"""反事实门槛策略重放：在「同一批已出现的选项」上换策略，看 L6 能否更早拿到。

方法（有边界的近似，必须声明）
    固定引擎抽到的事件序列与每个节点提供的选项集（取自 replay），
    只替换「选择函数」，然后按引擎规则推进状态：
      · 属性截断  cap = floor(下一级门槛 × 1.2)（skill/network/output），dignity/health ≤10
      · 下界      skill/network/hidden_risk/health/dignity ≥ 0，output ≥ −1，hidden_risk ≥ 0
      · 评审窗口  M5/11/17/23/29/35/41/47（on_month_modulo=6），门槛取自 promotion/levels.json
      · 晋升副作用 L3→L4 net−2 / L4→L5 net−2 / L5→L6 net−3 / L6→L7 net−4
      · 爆雷      hidden_risk ≥5 → risk 归零、output 回滚 6 个月前快照、dignity−2、wealth−2
    局限：换策略会改变长链走向与后续事件抽取，因此本结果是「上界估计」，
    用于回答「这一手牌够不够」而不是「一定能拿到」。

三种策略
    actual   —— 实际对局的选择
    greedyS  —— 每回合把 skill 拉满（单目标上界）
    gateAware—— 四门缺口驱动 + 风险厌恶（综合最优的近似）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import (  # noqa: E402
    GATES, KEYMAP, OUTROOT, analyze, clamps_at,
)

REVIEW = [5, 11, 17, 23, 29, 35, 41, 47]
KEYS = ["skill", "network", "output", "dignity", "health"]


def gate_of(level):
    return GATES.get(level, (9999, 9999, 9999, 9))


def run_policy(a, policy):
    """Replay the recorded offer sequence under `policy`."""
    st = {"skill": 1.0, "network": 1.0, "output": 0.0, "dignity": 5.0,
          "health": 5.0, "hidden_risk": 0.0, "wealth": 1.0}
    lvl = "L1"
    hist = []            # (month, level, snapshot of st)
    out_hist = []        # output by month for the 6-month rollback
    promo_log = []
    bursts = 0
    cur_month = 0

    def close_month(m):
        """Promotion review runs when the month *advances*, i.e. at month end."""
        nonlocal lvl
        out_hist.append(st["output"])
        if m in REVIEW and lvl != "L10":
            g = gate_of(lvl)
            if (st["skill"] >= g[0] and st["network"] >= g[1]
                    and st["output"] >= g[2] and st["dignity"] >= g[3]):
                nxt = "L%d" % (int(lvl[1:]) + 1)
                st["network"] = max(0.0, st["network"] - abs(GATES[lvl][4]))
                lvl = nxt
                promo_log.append((m, lvl))

    for r in a["rows"]:
        m = r["month"]
        if m != cur_month:
            if cur_month:
                close_month(cur_month)
            cur_month = m
        # choose
        if r["offered"] and r["kind"] == "story":
            d = policy(r, st)
        else:
            d = r["delta"]
        for kk, v in d.items():
            k = KEYMAP.get(kk)
            if k:
                st[k] = st.get(k, 0.0) + v
        # clamps
        for k, cap in clamps_at(lvl).items():
            st[k] = min(st[k], float(cap))
        st["dignity"] = min(10.0, max(0.0, st["dignity"]))
        st["health"] = min(10.0, max(0.0, st["health"]))
        st["hidden_risk"] = max(0.0, st["hidden_risk"])
        st["skill"] = max(0.0, st["skill"])
        st["network"] = max(0.0, st["network"])
        st["output"] = max(-1.0, st["output"])
        if st["hidden_risk"] >= 5:
            bursts += 1
            st["hidden_risk"] = 0.0
            if len(out_hist) >= 6:
                st["output"] = out_hist[-6]
            st["dignity"] = max(0.0, st["dignity"] - 2)
            st["wealth"] -= 2
        hist.append((m, lvl, dict(st)))
    if cur_month:
        close_month(cur_month)
    return {"final": st, "level": lvl, "promos": promo_log, "bursts": bursts,
            "firstL6": next((m for m, l in promo_log if l == "L6"), None),
            "hist": hist}


def pol_actual(r, st):
    return r["delta"]


def pol_greedy_skill(r, st):
    return max(r["offered"], key=lambda d: (d.get("Skill", 0), d.get("Output", 0)))


def pol_gate_aware(r, st):
    """缺口驱动 + 风险厌恶，并用结局分权重做边际折算。"""
    g = gate_of(st.get("level", "L1"))
    need = {
        "skill": (130, 0.0020), "network": (45, 0.0018), "output": (32, 0.0020),
        "dignity": (4, 0.0075),
    }

    def val(d):
        v = 0.0
        for key, (thr, w) in need.items():
            cap_key = key.capitalize()
            cur = st.get(key, 0.0)
            # gate premium only while the gate is unmet
            premium = 3.0 if cur < thr else 0.0
            v += float(d.get(cap_key, 0)) * (w + premium)
        v += float(d.get("Skill", 0)) * 0.0012
        v += float(d.get("Network", 0)) * 0.0010
        v += float(d.get("Output", 0)) * 0.0008
        v += float(d.get("Health", 0)) * 0.0075
        # risk aversion: hard price for hidden risk
        risk = float(d.get("HiddenRisk", 0))
        v -= risk * (0.05 if st["hidden_risk"] + risk >= 4 else 0.01)
        return v
    return max(r["offered"], key=val)


def main():
    runs = sorted(d for d in os.listdir(OUTROOT)
                  if os.path.isdir(os.path.join(OUTROOT, d))
                  and any(f.startswith("replay-") for f in os.listdir(os.path.join(OUTROOT, d))))
    print("=" * 118)
    print("反事实门槛重放：同一批选项下，三种策略各自能到第几级 / 何时拿到 L6")
    print("=" * 118)
    print(f"{'run':<18}{'actual':>16}{'greedyS':>16}{'gateAware':>16}"
          f"   {'gA终局S/N/O':>18}  {'gA爆雷':>6}")
    stats = []
    for run in runs:
        a = analyze(run)
        res = {}
        for name, pol in (("actual", pol_actual), ("greedyS", pol_greedy_skill),
                          ("gateAware", pol_gate_aware)):
            res[name] = run_policy(a, pol)
        f = res["gateAware"]["final"]
        print(f"{run[:18]:<18}"
              f"{res['actual']['level']:>8}(B{res['actual']['bursts']})"
              f"{res['greedyS']['level']:>8}(B{res['greedyS']['bursts']})"
              f"{res['gateAware']['level']:>8}(B{res['gateAware']['bursts']})"
              f"   {f['skill']:>5.0f}/{f['network']:>4.0f}/{f['output']:>4.0f}"
              f"  {res['gateAware']['bursts']:>6d}")
        stats.append((run, res))
    print("\n--- 汇总：L6 达成率 ---")
    n = len(stats)
    for name in ("actual", "greedyS", "gateAware"):
        k = sum(1 for _, r in stats if r[name]["level"] in ("L6", "L7", "L8", "L9", "L10"))
        firsts = [r[name]["firstL6"] for _, r in stats if r[name]["firstL6"]]
        avg = sum(firsts) / len(firsts) if firsts else 0
        print(f"  {name:<10} 达到 L6+ {k:>2}/{n}  ({k/n*100:>3.0f}%)   "
              f"平均首次 L6 月份 {avg:>4.1f}")


if __name__ == "__main__":
    main()
