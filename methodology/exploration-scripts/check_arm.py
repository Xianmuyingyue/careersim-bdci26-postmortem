#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
臂快照校验（可复用）：对 analysis/ab/<arm>/ 做三件事
  1) 契约校验：`---` 起闭、frontmatter 合法 YAML、name + description 非空（description > 20 字符）
  2) 合规校验：交付物不得出现引擎内部符号（源码名/配置键/内部函数名/*_conditions）
  3) 与另一臂对比：行数 + md5 差异（用于确认改动范围）

用法：
  .venv/bin/python3 analysis/check_arm.py v10b
  .venv/bin/python3 analysis/check_arm.py v10b --vs v10
"""
import re
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AB = ROOT / "analysis" / "ab"
SKILLS = ["decision-policy", "risk-guardian", "situation-awareness"]

# 引擎内部符号（交付前必须清零）；ALLOW 为可观察输入字段白名单
BAD = re.compile(
    r"\.py\b|\.data\b|\.json\b|config\.|::|源码|写死|行号"
    r"|promotion_conditions|salary_conditions|optional_conditions"
    r"|_on_month_advanced|apply_delta|apply_level_delta|_evaluate_failure_conditions"
    r"|wealth_scale|streak_tracking|min_duration_in_level|rapid_promotion"
    r"|increment_when|trigger_condition"
)
ALLOW = re.compile(r"^(current_state|current_event|simulation_flags|status|time)\.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    arm = sys.argv[1]
    vs = sys.argv[sys.argv.index("--vs") + 1] if "--vs" in sys.argv else None
    dst = AB / arm
    if not dst.exists():
        print(f"!! {dst} 不存在")
        sys.exit(1)

    print(f"=== 臂校验: {arm} ===")
    print("\n【1】契约校验")
    ok_all = True
    for s in SKILLS:
        f = dst / s / "SKILL.md"
        if not f.exists():
            print(f"  {s:<22} !! 缺失")
            ok_all = False
            continue
        L = f.read_text(encoding="utf-8").splitlines()
        fm_end = next((i for i, x in enumerate(L[1:], 1) if x.strip() == "---"), -1)
        fm = "\n".join(L[1:fm_end]) if fm_end > 0 else ""
        nm = re.search(r"^name:\s*(\S.*)$", fm, re.M)
        ds = re.search(r"^description:\s*(\S.*)$", fm, re.M)
        good = L[0].strip() == "---" and fm_end > 0 and bool(nm) and bool(ds and len(ds.group(1)) > 20)
        ok_all &= good
        print(f"  {s:<22} {len(L):>4} 行  {'PASS' if good else 'FAIL'}"
              f"  name={'有' if nm else '无'} desc={'有' if ds else '无'}")
    print(f"  契约 = {'PASS' if ok_all else 'FAIL'}")

    print("\n【2】合规校验（引擎内部符号残留）")
    left = []
    for s in SKILLS:
        f = dst / s / "SKILL.md"
        if not f.exists():
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in BAD.finditer(line):
                if ALLOW.match(m.group(0)):
                    continue
                left.append((s, i, m.group(0), line.strip()[:100]))
    if left:
        for s, i, sym, line in left:
            print(f"  !! {s} : L{i} : [{sym}] {line}")
    else:
        print("  无残留 PASS")

    if vs:
        print(f"\n【3】与 {vs} 对比")
        for s in SKILLS:
            a, b = AB / vs / s / "SKILL.md", dst / s / "SKILL.md"
            if not (a.exists() and b.exists()):
                continue
            ha = hashlib.md5(a.read_bytes()).hexdigest()
            hb = hashlib.md5(b.read_bytes()).hexdigest()
            la = len(a.read_text(encoding="utf-8").splitlines())
            lb = len(b.read_text(encoding="utf-8").splitlines())
            print(f"  {s:<22} {vs}={la:>4}行/{ha[:8]}  →  {arm}={lb:>4}行/{hb[:8]}  "
                  f"{'相同' if ha == hb else f'差异 {lb-la:+d} 行'}")


if __name__ == "__main__":
    main()
