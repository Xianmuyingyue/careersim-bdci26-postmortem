#!/usr/bin/env python3
"""抽取某局 agent 的决策 notes（含 M/Q 前缀），用于看它在关键窗做了什么。

用法：python3 analysis/notes_by_month.py <run_dir> [起始月] [结束月]
"""
import json
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
M_RE = re.compile(r"\bM(\d+)")
Q_RE = re.compile(r"\bQ(\d+)")


def walk_notes(obj, out):
    """递归找所有 notes 字符串。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "notes" and isinstance(v, str):
                out.append(v)
            else:
                walk_notes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_notes(v, out)
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                walk_notes(json.loads(s), out)
            except Exception:
                pass


def main():
    run_dir = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    p = os.path.join(OUT, run_dir, "events-%s.jsonl" % run_dir)
    seen, rows = set(), []
    cur = None
    for line in open(p, encoding="utf-8", errors="replace"):
        if "notes" not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        got = []
        walk_notes(o, got)
        for note in got:
            m = M_RE.search(note)
            mo = int(m.group(1)) if m else None
            if mo is None:
                q = Q_RE.search(note)
                if q:
                    mo = int(q.group(1)) + 1        # Q 季度口径：Q1≈M1
                elif cur is not None:
                    mo = cur
            if mo is not None:
                cur = mo
            if mo is None or not (lo <= mo <= hi):
                continue
            key = (mo, note[:70])
            if key in seen:
                continue
            seen.add(key)
            rows.append((mo, note))
    for mo, note in sorted(rows, key=lambda x: x[0]):
        print("M%-3s %s" % (mo, note[:300]))


if __name__ == "__main__":
    main()
