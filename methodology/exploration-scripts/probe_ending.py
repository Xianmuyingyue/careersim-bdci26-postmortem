#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_ending.py —— 从某局的 events/transcript 里定位引擎 `ending_score` 原始 JSON。

transcript 里的副本常常被截断（写盘时进程已崩），因此优先扫 events：
events 每行一个 JSON，末端通常带 a2ui 载荷，其中嵌有 ending_score 的完整对象。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def scan_text(text: str) -> dict | None:
    """找最后一个含 outcome + competition_partial_score 的 JSON 对象（容忍前后噪声）。"""
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


def main() -> int:
    d = Path(sys.argv[1])
    for pat, label in (("events-*.jsonl", "events"), ("transcript-*.log", "transcript")):
        for f in sorted(d.glob(pat)):
            text = f.read_text(encoding="utf-8", errors="replace")
            # events 里 JSON 是转义后嵌入的 ⇒ 先反转义再扫
            cand = scan_text(text) or scan_text(text.replace('\\"', '"').replace('\\n', '\n'))
            if cand:
                print(f"[{label}] {f.name} → 解析到 ending_score")
                print(json.dumps(cand, ensure_ascii=False, indent=2)[:900])
                return 0
    print("未解析到 ending_score")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
