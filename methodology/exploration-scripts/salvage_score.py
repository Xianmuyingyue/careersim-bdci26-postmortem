#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""salvage_score.py —— 抢救「对局已完赛、但收尾时 play 崩溃导致 score_report.json 缺失」的局。

背景（2026-09-29）：v13 RUN1 attempt 1 打完 48 个月（引擎印 `GAME OVER: Completed`，
agent 也回显了 ending_score），但 runner 在收尾阶段撞上
`websockets.ConnectionClosedError: keepalive ping timeout` ⇒ 未写 score_report.json
⇒ ab_driver 视为失败并重试。

做法：复用官方 `build_score_report()`（官方 `score` 子命令的同一函数），
显式传目标是局目录 + 其 events/transcript；`ending_score` 由 transcript 里的
引擎原始 JSON 块解析（**不是我们编的数字**）。

用法：
    .venv/bin/python3 analysis/salvage_score.py <run_dir> [--apply]
默认 dry-run（只打印解析出的 ending_score，不写文件）。
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import sys
from pathlib import Path

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
sys.path.insert(0, REPO)

from career_sim_runner.cli import default_db_path, load_active_install  # noqa: E402
from career_sim_runner.models import TokenUsage  # noqa: E402
from career_sim_runner.score import build_score_report, write_score_report  # noqa: E402


def find(dir_: Path, pat: str) -> Path | None:
    hits = sorted(glob.glob(str(dir_ / pat)))
    return Path(hits[-1]) if hits else None


def _scan(text: str) -> dict | None:
    """找最后一个含 outcome + competition_partial_score 的 JSON 对象。"""
    dec = json.JSONDecoder()
    best = None
    for m in re.finditer(r'\{\s*"outcome"', text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
        except Exception:
            continue
        if isinstance(obj, dict) and "competition_partial_score" in obj:
            best = obj
    return best


def extract_ending(d: Path) -> dict:
    """events 优先（transcript 里的副本常被截断）。events 内 JSON 是转义嵌入 ⇒ 反转义再扫。"""
    for pat in ("events-*.jsonl", "transcript-*.log"):
        for f in sorted(d.glob(pat)):
            raw = f.read_text(encoding="utf-8", errors="replace")
            hit = _scan(raw) or _scan(raw.replace('\\"', '"').replace('\\n', '\n'))
            if hit:
                return hit
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--apply", action="store_true", help="真正写入 score_report.json")
    args = ap.parse_args()

    d = Path(args.run_dir)
    if not d.is_dir():
        print(f"no such dir: {d}", file=sys.stderr)
        return 2
    if (d / "score_report.json").exists():
        print("score_report.json 已存在，无需抢救")
        return 0

    install = load_active_install()
    if install is None:
        print("no active install found", file=sys.stderr)
        return 2

    tokens = TokenUsage()
    ending = extract_ending(d)
    if not ending:
        print("既无法从 DB、也无法从 events/transcript 解析出 ending_score ⇒ 放弃抢救", file=sys.stderr)
        return 3
    report = asyncio.run(build_score_report(
        install_record=install,
        db_path=default_db_path(),
        output_dir=d,
        token_usage=tokens,
        play_exit_code=1,            # 如实记录：收尾崩溃
        termination_reason="finalize_crash_ws_keepalive",
        transcript_path=find(d, "transcript-*.log"),
        events_path=find(d, "events-*.jsonl"),
    ))
    report.ending_score = ending
    print("outcome=%s grade=%s score=%s months=%s completed=%s"
          % (ending.get("outcome"), ending.get("grade"), ending.get("quantitative_score"),
             ending.get("survival_months"), ending.get("completed")))
    if args.apply:
        p = write_score_report(report, d)
        print(f"WROTE {p}")
    else:
        print("(dry-run；加 --apply 才写入)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
