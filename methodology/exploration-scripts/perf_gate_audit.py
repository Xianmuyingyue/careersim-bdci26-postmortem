"""Audit every promotion review: which of the 4 hard gates + the perf gate failed.

WHY a rewrite
-------------
`postmortem_run.py` reconstructs stats from option deltas, but it applies
`CareerState.clamp_stats()` after every turn, so a stat that is negative-capped
at the L1 ceiling (N3/O3) can silently absorb a later -1 and report the ceiling
instead of the truth.  Observed on 20260925T042320Z: reconstruction said
`M6 N3 O3`, the agent's own panel said `N2 O2`, and N<3 / O<3 is exactly why the
review failed.  So this script uses the replay's `**状态:**` lines as GROUND TRUTH.

Decision-boundary convention (verified)
---------------------------------------
`**状态:**` is the state *at the moment of decision, before the chosen option is
applied*.  Therefore the state the engine evaluates at a review sitting on the
replay-k / replay-k+1 boundary is the FIRST state line of replay month k+1
(any promotion announced in month k has already been folded in).

Engine-side semantics
---------------------
promotion/config.data  : on_month_modulo = 6, min_duration_in_level = 6
                         -> reviews at engine months 6/12/18/24/30/36/42/48
                         -> announced in replay months 5/11/17/23/29/35/41/47
performance_score      : COMPUTED (failure_conditions.py:155); must be built by
                         hand because the replay never prints it.
    stat_term = (capped + excess*0.3)/15 ; low=min(skill,network), high=max(..)
                capped=min(high, low*2.0) ; excess=max(0, high-low*2.0)
    out_term  = output/10
    lvl_term  = deg-9 poly -> L1 +2, L2 +3, L3 +2, L4 0, L5 -4, L6 -8, L7 -12
    mercy     : month<=12 and score<4  ->  score = 4   (M5/M11 only)
optional_conditions are MANDATORY whenever non-empty (promotion_conditions.py:170).

Usage:  python3 analysis/perf_gate_audit.py [run ...] [--all]
"""
from __future__ import annotations

import os
import re
import sys

ROOT = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUTROOT = os.path.join(ROOT, ".career_sim_runner", "career_emu", "outputs", "九问")

MON_RE = re.compile(r"^##\s*第\s*(\d+)\s*月")
ST_RE = re.compile(r"^\*\*状态:\*\*\s*(.+?)\s*$")
PROMO_RE = re.compile(r"已从\s*(L\d+)\s*晋升至\s*(L\d+)")
RAPID_RE = re.compile(r"升迁节奏过快")
HR_RE = re.compile(r"(笑着|偷偷|皱着眉头|神情复杂|生气)地?(?:跟你说|说)")
HR_CODE = {"笑着": 0, "偷偷": 1, "皱着眉头": 2, "神情复杂": 3, "生气": 4}

GATES = {  # level -> (skill, network, output, dignity, promo_network_cost, perf_gate)
    "L1": (8, 3, 3, 2, 0, 3),
    "L2": (18, 6, 5, 3, 0, 4),
    "L3": (35, 18, 14, 3, -2, 5),
    "L4": (90, 30, 22, 4, -2, 4),
    "L5": (130, 45, 32, 4, -3, 4),
    "L6": (170, 60, 45, 5, -4, 6),
    "L7": (210, 80, 60, 5, -4, 8),
}
POLY = [6.88932981e-05, -0.0037202381, 0.0856316138, -1.09791667, 8.59103009,
        -42.2239583, 129.157396, -235.174405, 228.665873, -86.0]
KEYS = ["skill", "network", "output", "dignity"]
REVIEW_REPLAY = [6, 12, 18, 24, 30, 36, 42, 48]


def level_term(lv: str) -> float:
    x = float(max(1, min(10, int(lv[1:]))))
    v = 0.0
    for c in POLY:
        v = v * x + c
    return v


def parse_state(text: str) -> dict:
    out = {}
    for kv in text.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        out[k] = v if k == "level" else float(v)
    return out


def parse_replay(run: str):
    d = os.path.join(OUTROOT, run)
    rp = [f for f in os.listdir(d) if f.startswith("replay-")][0]
    first, last, promo, rapid = {}, {}, {}, {}
    cur = None
    for line in open(os.path.join(d, rp), encoding="utf-8"):
        m = MON_RE.match(line)
        if m:
            cur = int(m.group(1))
            continue
        if cur is None:
            continue
        s = ST_RE.match(line)
        if s:
            st = parse_state(s.group(1))
            first.setdefault(cur, st)
            last[cur] = st
        p = PROMO_RE.search(line)
        if p:
            promo.setdefault(cur, (p.group(1), p.group(2)))
        if RAPID_RE.search(line):
            rapid[cur] = rapid.get(cur, 0) + 1
    return first, last, promo, rapid


def perf_of(s: dict, lv: str, month: int):
    sk, nt = s["skill"], s["network"]
    low, high = min(sk, nt), max(sk, nt)
    capped = min(high, low * 2.0)
    excess = max(0.0, high - low * 2.0)
    st = (capped + excess * 0.3) / 15.0
    ot = s["output"] / 10.0
    lt = level_term(lv)
    raw = st + ot + lt
    mercy = month <= 12 and round(raw) < 4
    return (4 if mercy else round(raw)), {"raw": raw, "st": st, "ot": ot, "lt": lt, "mercy": mercy}


