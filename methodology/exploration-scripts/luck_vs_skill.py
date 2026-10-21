"""跨局「运气 vs 实力」分布：把单局结果放进同一套供给/获取口径里比较。

对每一局（15 局）计算：
  · Supply(X)    = Σ_turn max_offer(ΔX)       ← 引擎抽到的事件给了多少（运气）
  · Greedy(X)    = 每回合取该属性最大选项后的终值（同一副牌下的能力上界）
  · Actual(X)    = 实际终值
  · Capture(X)   = Actual / Supply（正向口径）← 纯技术指标（实力）
  · RiskFloor    = Σ_turn min_offer(ΔRisk)    ← 该手牌下最低可注入风险（运气）
  · RiskExcess   = Σ_turn chosen(ΔRisk) - RiskFloor   ← 主动透支（实力缺口）

用途：判断 144338Z 的 L6 是否是「抽到好牌」的结果——即在同样一副牌
（同样的供给）下，一个贪心策略能否达到晋升门槛。若多数局的供给都足以
越过 L6 门槛，则「运气不是约束」，L6 的取得与错失都归因于选择。
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import GATES, KEYMAP, OUTROOT, analyze, clamps_at  # noqa: E402

KEYS = ["skill", "network", "output", "dignity", "health"]
GATES_TXT = {"L2": (8, 3, 3, 2), "L3": (18, 6, 5, 3), "L4": (35, 18, 14, 3),
             "L5": (90, 30, 22, 4), "L6": (130, 45, 32, 4), "L7": (170, 60, 45, 5)}
GATE_OF = {"L1": "L2", "L2": "L3", "L3": "L4", "L4": "L5", "L5": "L6", "L6": "L7"}


def runs():
    return sorted(d for d in os.listdir(OUTROOT)
                  if os.path.isdir(os.path.join(OUTROOT, d))
                  and any(f.startswith("replay-") for f in os.listdir(os.path.join(OUTROOT, d))))


def per_run(run):
    a = analyze(run)
    supply = Counter()
    actual_pos = Counter()
    risk_floor = 0.0
    risk_chosen = 0.0
    for r in a["rows"]:
        for off in r["offered"]:
            for kk, v in off.items():
                k = KEYMAP.get(kk)
                if k in KEYS:
                    supply[k] += max(0.0, float(v))
                elif k == "hidden_risk":
                    pass
        for kk, v in r["delta"].items():
            k = KEYMAP.get(kk)
            if k in KEYS:
                actual_pos[k] += max(0.0, float(v))
        if r["offered"]:
            risk_floor += min(float(o.get("HiddenRisk", 0.0)) for o in r["offered"])
        risk_chosen += float(r["delta"].get("HiddenRisk", 0.0))

    # greedy upper bound per attribute, on the same offer sequence
    greedy = {}
    for key in ("Skill", "Network", "Output"):
        v = {"skill": 1.0, "network": 1.0, "output": 0.0}[key.lower()]
        lvl = "L1"
        for r in a["rows"]:
            d = r["delta"]
            if r["offered"] and r["kind"] == "story":
                d = max(r["offered"], key=lambda x: x.get(key, -99))
            v += float(d.get(key, 0))
            cap = clamps_at(r["level"])[key.lower()]
            v = min(v, float(cap))
            v = max(0.0, v)
        greedy[key.lower()] = v

    levels = re.findall(r"\[Page|\[\[", "")
    return {"run": run, "rec": a["rec"], "supply": supply, "act": actual_pos,
            "risk_floor": risk_floor, "risk_chosen": risk_chosen, "greedy": greedy,
            "months": len(a["months"])}


def main():
    rows = []
    for r in runs():
        try:
            rows.append(per_run(r))
        except Exception as exc:  # noqa: BLE001
            print(f"skip {r}: {exc}")

    print("=" * 120)
    print("跨局供给/获取/贪心上界对照（15 局；供给=引擎给的正向增量总和，贪心=同一手牌下该属性最大化的终值）")
    print("=" * 120)
    hdr = (f"{'run':<18}{'月':>4}{'终L':>5}"
           f" | {'skill:供给':>10}{'贪心':>6}{'实际':>6}{'获取率':>8}"
           f" | {'net:供给':>9}{'贪心':>6}{'实际':>6}{'获取率':>8}"
           f" | {'out:供给':>9}{'贪心':>6}{'实际':>6}{'获取率':>8}"
           f" | {'风险余量':>8}{'风险超额':>8}")
    print(hdr)
    for r in rows:
        rec = r["rec"]
        lvl = "L1"
        # terminal level from the score file is not read here; approximate by caps
        def cap(s, g):
            return f"{r['supply'][s]:>10.0f}{g:>6.0f}{rec[s]:>6.0f}" \
                   f"{rec[s]/r['supply'][s]*100 if r['supply'][s] else 0:>7.1f}%"
        print(f"{r['run'][:18]:<18}{r['months']:>4}{'':>5}"
              f" | {cap('skill', r['greedy']['skill'])}"
              f" | {cap('network', r['greedy']['network'])}"
              f" | {cap('output', r['greedy']['output'])}"
              f" | {5 - rec['hidden_risk']:>8.0f}"
              f" | {r['risk_chosen'] - r['risk_floor']:>8.0f}")

    print("\n--- 供给是否构成约束：同一手牌下贪心上界能否越过门槛 ---")
    print(f"{'属性':<8}{'门槛(L5→L6)':>12}{'贪心≥门槛的局数':>16}{'占比':>8}   结论")
    for key, need in (("skill", 130), ("network", 45), ("output", 32)):
        n = sum(1 for r in rows if r["greedy"][key] >= need)
        verdict = "供给不是约束" if n / len(rows) >= 0.8 else "供给是硬约束"
        print(f"{key:<8}{need:>12}{n:>10}/{len(rows):<6}{n/len(rows)*100:>7.0f}%   {verdict}")

    import statistics as st
    for key, need in (("skill", 130), ("network", 45), ("output", 32)):
        vals = [r["greedy"][key] for r in rows]
        acts = [r["rec"][key] for r in rows]
        print(f"\n{key}: 贪心上界 均值 {st.mean(vals):.0f} 中位 {st.median(vals):.0f} "
              f"最小 {min(vals):.0f} 最大 {max(vals):.0f}")
        print(f"      实际终值 均值 {st.mean(acts):.0f} 中位 {st.median(acts):.0f} "
              f"最小 {min(acts):.0f} 最大 {max(acts):.0f}")
        print(f"      平均「上界−实际」缺口 {st.mean([g-a for g, a in zip(vals, acts)]):.0f}")

    print("\n--- 风险维度 ---")
    for r in sorted(rows, key=lambda x: -x["rec"]["hidden_risk"]):
        print(f"  {r['run'][:18]:<18} 终局 hidden_risk={r['rec']['hidden_risk']:>4.0f}  "
              f"风险下限={r['risk_floor']:>5.0f}  实际注入={r['risk_chosen']:>5.0f}  "
              f"过度削减(浪费)={min(0.0, r['risk_chosen'] - r['risk_floor']):>6.0f}")


if __name__ == "__main__":
    main()
