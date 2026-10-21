"""Re-extract metrics for every COMPLETED run using the CURRENT run_metrics logic.

Why this exists
---------------
The exploration driver (`explore8.py`) imports `run_metrics` once at process
start. Any later improvement — a new talk-tier fingerprint, a refined HR ladder,
a renamed column — does NOT affect rows it has already written. Meanwhile the
RESTART budget is precious: restarting the driver would discard an in-flight run.

So instead of restarting, regenerate `results.tsv` afterwards from the raw
per-run artefacts, which are the authoritative source:
    events-*.jsonl      -> observe payloads (HR ladder, bursts)
    replay-*.md         -> turn-by-turn state + talk fingerprints
    score_report.json   -> ending score, dimensions, tokens

Safety
------
Refuses to run while the driver is alive, because it would race the driver's
own append to results.tsv. Pass --force to override (you almost never want to).

Usage
-----
    python3 analysis/recollect.py            # driver must be stopped
    python3 analysis/recollect.py --force    # override the guard
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import TSV_HEADER, metrics, tsv_row  # noqa: E402

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
LOGDIR = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore")
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")


def driver_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "explore8.py"], capture_output=True)
    return r.returncode == 0


def completed_dirs() -> list[str]:
    """Run dirs that actually finished: must carry a score_report.json."""
    out = []
    for d in sorted(glob.glob(os.path.join(OUTROOT, "*"))):
        if not os.path.isdir(d):
            continue
        names = os.listdir(d)
        if not any(f.startswith("events-") for f in names):
            continue
        if not os.path.exists(os.path.join(d, "score_report.json")):
            continue  # incomplete / crashed run
        out.append(d)
    return out


def main() -> int:
    force = "--force" in sys.argv
    if driver_running() and not force:
        print("驱动仍在运行 —— 拒绝重算（会与驱动的 append 竞争）。")
        print("等 8 局跑完后再执行，或加 --force 强制。")
        return 1

    dirs = completed_dirs()
    if not dirs:
        print("未找到已完成的对局（需同时具备 events-*.jsonl 与 score_report.json）。")
        return 0

    os.makedirs(os.path.join(LOGDIR, "metrics"), exist_ok=True)
    tsv = os.path.join(LOGDIR, "results.tsv")
    rows, bad = [], []
    for d in dirs:
        try:
            m = metrics(d)
        except Exception as exc:  # noqa: BLE001
            bad.append((os.path.basename(d), repr(exc)))
            continue
        if m.get("score") is None:
            bad.append((os.path.basename(d), "score is None"))
            continue
        rows.append(m)
        with open(os.path.join(LOGDIR, "metrics", f"{os.path.basename(d)}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)

    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write(TSV_HEADER + "\n")
        for m in rows:
            fh.write(tsv_row(m) + "\n")

    print(f"已重算 {len(rows)} 局 -> {tsv}")
    if bad:
        print(f"跳过 {len(bad)} 个目录：")
        for name, why in bad:
            print(f"  - {name}: {why}")

    # refresh the human-readable summary as well
    summary = os.path.join(os.path.dirname(os.path.abspath(__file__)), "summarize8.py")
    if os.path.exists(summary):
        subprocess.run([sys.executable, summary], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
