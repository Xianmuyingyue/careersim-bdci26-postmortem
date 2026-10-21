"""144338Z（唯一 A 级，72.38）—— 深度因果复盘：实力 vs 运气定量分解。

回答三个问题：
  Q1  唯一一次晋升到 L6（第六级），关键决策做对了什么？
  Q2  全程零爆雷，靠的是什么操作？运气占多少？
  Q3  两件事里，实力与运气各占多少？给出数据支撑。

方法（三层，互相独立）
  L1  重建层：把 replay 的每个选择经官方事件池查表换成真实 status_updates，
      重建含 HiddenRisk 的完整轨迹，并用 raw_risk_control 做终局锚定。
  L2  审计层：把「晋升门槛」逐窗口对照（8 个半年窗口），算出每个窗口的缺口。
  L3  分解层：
      · 供给上限 Opportunity(运气)  = Σ_turn max_offer(ΔX)
      · 实际获取 Realized(实力)     = Σ_turn chosen(ΔX)
      · 获取率 Capture = Realized / Opportunity  ← 与剧本无关，纯技术指标
      · 风险注入 vs 同回合最低可选下限 → 主动超额风险
      · 反事实：同一手牌下「栅栏策略」能否更早晋升
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import (  # noqa: E402
    GATES, KEYMAP, OUTROOT, analyze, clamps_at, strip_idx,
)

RUN = "20260924T144338Z"
KEYS = ["skill", "network", "output", "dignity", "health"]

# review windows: display month -> 晋升评审发生在该月
REVIEW_MONTHS = [5, 11, 17, 23, 29, 35, 41, 47]


def state_at(a, month):
    for mo in a["months"]:
        if mo["month"] == month:
            return mo
    return None


def gate_audit(a):
    print("=" * 108)
    print("L2 晋升门槛逐窗口审计（8 个半年窗口；门槛取自 promotion/levels.json）")
    print("=" * 108)
    print(f"{'窗口':>4} {'职级':>4} {'目标':>4} | "
          f"{'skill':>14} {'network':>14} {'output':>14} {'dignity':>9} | 结果")
    for m in REVIEW_MONTHS:
        mo = state_at(a, m)
        if mo is None:
            continue
        s = mo["snap_end"]
        # observed level at this month (from the replay status line)
        lv = None
        for t in mo["turns"]:
            if t["state"] and t["state"].get("level"):
                lv = t["state"]["level"]
        if lv is None:
            continue
        g = GATES.get(lv)
        promoted = mo["promo"] is not None
        cells, ok = [], True
        for i, (name, gi) in enumerate(zip(KEYS[:3] + ["dignity"],
                                          [0, 1, 2, 3])):
            need = g[gi]
            have = s[name]
            good = have >= need
            ok = ok and good
            cells.append(f"{have:>6.0f}/{need:<4d}{'✓' if good else '✗'}")
        res = f"通过 → {mo['promo'][1]}" if promoted else ("门槛已达但未放行" if ok else "未达门槛")
        print(f"M{m:<3d} {lv:>4} {'→'+mo['promo'][1] if promoted else '—':>4} | "
              f"{cells[0]:>14} {cells[1]:>14} {cells[2]:>14} {cells[3]:>9} | {res}")


def risk_ledger(a):
    print("\n" + "=" * 108)
    print("L3a 风险账本（hidden_risk 的注入 / 清理 / 被下界吃掉的浪费）")
    print("=" * 108)
    inj = Counter()
    clr = Counter()
    raw_delta = 0.0
    wasted = 0.0
    traj = []
    for r in a["rows"]:
        d = float(r["delta"].get("HiddenRisk", 0.0))
        raw_delta += d
        if d > 0:
            inj[r["title"][:22]] += d
        elif d < 0:
            clr[r["title"][:22]] += -d
        pre = r["pre"]["hidden_risk"]
        post = r["post"]["hidden_risk"]
        uncapped = pre + d
        if uncapped < 0:
            wasted += -uncapped
        traj.append((r["month"], r["n"], r["title"][:22], d, pre, post, uncapped))
    peak = max(t[5] for t in traj)
    peak_m = [t[0] for t in traj if t[5] == peak]
    print(f"净注入（未加下界）{raw_delta:+.0f}   被 0 下界吃掉 {wasted:.0f}   "
          f"最终 hidden_risk = {a['rec']['hidden_risk']:.0f}（爆雷阈值 5）")
    print(f"全程峰值 hidden_risk = {peak:.0f}（出现在 M{peak_m[0]}）；"
          f"距阈值最少余量 = {5 - peak:.0f}")
    t3 = [t for t in traj if t[5] >= 3]
    print(f"hidden_risk ≥3 的回合数：{len(t3)}"
          + (f"（{', '.join('M%d' % t[0] for t in t3)}）" if t3 else ""))
    print("\nTop 注入源：")
    for k, v in inj.most_common(10):
        print(f"   +{v:<4.0f} {k}")
    print("Top 清理源：")
    for k, v in clr.most_common(10):
        print(f"   -{v:<4.0f} {k}")
    return {"raw_delta": raw_delta, "wasted": wasted, "peak": peak, "traj": traj,
            "inj": inj, "clr": clr}


def opportunity(a):
    print("\n" + "=" * 108)
    print("L3b 供给（运气） vs 获取（实力）—— 只统计正向增量，口径与剧本无关")
    print("=" * 108)
    opp = Counter()
    rea = Counter()
    n_story = n_fixed = 0
    for r in a["rows"]:
        if r["kind"] == "story":
            n_story += 1
        elif r["kind"] == "fixed":
            n_fixed += 1
        for off in r["offered"]:
            for kk, v in off.items():
                k = KEYMAP.get(kk)
                if k in KEYS:
                    opp[k] += max(0.0, float(v))
        for kk, v in r["delta"].items():
            k = KEYMAP.get(kk)
            if k in KEYS:
                rea[k] += max(0.0, float(v))
    print(f"回合构成：剧情事件 {n_story} / 固定行动 {n_fixed} / 合计 {len(a['rows'])}")
    print(f"\n{'属性':<8} {'供给上限(运气)':>12} {'实际获取(实力)':>13} {'获取率':>8} {'终值':>7} {'距门槛':>8}")
    rate = {}
    for k in KEYS:
        o, x = opp[k], rea[k]
        rate[k] = x / o if o else float("nan")
        end = a["rec"].get(k, 0.0)
        print(f"{k:<8} {o:>12.0f} {x:>13.0f} {rate[k]*100:>7.1f}% {end:>7.0f}")
    # cumulative-opportunity view: how much of the total positive supply was taken
    tot_o = sum(opp.values())
    tot_x = sum(rea.values())
    print(f"\n合计：供给 {tot_o:.0f} / 获取 {tot_x:.0f} → 综合获取率 {tot_x/tot_o*100:.1f}%")
    return {"opp": opp, "rea": rea, "rate": rate, "tot_o": tot_o, "tot_x": tot_x}


def counterfactual(a):
    """同一手牌下，若改成「贪心技能」策略，skill 何时越过 130？"""
    print("\n" + "=" * 108)
    print("L3c 反事实：同一副牌（同样的供给），换策略会怎样")
    print("=" * 108)
    # Actual skill crossing month
    def crossing(vals, thr):
        for m, v in vals:
            if v >= thr:
                return m
        return None
    actual = [(mo["month"], mo["snap_end"]["skill"]) for mo in a["months"]]
    print("实际 skill 轨迹：", " ".join(f"M{m}:{v:.0f}" for m, v in actual if m % 6 == 0 or m in (43, 47, 48)))
    print(f"实际越过 130 的月份：M{crossing(actual, 130)}"
          f"（对应可用窗口 M47；上一层窗口 M41 时为 "
          f"{[v for m, v in actual if m == 41][0]:.0f}）")

    # Greedy-skill replay: at every turn pick the offered option with max dSkill,
    # tie-break by max value under ending-score marginal weights.  Fixed actions
    # (energy / main) are held at the actual choice to isolate the story decisions.
    sk = 1.0
    lvl = "L1"
    traj = []
    for r in a["rows"]:
        if r["offered"] and r["kind"] == "story":
            best = max(r["offered"], key=lambda d: (d.get("Skill", 0), d.get("Output", 0)))
            d = best
        else:
            d = r["delta"]
        sk += float(d.get("Skill", 0))
        cap = clamps_at(r["level"])["skill"]
        sk = min(sk, float(cap))
        sk = max(0.0, sk)
        traj.append((r["month"], sk))
    greedy = []
    seen = set()
    for m, v in traj:
        if m not in seen:
            seen.add(m)
        greedy.append((m, v))
    print(f"\n反事实「每回合取 skill 最大选项」：越过 130 的月份 = "
          f"M{crossing(greedy, 130)}  终值 skill = {greedy[-1][1]:.0f}")
    print("  说明：该策略只优化 skill，必然牺牲 network/output/dignity，"
          "故仅用于量化「技能爬升速度」这一项对晋升时点的贡献。")
    return {"actual_cross": crossing(actual, 130), "greedy_cross": crossing(greedy, 130)}


def reason_stats(a):
    """统计 agent 自述理由里出现「风险/埋雷/规避」的回合占比。"""
    txt = a["txt"]
    cur = None
    rows = []
    for line in txt.splitlines():
        m = re.match(r"^### 回合 (\d+) · (.+?)\s*$", line)
        if m:
            cur = {"n": int(m.group(1)), "t": m.group(2), "r": None}
            rows.append(cur)
            continue
        if cur is not None and line.startswith("**理由:**"):
            cur["r"] = line[len("**理由:**"):].strip()
    risk_kw = ["风险", "埋雷", "爆雷", "HiddenRisk", "合规", "诚信", "底线", "造假", "泄密", "抄袭"]
    n_risk = sum(1 for r in rows if r["r"] and any(k in r["r"] for k in risk_kw))
    print("\n" + "=" * 108)
    print("L3d 决策自述（agent 的显式策略痕迹）")
    print("=" * 108)
    print(f"有自述理由的回合：{sum(1 for r in rows if r['r'])} / {len(rows)}")
    print(f"理由中显式提到「风险/埋雷/合规/诚信/底线」类词汇的回合：{n_risk}"
          f"（{n_risk/len(rows)*100:.0f}%）")
    for r in rows[-4:]:
        print(f"  M? 回合{r['n']:>3} {r['t'][:20]:<22} → {r['r'][:80] if r['r'] else '(无)'}")
    return {"n_risk": n_risk, "n": len(rows)}


def main():
    a = analyze(RUN)
    print(f"# 144338Z 深度复盘\n")
    print(f"run={a['run']}  回合={len(a['rows'])}  月份={len(a['months'])}  "
          f"未匹配={a['unmatched']}  重复键命中={a['dup']}\n")
    print("终局重建：", {k: round(v, 1) for k, v in a["rec"].items()})
    print("官方锚定：raw_skill=143 / raw_network=57 / raw_wealth=38.5 / "
          "raw_resilience=19 / raw_risk_control=4.0 / raw_level=6.0")
    gate_audit(a)
    rl = risk_ledger(a)
    op = opportunity(a)
    cf = counterfactual(a)
    rs = reason_stats(a)
    return a, rl, op, cf, rs


if __name__ == "__main__":
    main()
