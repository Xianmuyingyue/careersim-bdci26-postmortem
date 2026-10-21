#!/usr/bin/env python3
"""抽取每局的「风险读数」轨迹（agent 自述的 HR 档位），用于判断 M42 前是否做到谨慎风控。

识别：risk=0/1/2/3 或 绿/黄/橙/红 灯 + 月号。
用法：python3 analysis/risk_trace.py <run_dir> [起月] [止月]
"""
import os
import re
import sys
from collections import defaultdict

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

# "M18 ... risk=1 (黄)" / "风险绿0" / "读数=2 (橙)" / "risk≈2红"
PAT = re.compile(
    r"(?:M(\d{1,2})[^\n]{0,120}?)?(?:risk\s*[=＝≈]?\s*(\d)|风险\s*[^。\n]{0,12}?(绿|黄|橙|红)\s*(\d)?)",
)
LAMP = {"绿": 0, "黄": 1, "橙": 2, "红": 3}


def main():
    run_dir = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    p = os.path.join(OUT, run_dir, "transcript-%s.log" % run_dir)
    t = open(p, encoding="utf-8", errors="replace").read()
    by_month = defaultdict(list)
    cur = None
    for m in PAT.finditer(t):
        mo = int(m.group(1)) if m.group(1) else cur
        if m.group(1):
            cur = mo
        if mo is None or not (lo <= mo <= hi):
            continue
        if m.group(2) is not None:
            val = int(m.group(2))
        else:
            val = LAMP.get(m.group(3), None)
            if val is not None and m.group(4):
                val = int(m.group(4))
        if val is None:
            continue
        by_month[mo].append(val)
    print("月  样本(读数)              最高档")
    for mo in sorted(by_month):
        vals = by_month[mo]
        lamp = ["绿", "黄", "橙", "红"][min(max(vals), 3)]
        print("M%-3d %-22s %s" % (mo, str(vals)[:22], lamp))


if __name__ == "__main__":
    main()
