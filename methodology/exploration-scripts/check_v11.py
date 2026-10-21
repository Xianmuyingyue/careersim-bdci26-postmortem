#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_v11.py —— v11 臂的交付前校验。

检查项（对照项目硬约束与横向分析的结论）：
  ① frontmatter：name / description 非空
  ② 体量：三文件字符数与占比（对照 v3 13.1K / v8_3 43.1K / v10e 72.6K）
  ③ 条款计数：约束条数（目标 ≤30）、禁止/必须类词频
  ④ ★ 禁入项：不得出现「赌本分层 / 安全垫 = health − 4k / 零容错区 / 低血例外优先于暴露窗」
  ⑤ ★ 必含项：暴露窗(11) 与 L1 毕业线(12) 排在任何"低血/保守"判据之前；
      L1 毕业线必须有"如何守住 output"的执行手段；主行动「低调避险」必须有硬上限
  ⑥ 发展轴条款：L5@30/L6@42、闲置体力=放弃晋升、能推就推、主行动默认关键项目
"""
from __future__ import annotations

import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARM = os.path.join(REPO, "analysis", "ab", "v11")
SKILLS = ("situation-awareness", "risk-guardian", "decision-policy")

FORBIDDEN = [
    "赌本分层", "Health Bankroll", "安全垫 = health", "安全垫=health",
    "零容错区", "收紧区", "低血顺位", "低血例外",
]
REQUIRED = [
    ("暴露窗优先于风险", "暴露窗口保护区(11)"),
    ("L1 毕业线排在风险前", "L1毕业线(12) > 暴露窗口保护区(11)"),
    ("L1 毕业线有执行手段", "守住 `output` 的具体手段"),
    ("低调避险硬上限", "否则不得占用主行动位"),
    ("长期职级目标", "L5 @ 月 30"),
    ("闲置体力=放弃晋升", "闲置体力 = 放弃晋升"),
    ("能推就推", "能推就推"),
    ("主行动默认关键项目", "默认选择"),
    ("截断转负门禁", "截断转负门禁"),
    ("长链整链", "长链整链零成本律"),
    ("暴露窗两步法", "描述最长"),
]


def main() -> None:
    texts = {}
    print("=" * 90)
    print("① frontmatter 与体量")
    print("=" * 90)
    total = 0
    for s in SKILLS:
        p = os.path.join(ARM, s, "SKILL.md")
        if not os.path.exists(p):
            print(f"  ✗ 缺失 {s}")
            continue
        t = open(p, encoding="utf-8").read()
        texts[s] = t
        total += len(t)
        name = re.search(r"^name:\s*(\S+)", t, re.M)
        desc = re.search(r"^description:\s*(.+)$", t, re.M)
        ok = bool(name and name.group(1).strip()) and bool(desc and desc.group(1).strip())
        print(f"  {'✓' if ok else '✗'} {s:<22} {len(t):>7} 字符   "
              f"name={name.group(1) if name else '—'}   "
              f"description {len(desc.group(1)) if desc else 0} 字符")
    print(f"\n  合计 {total:,} 字符   （对照：v3 13,071 / v8_3 43,078 / v10e 72,556）")
    print(f"  相对 v3 = {total/13071:.2f}×　相对 v8_3 = {total/43078:.2f}×")

    all_t = "\n".join(texts.values())

    print()
    print("=" * 90)
    print("② 条款计数")
    print("=" * 90)
    rg = texts.get("risk-guardian", "")
    cons = set()
    for m in re.finditer(r"^\|\s*(\d+[a-f]?)\s*\|", rg, re.M):
        v = m.group(1)
        if re.fullmatch(r"\d+[a-f]?", v):
            cons.add(v)
    print(f"  risk-guardian 约束编号：{sorted(cons, key=lambda x: (len(x), x))}"
          f"  → {len(cons)} 条")
    for w in ("禁止", "不得", "必须", "绝不", "一票否决", "例："):
        print(f"    「{w}」出现 {all_t.count(w)} 次")

    print()
    print("=" * 90)
    print("③ ★ 禁入项检查（v10e 的致命机制不得残留）")
    print("=" * 90)
    bad = [w for w in FORBIDDEN if w in all_t]
    if bad:
        for w in bad:
            print(f"  ✗ 出现禁入词：{w}")
    else:
        print("  ✓ 无赌本分层 / 安全垫 / 零容错区 / 低血顺位 残留")

    print()
    print("=" * 90)
    print("④ ★ 必含项检查")
    print("=" * 90)
    for label, needle in REQUIRED:
        hit = needle in all_t
        print(f"  {'✓' if hit else '✗'} {label:<24} （锚点「{needle}」）")

    print()
    print("=" * 90)
    print("⑤ 冲突裁决顺序（RG 内文字核对）")
    print("=" * 90)
    m = re.search(r"```\n(health≤3.*?)```", rg, re.S)
    if m:
        for line in m.group(1).strip().split("\n"):
            print("   " + line.strip())
    else:
        print("  ✗ 未找到冲突裁决顺序块")


if __name__ == "__main__":
    main()
