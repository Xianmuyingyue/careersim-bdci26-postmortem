"""Scan every event choice for trades that spend Dignity, and quantify the rate.

Usage:
    python3 analysis/dignity_audit.py            # reprint the trade table
    python3 analysis/dignity_audit.py --runs     # also dump dignity trajectories

Reads the decoded official dataset (already msgpack/zlib-unwrapped) under
`官方资料/decoded_dev/action_pool/`.  Every event file holds a DAG of nodes;
each node has `choices[]`, each choice has `status_updates` (exact engine
deltas).  We therefore never need to *infer* an effect — we read it.

The point of the audit is to answer, with numbers rather than vibes:
"is it ever worth spending Dignity to buy Output / Network / Skill?"
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = "<PROJECT_ROOT>"
POOL = os.path.join(ROOT, "官方资料", "decoded_dev", "action_pool")
OUTROOT = os.path.join(ROOT, "CareerSim-BDCI26", ".career_sim_runner",
                       "career_emu", "outputs", "九问")
LOGDIR = os.path.join(ROOT, ".workbuddy", "logs", "explore")

# scorer weights reused from decision-policy (see solution/design/decision_report.md)
W = {"Output": 0.35, "Network": 0.30, "Skill": 0.25, "Dignity": 0.15, "Health": 0.05}
W_RISK = -0.60


def load_choices():
    """Yield every (event_id, event_name, node, action, deltas) in the pool."""
    out = []
    for f in sorted(glob.glob(os.path.join(POOL, "*", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        eid = d.get("event_id", os.path.basename(f))
        ename = d.get("event_name", "")
        for node, body in (d.get("nodes") or {}).items():
            for ch in (body.get("choices") or []):
                out.append({
                    "eid": eid, "ename": ename, "node": node,
                    "action": ch.get("action", ""),
                    "upd": ch.get("status_updates") or {},
                    "next": ch.get("next_node"),
                })
    return out


def main() -> int:
    ch = load_choices()
    print(f"事件池选项总数: {len(ch)}  "
          f"(事件数 {len({c['eid'] for c in ch})})\n")

    dn = [c for c in ch if (c["upd"].get("Dignity") or 0) < 0]
    dp = [c for c in ch if (c["upd"].get("Dignity") or 0) > 0]
    dz = [c for c in ch if (c["upd"].get("Dignity") or 0) == 0]
    print(f"含 Dignity 的选项: 负 {len(dn)} / 正 {len(dp)} / 零 {len(dz)}")
    print(f"负向合计 {sum(c['upd']['Dignity'] for c in dn)} 点，"
          f"正向合计 {sum(c['upd']['Dignity'] for c in dp)} 点")
    print(f"⇒ 供给/需求比 ≈ {sum(c['upd']['Dignity'] for c in dp) / -sum(c['upd']['Dignity'] for c in dn):.2f} : 1\n")

    # --- distribution of Dignity deltas inside negative-dignity choices ------
    print("=== A. 牺牲尊严的选项：它同时还动了什么？ ===")
    gain_keys = ["Output", "Network", "Skill", "Wealth", "Health", "HiddenRisk"]
    rows = []
    for c in dn:
        g = {k: c["upd"].get(k, 0) for k in gain_keys}
        d = c["upd"]["Dignity"]
        # net "value" by the in-game scorer, Dignity itself excluded
        val = sum(W[k] * g.get(k, 0) for k in ("Output", "Network", "Skill")) \
            + W["Health"] * g.get("Health", 0) + W_RISK * g.get("HiddenRisk", 0) \
            + (0.05 * g.get("Wealth", 0)) / 8
        dn_val = W["Dignity"] * d
        rows.append((c, d, g, val, dn_val, val + dn_val))
    rows.sort(key=lambda r: r[5])

    pure_loss = [r for r in rows if r[3] <= 0]
    print(f"其中『换不到任何正向收益』的选项（净收益 ≤ 0）: {len(pure_loss)} / {len(rows)}")
    print("最亏的 8 个（按净收益升序）：")
    for c, d, g, val, dn_val, tot in rows[:8]:
        gg = " ".join(f"{k}{v:+d}" for k, v in g.items() if v)
        print(f"  Dignity{d:+d} | {gg:<46} | 非尊严净 {val:+.3f} 合计 {tot:+.3f} | {c['action'][:26]}")
    print("\n最值的 6 个（说明牺牲尊严有时是划算的）：")
    for c, d, g, val, dn_val, tot in rows[-6:]:
        gg = " ".join(f"{k}{v:+d}" for k, v in g.items() if v)
        print(f"  Dignity{d:+d} | {gg:<46} | 非尊严净 {val:+.3f} 合计 {tot:+.3f} | {c['action'][:26]}")

    # --- aggregate "exchange rate" ------------------------------------------
    print("\n=== B. 汇率：每牺牲 1 点尊严换回什么（全部负向选项合计） ===")
    tot_d = -sum(c["upd"]["Dignity"] for c in dn)
    for k in gain_keys:
        s = sum(c["upd"].get(k, 0) for c in dn)
        print(f"  {k:<11} 合计 {s:+5d}   → 每点尊严 {s / tot_d:+.3f}")

    # --- who spends dignity most often --------------------------------------
    print("\n=== C. 高频『花尊严』事件 ===")
    cnt = Counter((c["eid"], c["ename"]) for c in dn)
    for (eid, ename), n in cnt.most_common(8):
        print(f"  {n} 次  {ename or eid}")

    # --- hard rule: is there a strictly-dominated action? -------------------
    print("\n=== D. 关键裁决：`高强度工作` 是否被严格支配？ ===")
    hw = {"Output": 2, "Health": -1, "Dignity": -1, "HiddenRisk": 1}   # 2 energy
    alt = {"Output": 2, "Dignity": 2}                                   # 准备汇报材料 ×2, 2 energy
    print(f"  高强度工作 (2 体力): {hw}")
    print(f"  准备汇报材料×2 (2 体力): {alt}")
    print("  ⇒ 同样 2 体力、同样 Output+2，但一个 Dignity−1/Health−1/HiddenRisk+1，"
          "另一个 Dignity+2。净差 = Dignity 3 点 + Health 1 点 + HiddenRisk 1 点。")
    print("  ⇒ 结论：体力行动层面『用尊严换 Output』不存在正汇率，该行动被严格支配。")

    # --- floor analysis -----------------------------------------------------
    print("\n=== E. 尊严的三段收益曲线（按引擎配置） ===")
    for lo, hi, note in [
        (0, 1, "连续 3 个月 ≤1 → dignity_crisis 失败条件：扣 2 HP + Health−2 + Network−1，"
               "且 talk_score 每月 −0.8"),
        (2, 3, "仅满足 L1→L2/L2→L3/L3→L4 的晋升硬门槛（2/3/3），无任何结局分溢价"),
        (4, 5, "满足 L4→L5/L5→L6/L6→L7 门槛（4/4/5）；结局分 0.75 分/点"),
        (6, 10, "超过全部实用门槛，只剩结局分 0.75 分/点 + talk_score 1.0/点（且 good 档已封顶）"),
    ]:
        print(f"  [{lo}–{hi}] {note}")

    if "--runs" in sys.argv:
        print("\n=== F. 实测尊严轨迹（全部对局） ===")
        print(f"{'run':<18}{'最低':>5}{'终值':>5}{'≤1月数':>7}{'均值':>7}  月度序列(每3月抽样)")
        mre = re.compile(r"^##\s*第\s*(\d+)\s*月")
        sre = re.compile(r"^\*\*状态:\*\*\s*(.+?)\s*$")
        for d in sorted(os.listdir(OUTROOT)):
            p = os.path.join(OUTROOT, d)
            if not os.path.isdir(p):
                continue
            reps = [f for f in os.listdir(p) if f.startswith("replay-")]
            if not reps:
                continue
            cur, series = None, []
            for line in open(os.path.join(p, reps[0]), encoding="utf-8"):
                if mre.match(line):
                    cur = int(mre.match(line).group(1))
                else:
                    m = sre.match(line)
                    if m and "dignity" in m.group(1) and cur:
                        v = int(re.search(r"dignity=(-?\d+)", m.group(1)).group(1))
                        series.append((cur, v))
            if not series:
                continue
            vals = [v for _, v in series]
            low = sum(1 for v in vals if v <= 1)
            samp = [str(v) for m, v in series if m % 12 == 0][:5]
            print(f"{d:<18}{min(vals):>5}{vals[-1]:>5}{low:>7}"
                  f"{sum(vals)/len(vals):>7.1f}  {' '.join(samp)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
