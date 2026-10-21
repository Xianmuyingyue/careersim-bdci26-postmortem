#!/usr/bin/env python3
"""从 transcript 抽取 agent 自述的状态快照（形如 "State: S42 O16 N21 D10 ..." 或 "M18. State: ..."）。

用法：python3 analysis/state_trace.py <run_dir> [起月] [止月]
"""
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

# 匹配 "…M18. State: <任意>" 或 "State: …"（前面 200 字符内找月份）
STATE_RE = re.compile(r"(?:M(\d{1,2})[^A-Za-z]{0,8})?State:\s*([^\n]{0,200})")
LVL_RE = re.compile(r"\bL(\d)\b")


def main():
    run_dir = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    p = os.path.join(OUT, run_dir, "transcript-%s.log" % run_dir)
    if not os.path.exists(p):
        print("no transcript:", p)
        return 1
    t = open(p, encoding="utf-8", errors="replace").read()
    seen, cur = set(), None
    for m in STATE_RE.finditer(t):
        mo = int(m.group(1)) if m.group(1) else None
        if mo is not None:
            cur = mo
        elif cur is not None:
            mo = cur
        if mo is None or not (lo <= mo <= hi):
            continue
        body = m.group(2).strip()
        key = (mo, body[:60])
        if key in seen:
            continue
        seen.add(key)
        # 就近取一个 Lx 作为 agent 自述职级
        seg = t[max(0, m.start() - 240):m.end() + 60]
        lv = LVL_RE.findall(seg)
        print("M%-3s %-9s %s" % (mo, ("L" + lv[-1]) if lv else "-", body[:170]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