def report(run: str, verbose: bool = False) -> dict:
    first, last, promo, rapid = parse_replay(run)
    fx = open(os.path.join(OUTROOT, run, "score_report.json"), encoding="utf-8").read()
    grade = re.search(r'"grade":\s*"(\w)"', fx).group(1)
    qs = re.search(r'"quantitative_score":\s*([\d.]+)', fx).group(1)
    surv = re.search(r'"survival_months":\s*(\d+)', fx).group(1)

    print(f"\n{'='*118}")
    print(f"run={run}   grade={grade}  score={qs}  存活={surv}月   "
          f"replay月数={max(first)}")
    print(f"{'='*118}")
    print(f"{'replay月':>7} {'引擎月':>6} {'职级':>4} {'S':>4} {'N':>4} {'O':>4} {'D':>4} "
          f"| {'ΔS':>4} {'ΔN':>4} {'ΔO':>4} {'ΔD':>4} | {'perf':>4} {'需':>3} | 结论")
    print("-" * 118)

    fails = {"gate": 0, "perf": 0, "skill": 0, "network": 0, "output": 0, "dignity": 0}
    for rk in REVIEW_REPLAY:
        if rk not in first:
            break
        s = dict(first[rk])
        lv_post = s["level"]
        pv = promo.get(rk - 1)
        if pv:
            # promotion was announced at replay rk-1; state already net of costs
            from_lv = pv[0]
            cost = GATES[from_lv][4]
            s["network"] -= cost  # undo, to audit the pre-review number
            lv = from_lv
            res = f"晋升 {pv[0]}->{pv[1]}"
            if rapid.get(rk - 1):
                res += "  [吃快晋升税]"
        else:
            lv = lv_post
            g = GATES[lv]
            miss = [f"{k}{s[k]-g[i]:+.0f}" for i, k in enumerate(KEYS) if s[k] - g[i] < 0]
            pf, _ = perf_of(s, lv, rk * 6)
            need = g[5]
            if miss:
                res = "缺 " + ",".join(miss)
                fails["gate"] += 1
                for k in KEYS:
                    i = KEYS.index(k)
                    if s[k] - g[i] < 0:
                        fails[k] += 1
            elif pf < need:
                res = f"★卡perf门 {pf} < {need}"
                fails["perf"] += 1
            else:
                res = "★不明（四门+perf 全过却未晋升）"
                fails["perf"] += 1
        g = GATES[lv]
        d = [s[k] - g[i] for i, k in enumerate(KEYS)]
        pf, meta = perf_of(s, lv, rk * 6)
        print(f"{rk:>7} {rk*6:>6} {lv:>4} {s['skill']:>4.0f} {s['network']:>4.0f} "
              f"{s['output']:>4.0f} {s['dignity']:>4.0f} | "
              f"{d[0]:>+4.0f} {d[1]:>+4.0f} {d[2]:>+4.0f} {d[3]:>+4.0f} | "
              f"{pf:>3}{'M' if meta['mercy'] else ' '} {g[5]:>3} | {res}")

    if verbose:
        print("\n  perf 分解（stat_term 含 skill/network 软帽；out_term=output/10；lt=职级多项式）")
        for rk in REVIEW_REPLAY:
            if rk not in first:
                break
            s = dict(first[rk])
            pv = promo.get(rk - 1)
            lv = pv[0] if pv else s["level"]
            if pv:
                s["network"] -= GATES[lv][4]
            pf, m = perf_of(s, lv, rk * 6)
            print(f"    replay M{rk:<3} {lv:<3} raw={m['raw']:>6.2f} = "
                  f"stat{m['st']:>5.2f} + out{m['ot']:>5.2f} + lvl{m['lt']:>+6.2f}"
                  f"{'   [mercy->4]' if m['mercy'] else ''}")
        print("  快晋升税分布: " + (", ".join(f"replay M{k}" for k in sorted(rapid)) or "无"))
    return {"run": run, "grade": grade, "score": float(qs), "fails": fails,
            "promos": sorted(promo.items()), "rapid": rapid}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv or not args:
        args = sorted(d for d in os.listdir(OUTROOT)
                      if os.path.isdir(os.path.join(OUTROOT, d))
                      and any(f.startswith("replay-") for f in os.listdir(os.path.join(OUTROOT, d))))
    agg = []
    for r in args:
        agg.append(report(r, verbose=True))
    print(f"\n{'#'*118}\n汇总\n{'#'*118}")
    print(f"{'run':>20} {'grade':>6} {'score':>7} {'缺门次数':>8} {'卡perf':>7} "
          f"{'S缺':>4} {'N缺':>4} {'O缺':>4} {'D缺':>4} {'晋升次数':>8} {'快晋升税':>8}")
    for a in agg:
        f = a["fails"]
        print(f"{a['run']:>20} {a['grade']:>6} {a['score']:>7.2f} {f['gate']:>8} {f['perf']:>7} "
              f"{f['skill']:>4} {f['network']:>4} {f['output']:>4} {f['dignity']:>4} "
              f"{len(a['promos']):>8} {sum(a['rapid'].values()):>8}")
    tot = {"skill": 0, "network": 0, "output": 0, "dignity": 0, "perf": 0}
    for a in agg:
        for k in tot:
            tot[k] += a["fails"][k]
    print(f"\n  全部 {len(agg)} 局合计缺门: {tot}")
