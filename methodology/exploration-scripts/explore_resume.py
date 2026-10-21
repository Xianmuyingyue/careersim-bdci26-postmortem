"""Resume an exploration batch: run N more games and append to results.tsv.

Why separate from explore8.py
-----------------------------
explore8.py always labels its runs 1..N and overwrites its own per-run logs.
This driver is for TOPPING UP a batch after environment failures: it
  * numbers its logs with a `resumeNN_` prefix so nothing collides,
  * appends to the same results.tsv,
  * treats a run as valid only when metrics extraction actually yields a score
    (an aborted run such as `max_continuations` produces a score_report.json
    with an EMPTY ending_score — that must NOT enter the dataset).

Usage:
    python3 analysis/explore_resume.py [N]     # default N=4
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import TSV_HEADER, metrics, tsv_row  # noqa: E402

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
LOGDIR = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore")
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
PY = sys.executable

# see launch_driver.py for why this is needed
os.environ["CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD"] = "100000"
os.environ["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + os.environ.get("PATH", "")


def log(message: str) -> None:
    line = f"[{time.strftime('%F %T')}] {message}"
    print(line, flush=True)
    with open(os.path.join(LOGDIR, "resume.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], logfile: str, timeout: int | None = None) -> int:
    with open(logfile, "w", encoding="utf-8") as fh:
        try:
            proc = subprocess.run(cmd, cwd=REPO, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            return -1
    return proc.returncode


def backend_up(port: int = 19092) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_backend() -> bool:
    if backend_up():
        return True
    log("backend DOWN — detached restart")
    with open(os.path.join(LOGDIR, "instance_restart.log"), "a", encoding="utf-8") as fh:
        subprocess.Popen(["jiuwenswarm-start", "--name", "career_emu", "all"],
                         cwd=REPO, stdin=subprocess.DEVNULL, stdout=fh,
                         stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(60):
        time.sleep(5)
        if backend_up():
            log("backend recovered")
            return True
    log("backend did not recover within 300s")
    return False


def main() -> int:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    os.makedirs(LOGDIR, exist_ok=True)
    stamp = time.strftime("%H%M%S")  # keep this batch's logs from clobbering earlier ones
    results = os.path.join(LOGDIR, "results.tsv")
    if not os.path.exists(results):
        with open(results, "w", encoding="utf-8") as fh:
            fh.write(TSV_HEADER + "\n")

    wins = fails = 0
    for i in range(1, total + 1):
        log(f"=========== RESUME {i}/{total} START ===========")
        if not ensure_backend():
            log(f"RESUME {i} skipped: backend unreachable")
            fails += 1
            if fails >= 3:
                log("3 consecutive failures — aborting")
                return 1
            continue

        before = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        play_log = os.path.join(LOGDIR, f"resume{stamp}_{i:02d}_play.log")
        code = run([PY, "-m", "career_sim_runner", "play", "--submission", "solution"],
                   play_log, timeout=3600)
        log(f"RESUME {i} play exit={code}")

        after = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        created = sorted(after - before, key=lambda d: os.path.getmtime(os.path.join(OUTROOT, d)))
        target = os.path.join(OUTROOT, created[-1]) if created else None

        if code != 0 or target is None:
            log(f"RESUME {i} FAILED (exit={code}, dir={target})")
            fails += 1
            if fails >= 3:
                log("3 consecutive failures — aborting")
                return 1
            time.sleep(20)
            continue

        if not any(f.startswith("replay-") for f in os.listdir(target)):
            events = [f for f in os.listdir(target) if f.startswith("events-")]
            if events:
                run([PY, "-m", "career_sim_runner", "replay",
                     "--events", os.path.join(target, events[0])],
                    os.path.join(LOGDIR, f"resume{stamp}_{i:02d}_replay.log"), timeout=600)

        try:
            m = metrics(target)
        except Exception as exc:  # noqa: BLE001
            log(f"RESUME {i} metrics failed: {exc!r}")
            fails += 1
            continue

        # an aborted run has a score_report.json with an EMPTY ending_score
        if m.get("score") is None:
            log(f"RESUME {i} INVALID (no score; likely max_continuations) — not recorded")
            fails += 1
            if fails >= 3:
                log("3 consecutive failures — aborting")
                return 1
            continue

        fails = 0
        wins += 1
        with open(os.path.join(LOGDIR, "metrics", f"{os.path.basename(target)}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
        with open(results, "a", encoding="utf-8") as fh:
            fh.write(tsv_row(m) + "\n")
        log(f"RESUME {i} DONE dir={os.path.basename(target)} grade={m.get('grade')} "
            f"score={m.get('score')} months={m.get('months')} "
            f"level={m.get('final_level')} wealth={m.get('raw_wealth')} "
            f"bursts={m.get('bursts')}")

    log(f"=========== RESUME BATCH FINISHED ({wins} ok / {fails} failed) ===========")
    return 0


if __name__ == "__main__":
    sys.exit(main())
