"""Deep postmortem of one CareerSim run with full causal reconstruction.

Usage:
    python3 analysis/postmortem_run.py [run_dir_name] [--dump] [--js]

Why this works
--------------
The agent never sees `status_updates` for story events, but we do: the decoded
official dataset (`官方资料/decoded_dev/action_pool/`) stores the exact delta of
every choice in every node.  The replay markdown records, per turn, the offered
options and the chosen one.  Matching (option-set -> node) recovers the true
delta vector of every decision the agent made -- including `HiddenRisk`, which
is invisible in the in-game state panel (the panel shows it, but the official
replay *status* line does not carry risk).

That turns "was it skill or luck?" from an opinion into arithmetic:

    Opportunity (luck)  = sum over turns of  max(dX)  among the *offered* options
    Realized   (skill)  = sum over turns of  dX      of the *chosen* option
    Capture rate        = Realized / Opportunity        <- script-independent
    Risk floor (luck)   = sum over turns of  min(dHiddenRisk) among offered
    Excess risk         = Realized risk - floor         <- skill deficit

`Opportunity` depends only on which events the engine drew (no seed -> luck).
`Capture rate` depends only on the choices (skill).  The two are separable.

Engine semantics encoded here (all verified against .venv source)
------------------------------------------------------------------
* `CareerState.clamp_stats()` (server/models.py:597)
    health, dignity in [0, hp_cap=10]
    skill, network, energy, hidden_risk >= 0
    output >= -1
    skill/network/output additionally capped at floor(next-level gate x 1.2)
* promotion schedule: `on_month_modulo = 6`, `min_duration_in_level = 6`
    L1->L2  skill 8  / network 3  / output 3  / dignity 2
    L2->L3  skill 18 / network 6  / output 5  / dignity 3
    L3->L4  skill 35 / network 18 / output 14 / dignity 3
    L4->L5  skill 90 / network 30 / output 22 / dignity 4   (-2 network on promo)
    L5->L6  skill 130/ network 45 / output 32 / dignity 4   (-3 network on promo)
    L6->L7  skill 170/ network 60 / output 45 / dignity 5   (-4 network on promo)
* `rapid_promotion`: >1 promotion inside 12 months -> network -3, dignity -1
* HR risk hint (game.py:436 + salary_conditions.RISK_LEVEL_MAP) is an *index*
    into a list keyed by hidden_risk:
        0 笑着跟你说   | 1 偷偷跟你说 | 2 皱着眉头跟你说
        3 神情复杂地说 | >=4 生气地说
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

STATS = ["skill", "network", "output", "dignity", "health"]
KEYMAP = {"Skill": "skill", "Network": "network", "Output": "output",
          "Dignity": "dignity", "Health": "health", "HiddenRisk": "hidden_risk",
          "Wealth": "wealth"}

# energy / main actions are visible in-game; hard-coded from the fixed events
ENERGY = {
    "高强度工作": (2, {"Output": 2, "Health": -1, "Dignity": -1, "HiddenRisk": 1}),
    "技能学习":   (2, {"Skill": 1, "Health": -1}),
    "人脉维护":   (1, {"Network": 1, "Dignity": 1}),
    "处理历史埋雷": (2, {"HiddenRisk": -1}),
    "心理修复":   (1, {"Dignity": 2}),
    "健康恢复":   (1, {"Health": 2}),
    "准备汇报材料": (1, {"Output": 1, "Dignity": 1}),
}
MAIN = {
    "申请关键项目": {"Output": 2, "Skill": 1, "Network": 1},
    "向领导汇报成果": {"Output": 1, "Network": 1, "Dignity": 1},
    "主动争取资源": {"Output": 1, "Network": 1},
    "申请岗位轮岗": {"Skill": 2, "Network": 1},
    "主动曝光成果": {"Output": 1, "Dignity": 1},
    "建立导师关系": {"Skill": 1, "Network": 2},
    "修复关键关系": {"Network": 1, "Dignity": 1},
    "低调避险":   {"Health": 1, "HiddenRisk": -1},
    "不行动": {},
    "选择不行动": {},
}

TURN_RE = re.compile(r"^### 回合 (\d+) · (.+?)\s*$")
OPT_RE = re.compile(r"^-\s*\[(\d+)\]\s*(.+?)\s*$")
CH_RE = re.compile(r"^\*\*选择:\*\*\s*(.+?)\s*$")
ST_RE = re.compile(r"^\*\*状态:\*\*\s*(.+?)\s*$")
MONTH_RE = re.compile(r"^##\s*第\s*(\d+)\s*月\s*·\s*第\s*(\d+)\s*季度\s*·\s*第\s*(\d+)\s*年\s*$")
BONUS_RE = re.compile(r"半年绩效奖金（([SABCD])）：([+-][\d.]+)")
PROMO_RE = re.compile(r"晋升通知：半年组织评审通过，您已从 (L\d+) 晋升至 (L\d+)")
HR_RE = re.compile(r"(笑着|偷偷|皱着眉头|神情复杂|生气)地?(?:跟你说|说)[，,：:]?\s*(.+?)\s*$")
# RISK_LEVEL_MAP is indexed BY hidden_risk -> the fuzzy word is the *bucket name*.
HR_CODE = {"笑着": 0, "偷偷": 1, "皱着眉头": 2, "神情复杂": 3, "生气": 4}

# next-level gates (skill, network, output, dignity, promo_network_cost)
GATES = {
    "L1": (8, 3, 3, 2, 0), "L2": (18, 6, 5, 3, 0), "L3": (35, 18, 14, 3, -2),
    "L4": (90, 30, 22, 4, -2), "L5": (130, 45, 32, 4, -3), "L6": (170, 60, 45, 5, -4),
    "L7": (210, 80, 60, 5, -4), "L8": (250, 100, 75, 6, -5), "L9": (290, 120, 90, 7, -5),
    "L10": (9999, 9999, 9999, 9, 0),
}
HARD_CAP = {"dignity": 10.0, "health": 10.0}
FLOOR = {"skill": 0.0, "network": 0.0, "hidden_risk": 0.0, "health": 0.0,
         "dignity": 0.0, "energy": 0.0, "output": -1.0}


def clamps_at(level: str) -> dict:
    sk, nt, ou = GATES.get(level, (9999, 9999, 9999))[:3]
    return {"skill": int(sk * 1.2), "network": int(nt * 1.2), "output": int(ou * 1.2)}


def apply_caps(rec: dict, level: str) -> None:
    """Mirror CareerState.clamp_stats()."""
    for k, cap in clamps_at(level).items():
        if k in rec and rec[k] > cap:
            rec[k] = float(cap)
    for k, cap in HARD_CAP.items():
        if k in rec and rec[k] > cap:
            rec[k] = float(cap)
    for k, lo in FLOOR.items():
        if k in rec and rec[k] < lo:
            rec[k] = lo


def parse_state(text: str) -> dict:
    out = {}
    for kv in text.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "level":
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def build_pool():
    """frozenset(actions) -> node record (only uniquely identifiable nodes)."""
    byset = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(POOL, "*", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        for node, body in (d.get("nodes") or {}).items():
            ch = body.get("choices") or []
            if not ch:
                continue
            byset[frozenset(c.get("action", "") for c in ch)].append({
                "eid": d.get("event_id"), "name": d.get("event_name"), "node": node,
                "choices": ch,
            })
    return ({k: v[0] for k, v in byset.items() if len(v) == 1},
            {k: len(v) for k, v in byset.items()})


def parse_replay(run_dir: str):
    reps = [f for f in os.listdir(run_dir) if f.startswith("replay-") and f.endswith(".md")]
    txt = open(os.path.join(run_dir, reps[0]), encoding="utf-8").read()
    months, cur_m, cur_t = [], None, None
    for line in txt.splitlines():
        m = MONTH_RE.match(line)
        if m:
            cur_m = {"month": int(m.group(1)), "quarter": int(m.group(2)),
                     "turns": [], "promo": None, "bonus": None, "hr": None}
            months.append(cur_m)
            cur_t = None
            continue
        if cur_m is None:
            continue
        t = TURN_RE.match(line)
        if t:
            cur_t = {"n": int(t.group(1)), "title": t.group(2), "opts": [],
                     "choice": None, "state": None}
            cur_m["turns"].append(cur_t)
            continue
        if cur_t is not None:
            o = OPT_RE.match(line)
            if o:
                cur_t["opts"].append(o.group(2))
                continue
            c = CH_RE.match(line)
            if c:
                cur_t["choice"] = c.group(1)
                continue
            s = ST_RE.match(line)
            if s:
                cur_t["state"] = parse_state(s.group(1))
                continue
        b = BONUS_RE.search(line)
        if b and cur_m["bonus"] is None:
            cur_m["bonus"] = (b.group(1), float(b.group(2)))
        p = PROMO_RE.search(line)
        if p:
            cur_m["promo"] = (p.group(1), p.group(2))
        h = HR_RE.search(line)
        if h and cur_m["hr"] is None:
            cur_m["hr"] = (HR_CODE.get(h.group(1)), h.group(2)[:60])
    return txt, months


def strip_idx(s: str) -> str:
    return re.sub(r"^\[\d+\]\s*", "", (s or "").strip()).split("—")[0].strip()


def opt_delta(action_text: str, node: dict | None) -> dict:
    """Delta of one *offered* option (story node or fixed action table)."""
    act = strip_idx(action_text)
    if node is not None:
        for c in node["choices"]:
            if c.get("action", "").strip() == act:
                return c.get("status_updates") or {}
    for table in (ENERGY, MAIN):
        if act in table:
            v = table[act]
            return dict(v[1]) if isinstance(v, tuple) else dict(v)
    return {}


def analyze(run: str):
    rd = os.path.join(OUTROOT, run)
    pool_fs, dup = build_pool()
    txt, months = parse_replay(rd)

    init = {"skill": 1.0, "network": 1.0, "output": 0.0, "dignity": 5.0,
            "health": 5.0, "hidden_risk": 0.0, "wealth": 1.0, "energy": 3.0}
    rec = dict(init)
    rows = []
    unmatched = 0
    dupmatched = 0
    lvl = "L1"

    for mo in months:
        mo["snap_start"] = dict(rec)
        for t in mo["turns"]:
            node, kind, d = None, "fixed", {}
            if t["opts"]:
                key = frozenset(t["opts"])
                node = pool_fs.get(key)
                if node is None:
                    if key in dup:
                        dupmatched += 1
                    kind = "fixed"
                else:
                    kind = "story"
            # delta of the CHOSEN option
            chosen = strip_idx(t["choice"]) if t["choice"] else ""
            if node is not None:
                hit = [c for c in node["choices"] if c.get("action", "").strip() == chosen]
                if hit:
                    d = hit[0].get("status_updates") or {}
                else:
                    unmatched += 1
            else:
                for table in (ENERGY, MAIN):
                    if chosen in table:
                        v = table[chosen]
                        d = dict(v[1]) if isinstance(v, tuple) else dict(v)
                        break
            # opportunity set (all offered options)
            offered = [opt_delta(o, node) for o in t["opts"]] if t["opts"] else []

            pre = dict(rec)
            for k, v in d.items():
                kk = KEYMAP.get(k)
                if kk:
                    rec[kk] = rec.get(kk, 0) + v
            apply_caps(rec, lvl)
            rows.append({"month": mo["month"], "n": t["n"], "title": t["title"],
                         "opts": t["opts"], "choice": t["choice"], "kind": kind,
                         "delta": d, "offered": offered, "pre": pre,
                         "post": dict(rec), "state": t["state"], "level": lvl})
            if t["state"] and t["state"].get("level"):
                lvl = t["state"]["level"]
        # promotion side effects at review months
        if mo["promo"]:
            to = mo["promo"][1]
            cost = GATES.get(mo["promo"][0], (0, 0, 0, 0, 0))[4]
            if cost:
                rec["network"] = max(0.0, rec.get("network", 0) - abs(cost))
            lvl = to
            apply_caps(rec, to)
        mo["snap_end"] = dict(rec)
    return {"run": run, "rows": rows, "months": months, "rec": rec,
            "unmatched": unmatched, "dup": dupmatched, "txt": txt}


def validate(rows) -> dict:
    errs = defaultdict(list)
    for r in rows:
        st = r["state"]
        if not st:
            continue
        for k in STATS:
            if k in st and isinstance(st[k], (int, float)):
                errs[k].append(st[k] - r["pre"].get(k, 0))
    return {k: {"n": len(v), "exact": sum(1 for x in v if abs(x) < 1e-9),
                "max_abs": max((abs(x) for x in v), default=0),
                "mean": sum(v) / len(v) if v else 0} for k, v in errs.items()}


def reconcile_risk(a: dict) -> None:
    """Month-by-month: reconstructed hidden_risk vs the HR hint bucket."""
    print("\n=== 风险对话逐月对账（HR 提示是 hidden_risk 的索引）===")
    print(f"{'月':>3} {'重建终值':>8} {'HR读数字面':>10} {'HR字面':>14} 一致?")
    ok = bad = 0
    for mo in a["months"]:
        end = mo["snap_end"]["hidden_risk"]
        hr = mo["hr"]
        if hr is None:
            continue
        code, word = hr
        # HR prints a *bucket*: code 4 means ">=4"
        hit = (end == code) or (code == 4 and end >= 4)
        ok += hit
        bad += (not hit)
        flag = "" if hit else "  <-- 不吻合"
        print(f"{mo['month']:>3} {end:>8.1f} {str(code):>10} {word[:12]:>14} {'Y' if hit else 'N'}{flag}")
    print(f"  吻合 {ok} / {ok + bad}")


def opportunity(a: dict) -> None:
    """Separate luck (what the engine offered) from skill (what was captured)."""
    print("\n=== 机会成本分解：运气（供给） vs 实力（获取）===")
    keys = ["skill", "network", "output", "dignity", "health", "hidden_risk"]
    opp = Counter()
    rea = Counter()
    for r in a["rows"]:
        for off in r["offered"]:
            for kk, v in off.items():
                k = KEYMAP.get(kk)
                if k in keys:
                    opp[k] += max(0.0, float(v))
        for kk, v in r["delta"].items():
            k = KEYMAP.get(kk)
            if k in keys:
                rea[k] += float(v)
    print(f"{'属性':<8} {'供给上限':>9} {'实际获取':>9} {'获取率':>8}   说明")
    for k in keys:
        o, x = opp[k], rea[k]
        rate = (x / o * 100) if o else float("nan")
        print(f"{k:<8} {o:>9.1f} {x:>9.1f} {rate:>7.1f}%")
    # risk floor
    floor = 0.0
    for r in a["rows"]:
        vals = [float(off.get("HiddenRisk", 0.0)) for off in r["offered"]]
        vals += [float(r["delta"].get("HiddenRisk", 0.0))] if not r["offered"] else []
        if vals:
            floor += min(vals)
    real = sum(float(r["delta"].get("HiddenRisk", 0.0)) for r in a["rows"])
    print(f"\nhidden_risk 实际注入 {real:+.0f} / 同回合「最低可选」下限合计 {floor:+.0f}"
          f" → 主动超额 {real - floor:+.0f}")


if __name__ == "__main__":
    run = "20260924T144338Z"
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            run = arg
    a = analyze(run)
    print(f"run={a['run']} 回合={len(a['rows'])} 未匹配={a['unmatched']} 重复键命中={a['dup']}")
    v = validate(a["rows"])
    print("\n=== 重建校验（观测状态 − 重建值）===")
    for k, s in v.items():
        print(f"  {k:<9} 样本 {s['n']:>4}  完全一致 {s['exact']:>4} "
              f"({s['exact']/s['n']*100:5.1f}%)  最大偏差 {s['max_abs']:>6.1f}  平均偏差 {s['mean']:>6.2f}")
    print("\n最终重建值:", {k: round(x, 1) for k, x in a["rec"].items()})
    reconcile_risk(a)
    opportunity(a)
    if "--dump" in sys.argv:
        print("\n=== 逐月终值 ===")
        for mo in a["months"]:
            e = mo["snap_end"]
            print(f"M{mo['month']:>2} lvl={e.get('level') if 'level' in e else ''} "
                  f"S{e['skill']:>5.0f} N{e['network']:>4.0f} O{e['output']:>4.0f} "
                  f"D{e['dignity']:>4.0f} H{e['health']:>4.0f} R{e['hidden_risk']:>4.0f} "
                  f"W{e['wealth']:>5.1f}")
