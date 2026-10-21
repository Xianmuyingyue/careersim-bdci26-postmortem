"""两大高分对局（144338Z=72.38/A、194245Z=69.46/B）的大周期经验抽取。

目标（对应任务 B 第 4 句「从 2 次 score 高的跑分中，抽取大周期决策的经验」）：
把两局放到同一张「24 个月尺度」的对照表上，回答：

  Q4  跨半个赛程看，两局的资源是怎么分布的？（分段增量 / 主行动 / 体力构成）
  Q5  每个晋升窗口的瓶颈维是谁？两局是否同构？
  Q6  哪些大周期规律是「两局都成立」的（=> 可以固化为策略铁律），
      哪些只是单局偶然（=> 不可写进技能）？

方法：完全复用 postmortem_run.analyze（含 HiddenRisk 的真实事件池重建）。
输出：analysis/bigcycle_2runs.md（人读） + stdout（表格）。
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import (  # noqa: E402
    GATES, KEYMAP, OUTROOT, analyze,
)

RUNS = [("20260924T144338Z", "A", 72.38), ("20260924T194245Z", "B", 69.46)]
REVIEW_MONTHS = [5, 11, 17, 23, 29, 35, 41, 47]
KEYS = ["skill", "network", "output", "dignity", "health", "hidden_risk"]
# 分段（大周期）：以评审窗口为边界，共 8 段
SEGMENTS = [(1, 5), (6, 11), (12, 17), (18, 23), (24, 29), (30, 35), (36, 41), (42, 47), (48, 48)]


def level_at(a, month):
    mo = next((m for m in a["months"] if m["month"] == month), None)
    if mo is None:
        return None, None
    lv = None
    for t in mo["turns"]:
        if t["state"] and t["state"].get("level"):
            lv = t["state"]["level"]
    return mo, lv


def window_table(a, label):
    """每个晋升窗口：职级 / 四门余量 / 瓶颈 / 是否放行。"""
    print("\n" + "=" * 104)
    print(f"[{label}] 晋升窗口审计（余量 = 实际 − 门槛；负数即瓶颈）")
    print("=" * 104)
    print(f"{'窗口':>5} {'职级':>5} {'晋升':>6} | "
          f"{'Δskill':>10} {'Δnetwork':>10} {'Δoutput':>10} {'Δdignity':>10} | 瓶颈")
    rows = []
    for m in REVIEW_MONTHS:
        mo, lv = level_at(a, m)
        if mo is None or lv is None:
            continue
        s = mo["snap_end"]
        g = GATES.get(lv)
        if g is None:
            continue
        slack = {"skill": s["skill"] - g[0], "network": s["network"] - g[1],
                 "output": s["output"] - g[2], "dignity": s["dignity"] - g[3]}
        neg = [k for k, v in slack.items() if v < 0]
        bottleneck = ", ".join(f"{k}{slack[k]:+.0f}" for k in
                               sorted(slack, key=lambda k: slack[k])[:2]) if neg else "（无缺口）"
        promo = mo["promo"][1] if mo["promo"] else "×"
        print(f"M{m:<4d} {lv:>5} {promo:>6} | "
              f"{slack['skill']:>+10.0f} {slack['network']:>+10.0f} "
              f"{slack['output']:>+10.0f} {slack['dignity']:>+10.0f} | {bottleneck}")
        rows.append({"m": m, "lv": lv, "promo": promo, "slack": slack,
                     "bottleneck": bottleneck, "end": dict(s)})
    return rows


def segment_gains(a, label):
    """每段（6 个月）内各属性的净增量 + 该段获取率 + 行动构成。"""
    print("\n" + "=" * 104)
    print(f"[{label}] 大周期分段：每 6 个月的属性净增量与获取率")
    print("=" * 104)
    out = []
    for lo, hi in SEGMENTS:
        mos = [m for m in a["months"] if lo <= m["month"] <= hi]
        if not mos:
            continue
        start = mos[0]["snap_start"]
        end = mos[-1]["snap_end"]
        gain = {k: end.get(k, 0) - start.get(k, 0) for k in KEYS}
        # capture rate within the segment
        opp = Counter()
        rea = Counter()
        for mo in mos:
            for r in [x for x in a["rows"] if x["month"] == mo["month"]]:
                for off in r["offered"]:
                    for kk, v in off.items():
                        k = KEYMAP.get(kk)
                        if k in KEYS:
                            opp[k] += max(0.0, float(v))
                for kk, v in r["delta"].items():
                    k = KEYMAP.get(kk)
                    if k in KEYS:
                        rea[k] += max(0.0, float(v))
        rate = {k: (rea[k] / opp[k] * 100 if opp[k] else float("nan")) for k in KEYS}
        out.append({"seg": f"M{lo}-M{hi}", "gain": gain, "rate": rate, "opp": opp, "rea": rea})
        print(f"M{lo:>2}-M{hi:<2} | "
              f"S{gain['skill']:>+5.0f}({rate['skill']:>5.1f}%) "
              f"N{gain['network']:>+5.0f}({rate['network']:>5.1f}%) "
              f"O{gain['output']:>+5.0f}({rate['output']:>5.1f}%) "
              f"D{gain['dignity']:>+4.0f} H{gain['health']:>+4.0f} "
              f"R{gain['hidden_risk']:>+4.0f}  [终值 S{end.get('skill',0):.0f} "
              f"N{end.get('network',0):.0f} O{end.get('output',0):.0f}]")
    return out


def action_mix(a, label):
    """主行动 / 体力行动构成（全局 + 分段）。"""
    print("\n" + "=" * 104)
    print(f"[{label}] 行动构成")
    print("=" * 104)
    energy = Counter()
    main = Counter()
    per_seg_energy = defaultdict(Counter)
    for r in a["rows"]:
        choice = (r["choice"] or "")
        choice = choice.strip()
        # strip "[n] " index and trailing reason
        for pre in ("[",):
            pass
        import re
        c = re.sub(r"^\[\d+\]\s*", "", choice).split("—")[0].strip()
        if c in ("高强度工作", "技能学习", "人脉维护", "处理历史埋雷",
                 "心理修复", "健康恢复", "准备汇报材料", "保留体力（不行动）", "不行动"):
            energy[c] += 1
            for lo, hi in SEGMENTS:
                if lo <= r["month"] <= hi:
                    per_seg_energy[f"M{lo}-M{hi}"][c] += 1
        elif c in ("申请关键项目", "向领导汇报成果", "主动争取资源", "申请岗位轮岗",
                   "主动曝光成果", "建立导师关系", "修复关键关系", "低调避险", "不行动"):
            main[c] += 1
    print("体力行动：", dict(energy.most_common()))
    print("主  行动：", dict(main.most_common()))
    print("\n分段体力（技能学习 / 准备汇报材料）：")
    for k in sorted(per_seg_energy, key=lambda x: int(x.split("-")[0][1:])):
        c = per_seg_energy[k]
        print(f"  {k:<9} 技能学习 {c.get('技能学习',0):>2} | 准备汇报 {c.get('准备汇报材料',0):>2} "
              f"| 健康恢复 {c.get('健康恢复',0):>2} | 处理历史埋雷 {c.get('处理历史埋雷',0):>2}")
    return energy, main, per_seg_energy


def risk_profile(a, label):
    print("\n" + "=" * 104)
    print(f"[{label}] 风险画像")
    print("=" * 104)
    inj = Counter()
    clr = Counter()
    peak = 0
    peak_ms = []
    first_hit = {}
    for r in a["rows"]:
        d = float(r["delta"].get("HiddenRisk", 0.0))
        t = r["title"][:20]
        if d > 0:
            inj[t] += d
        elif d < 0:
            clr[t] += -d
        if r["post"]["hidden_risk"] > peak:
            peak = r["post"]["hidden_risk"]
            peak_ms = [r["month"]]
        elif r["post"]["hidden_risk"] == peak:
            peak_ms.append(r["month"])
        for w in ("皱着眉头", "神情复杂", "生气"):
            pass
    # HR ladder
    lad = Counter()
    for mo in a["months"]:
        if mo["hr"]:
            code, word = mo["hr"]
            lad[word] += 1
    print(f"峰值 hidden_risk={peak:.0f} @ M{peak_ms[0] if peak_ms else '-'}  终值={a['rec']['hidden_risk']:.0f}")
    print(f"注入回合 {sum(1 for r in a['rows'] if float(r['delta'].get('HiddenRisk',0))>0)} 次 / "
          f"清理回合 {sum(1 for r in a['rows'] if float(r['delta'].get('HiddenRisk',0))<0)} 次")
    print("Top 注入源：", dict(inj.most_common(6)))
    print("Top 清理源：", dict(clr.most_common(6)))
    return {"peak": peak, "peak_ms": peak_ms, "inj": inj, "clr": clr}


def fmt_svg_bar(a, b, key):
    return None


def main():
    analyses = {}
    for run, grade, score in RUNS:
        a = analyze(run)
        analyses[run] = a
    lines = []
    for run, grade, score in RUNS:
        a = analyses[run]
        label = f"{run[:8]} {run[8:]} {grade} {score}"
        print("\n\n" + "#" * 104)
        print(f"# {label}   回合={len(a['rows'])}  未匹配={a['unmatched']}")
        print(f"# 重建终值 " + " ".join(f"{k}={a['rec'].get(k,0):.1f}" for k in KEYS + ['wealth']))
        print("#" * 104)
        window_table(a, label)
        segment_gains(a, label)
        action_mix(a, label)
        risk_profile(a, label)

    # ------- 交叉结论 -------
    print("\n\n" + "=" * 104)
    print("跨局比对：哪些大周期规律两局都成立？")
    print("=" * 104)
    for run, grade, score in RUNS:
        a = analyses[run]
        lv, seg, act, rp = window_table(a, run), segment_gains(a, run), action_mix(a, run), risk_profile(a, run)
        # bottleneck of M41 window (L5->L6 first chance)
        m41 = next((r for r in lv if r["m"] == 41), None)
        print(f"\n[{run}] L5→L6 首窗(M41)瓶颈: {m41['bottleneck'] if m41 else '-'}")


if __name__ == "__main__":
    main()
