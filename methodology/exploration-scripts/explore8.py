"""Sequential exploration driver: run N CareerSim games back-to-back and record metrics.

Usage:
    python3 analysis/explore8.py [N]

Writes:
    ../.workbuddy/logs/explore/run<i>_play.log      per-run raw play output
    ../.workbuddy/logs/explore/results.tsv          one row per finished run
    ../.workbuddy/logs/explore/metrics/<run>.json   full metric dump
    ../.workbuddy/logs/explore/driver.log           driver-level progress
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import TSV_HEADER, metrics, tsv_row  # noqa: E402

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
LOGDIR = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore")
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
PY = sys.executable

# `career_sim_runner` shells out to the `jiuwenswarm-start` console script, which
# lives in .venv/bin. `uv run` puts it on PATH; a bare venv interpreter does not.
_VENV_BIN = os.path.join(REPO, ".venv", "bin")
os.environ["PATH"] = _VENV_BIN + os.pathsep + os.environ.get("PATH", "")


def log(message: str) -> None:
    stamp = time.strftime("%F %T")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with open(os.path.join(LOGDIR, "driver.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], logfile: str, timeout: int | None = None) -> int:
    with open(logfile, "w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT,
                              timeout=timeout)
    return proc.returncode


def backend_up(port: int = 19092) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_backend() -> bool:
    """Return True if the AgentServer is reachable; try one detached restart if not."""
    if backend_up():
        return True
    log("backend DOWN — attempting detached restart of jiuwenswarm instance")
    start_log = os.path.join(LOGDIR, "instance_restart.log")
    with open(start_log, "a", encoding="utf-8") as fh:
        subprocess.Popen(
            ["jiuwenswarm-start", "--name", "career_emu", "all"],
            cwd=REPO, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(60):  # wait up to 5 minutes
        time.sleep(5)
        if backend_up():
            log("backend recovered")
            return True
    log("backend did not recover within 300s")
    return False


def newest_output_dir() -> str | None:
    if not os.path.isdir(OUTROOT):
        return None
    dirs = [os.path.join(OUTROOT, d) for d in os.listdir(OUTROOT)
            if os.path.isdir(os.path.join(OUTROOT, d))]
    return max(dirs, key=os.path.getmtime) if dirs else None


def main() -> int:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    os.makedirs(LOGDIR, exist_ok=True)
    os.makedirs(os.path.join(LOGDIR, "metrics"), exist_ok=True)

    results = os.path.join(LOGDIR, "results.tsv")
    if not os.path.exists(results):
        with open(results, "w", encoding="utf-8") as fh:
            fh.write(TSV_HEADER + "\n")

    consecutive_failures = 0
    for i in range(1, total + 1):
        log(f"=========== RUN {i}/{total} START ===========")
        if not ensure_backend():
            log(f"RUN {i} skipped: backend unreachable")
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log("3 consecutive backend failures — aborting driver")
                return 1
            continue
        before = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        play_log = os.path.join(LOGDIR, f"run{i:02d}_play.log")

        try:
            code = run([PY, "-m", "career_sim_runner", "play", "--submission", "solution"],
                       play_log, timeout=3600)
        except subprocess.TimeoutExpired:
            log(f"RUN {i} TIMEOUT after 3600s")
            code = -1
        log(f"RUN {i} play exit={code}")

        after = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        created = sorted(after - before, key=lambda d: os.path.getmtime(
            os.path.join(OUTROOT, d)))
        target = os.path.join(OUTROOT, created[-1]) if created else newest_output_dir()

        if code != 0 or target is None:
            consecutive_failures += 1
            log(f"RUN {i} FAILED (exit={code}, dir={target})")
            if consecutive_failures >= 3:
                log("3 consecutive failures — aborting driver")
                return 1
            time.sleep(20)
            continue
        consecutive_failures = 0

        # ensure a replay markdown exists for this run
        if not any(f.startswith("replay-") for f in os.listdir(target)):
            events = [f for f in os.listdir(target) if f.startswith("events-")]
            if events:
                run([PY, "-m", "career_sim_runner", "replay",
                     "--events", os.path.join(target, events[0])],
                    os.path.join(LOGDIR, f"run{i:02d}_replay.log"), timeout=600)

        try:
            m = metrics(target)
        except Exception as exc:  # noqa: BLE001
            log(f"RUN {i} metrics extraction failed: {exc!r}")
            continue

        with open(os.path.join(LOGDIR, "metrics", f"{os.path.basename(target)}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
        with open(results, "a", encoding="utf-8") as fh:
            fh.write(tsv_row(m) + "\n")

        log(f"RUN {i} DONE dir={os.path.basename(target)} grade={m.get('grade')} "
            f"score={m.get('score')} months={m.get('months')} "
            f"level={m.get('final_level')} wealth={m.get('raw_wealth')} "
            f"bursts={m.get('bursts')} tokens={m.get('tokens')}")

    log(f"=========== ALL {total} RUNS FINISHED ===========")
    return 0


if __name__ == "__main__":
    sys.exit(main())
