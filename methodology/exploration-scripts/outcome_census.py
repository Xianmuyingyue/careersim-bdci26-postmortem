"""全批结局与死因普查：给出「完赛率 / 死因分布」，用于判断应优先修哪条防线。

失败规则各自的 HP 预算（failure_conditions/*.data 的 hp 字段，独立计数）：
    health_zero                  hp=1  -> HP<=0 一击必杀
    consecutive_bad_performance  hp=2  -> 2 次「半年绩效 perf<4」即出局
    risk_burst                   hp=2  -> 2 次 hidden_risk>=5 爆雷即出局
    dignity_crisis               hp=2  -> dignity<=1 连续 3 月
    network_isolated             hp=2  -> network<=1 连续 3 月
    wealth_deficit               hp=2  -> wealth<=0 连续 3 月
    skill_obsolete               hp=5  -> skill<=0（触发后 skill 被重置为 1）
"""
from __future__ import annotations

import os
import re
from collections import Counter

from perf_gate_audit import OUTROOT

OUT_RE = re.compile(r"出局:\*\*\s*(.+?)(?:\n|$)")


def main() -> None:
    c = Counter()
    rows = []
    for run in sorted(os.listdir(OUTROOT)):
        d = os.path.join(OUTROOT, run)
        if not os.path.isdir(d) or not any(f.startswith("replay-") for f in os.listdir(d)):
            continue
        rp = [f for f in os.listdir(d) if f.startswith("replay-")][0]
        txt = open(os.path.join(d, rp), encoding="utf-8").read()
        sr = open(os.path.join(d, "score_report.json"), encoding="utf-8").read()
        grade = re.search(r'"grade":\s*"(\w)"', sr).group(1)
        score = float(re.search(r'"quantitative_score":\s*([\d.]+)', sr).group(1))
        months = int(re.search(r'"survival_months":\s*(\d+)', sr).group(1))
        m = OUT_RE.search(txt)
        reason = m.group(1)[:40] if m else "完赛 48 月"
        c[reason.split("——")[0].strip()] += 1
        rows.append((run, grade, score, months, reason))

    print(f"{'run':>20} {'G':>2} {'score':>6} {'月':>4}  结局")
    print("-" * 100)
    for r in sorted(rows, key=lambda x: -x[2]):
        print(f"{r[0]:>20} {r[1]:>2} {r[2]:>6.2f} {r[3]:>4}  {r[4]}")

    print("\n=== 死因分布 ===")
    for k, v in c.most_common():
        print(f"  {v:>2}  {k}")
    done = sum(1 for r in rows if r[3] >= 48)
    print(f"\n  完赛率 {done}/{len(rows)}    A 级 {sum(1 for r in rows if r[1]=='A')}/{len(rows)}"
          f"    平均分 {sum(r[2] for r in rows)/len(rows):.2f}")
    print("  >=48月： " + ", ".join(r[0][-5:] for r in rows if r[3] >= 48))
    print("  <48月：  " + ", ".join(f"{r[0][-5:]}({r[3]})" for r in rows if r[3] < 48))


if __name__ == "__main__":
    main()
