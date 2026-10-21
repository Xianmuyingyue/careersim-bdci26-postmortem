"""Extract comparable metrics from one CareerSim run directory.

Usage:
    python analysis/run_metrics.py <run_dir> [--label NAME]

Prints a one-line TSV summary plus a multi-line detail block.
Kept dependency-free so it can run under the managed python3.
"""

from __future__ import annotations

import json
import os
import re
import sys

# --- HR risk ladder: face/keyword -> hidden_risk reading -------------------
# Ground truth: salary_conditions.RISK_LEVEL_MAP is a list INDEXED BY hidden_risk:
#   [("笑着跟你说", ...),        # hidden_risk == 0
#    ("偷偷跟你说", ...),        # == 1
#    ("皱着眉头跟你说", ...),     # == 2
#    ("神情复杂地说", ...)]       # == 3
#   + [("生气地说", ...)] * 100  # >= 4  (burst threshold is 5)
# => 神情复杂 is 3, NOT 4; 生气 means ">= 4 imminent", NOT "already burst".
HR_LADDER = [
    ("笑着", "L0_safe"),
    ("偷偷", "L1_mild"),
    ("皱着眉头", "L2_accum"),
    ("神情复杂", "L3_critical"),
    ("生气", "L4plus_imminent"),
]
HR_RE = re.compile(r"(笑着|偷偷|皱着眉头|神情复杂|生气)地?(?:跟你说|说)[，,：:]?\s*(.+?)(?:\n|$)")

# --- Promotion thresholds (skill, output, network, dignity) ---------------
THRESHOLDS = {
    "L2": (8, 3, 3, 2),
    "L3": (18, 5, 6, 3),
    "L4": (35, 14, 18, 3),
    "L5": (90, 22, 30, 4),
    "L6": (130, 32, 45, 4),
    "L7": (170, 45, 60, 5),
}

# 职级截断上限 = 下一级晋升门槛 × clamp_factor(1.2)，向下取整。
# 列序 = (skill, output, network)。在职级 L 上，超过该上限的投入被引擎直接丢弃。
LEVEL_CLAMP = {
    "L1": (9, 3, 3),        # L2 (8,3,3)   x1.2
    "L2": (21, 6, 7),       # L3 (18,5,6)  x1.2
    "L3": (42, 16, 21),     # L4 (35,14,18) x1.2
    "L4": (108, 26, 36),    # L5 (90,22,30) x1.2
    "L5": (156, 38, 54),    # L6 (130,32,45) x1.2
    "L6": (204, 54, 72),    # L7 (170,45,60) x1.2
    "L7": (252, 72, 96),    # L8 (210,60,80) x1.2
}

STAT_RE = re.compile(r"\*\*状态:\*\* (.+)")
CHOICE_RE = re.compile(r"\*\*选择:\*\* (.+)")
TURN_RE = re.compile(r"### 回合 (\d+) · (.+?)\n(.*?)(?=\n### 回合 |\n## |\Z)", re.S)
BONUS_RE = re.compile(r"半年绩效奖金（([SABCD])）：([+-][\d.]+)")
TALK_RE = re.compile(r"【半年谈话】")


def _parse_status(text: str) -> dict:
    out = {}
    for kv in text.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        out[k] = v if k == "level" else (int(v) if re.fullmatch(r"-?\d+", v) else v)
    return out


def load_observe(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, f"events-{os.path.basename(run_dir)}.jsonl")
    if not os.path.exists(path):
        cands = [f for f in os.listdir(run_dir) if f.startswith("events-")]
        if not cands:
            return []
        path = os.path.join(run_dir, cands[0])
    obs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "tool_result":
                continue
            payload = rec.get("payload", {})
            if payload.get("tool_name") != "mcp_career-emulator_observe":
                continue
            try:
                obs.append(json.loads(payload["raw_output"]["result"]))
            except Exception:
                continue
    return obs


def load_replay(run_dir: str) -> str:
    cands = [f for f in os.listdir(run_dir) if f.startswith("replay-") and f.endswith(".md")]
    if not cands:
        return ""
    with open(os.path.join(run_dir, cands[0]), encoding="utf-8") as fh:
        return fh.read()


def metrics(run_dir: str) -> dict:
    m: dict = {"run_dir": os.path.basename(run_dir)}

    rep = os.path.join(run_dir, "score_report.json")
    if os.path.exists(rep):
        r = json.load(open(rep, encoding="utf-8"))
        es = r.get("ending_score", {})
        m["grade"] = es.get("grade")
        m["score"] = es.get("quantitative_score")
        m["months"] = es.get("survival_months")
        m["session"] = (r.get("session_id") or "")[:12]
        m["tokens"] = r.get("token_usage", {}).get("total_tokens")
        for dim in es.get("dimensions", []):
            m[f"raw_{dim['name']}"] = dim["raw_value"]
        m["termination"] = r.get("termination_reason")

    txt = load_replay(run_dir)
    if txt:
        turns = [(int(i), t.strip(), b) for i, t, b in TURN_RE.findall(txt)]
        rows = []
        for i, t, b in turns:
            sm = STAT_RE.search(b)
            if sm:
                rows.append((i, t, _parse_status(sm.group(1))))
        m["turns"] = len(turns)
        m["state_rows"] = len(rows)

        # level path: first turn observed at each level
        path, prev = [], None
        for i, t, s in rows:
            lv = s.get("level")
            if lv != prev:
                path.append((lv, i))
                prev = lv
        m["level_path"] = path
        m["final_level"] = rows[-1][2].get("level") if rows else None

        # threshold first-hit vs actual promotion turn
        gate = {}
        for lv, (sk, ou, nt, dg) in THRESHOLDS.items():
            hit = None
            for i, t, s in rows:
                if (s.get("skill", 0) >= sk and s.get("output", 0) >= ou
                        and s.get("network", 0) >= nt and s.get("dignity", 0) >= dg):
                    hit = i
                    break
            act = next((i for i, t, s in rows if s.get("level") == lv), None)
            gate[lv] = (hit, act)
        m["gate"] = gate

        # actions
        e_acts, m_acts, talk_tiers = {}, {}, {"good": 0, "average": 0, "bad": 0}
        talk_seq: list = []
        for i, t, b in turns:
            cm = CHOICE_RE.search(b)
            if "体力" in t and cm:
                a = re.sub(r"^\[\d+\]\s*", "", cm.group(1).strip()).split("—")[0].strip()
                e_acts[a] = e_acts.get(a, 0) + 1
            elif "主行动" in t and cm:
                a = re.sub(r"^\[\d+\]\s*", "", cm.group(1).strip()).split("—")[0].strip()
                m_acts[a] = m_acts.get(a, 0) + 1
        m["energy_actions"] = e_acts
        m["main_actions"] = m_acts
        m["bonus_seq"] = [g for g, _ in BONUS_RE.findall(txt)]

        # talk tier via narrative text fingerprints.
        #
        # 权威来源：官方 `decoded_dev/talk_mechanism/narratives.json` —— 每档恰好 3 条
        # 叙事模板，`selection: random_per_tier`，故文案是 tier 的确定性读数。
        # 引擎按 `first_match_descending`（good -> average -> bad）解档，这里同序判定。
        #
        # ⚠️ 修正记录（2026-09-25，R3 局 + 三方核对）：
        #   1. 旧词表把「你这半年不好不坏」「还在观察名单里」归入 bad —— **错**，
        #      二者出自 talk_avg_02「观望期」，是 **average** 档。
        #   2. 旧实现用 `txt.count(kw)` 全文累加，同一条叙事命中多个关键词就会被重复计数
        #      （曾把 8 次谈话算成 15 次）。**必须按回合去重、每回合只归一个档位。**
        good_kw = ("这半年你扛的事我都记着", "上面问部门骨干名单时，我第一个想到你",
                   "下个窗口我会重点推你", "该准备的材料提前整理好",
                   "你最近的表现符合预期", "半年后我们再看一档")
        avg_kw = ("照本宣科", "你这半年不好不坏", "还在观察名单里",
                  "没有要批你的意思", "只会忙、不会赢", "用同一套标准再看你")
        bad_kw = ("最后一次调整窗口", "我不得不重新评估",
                  "标记为「需跟进」", "半年内再没改善")
        for _i, _t, _b in turns:
            if "【半年谈话】" not in _b:
                continue
            tier = None
            if any(k in _b for k in good_kw):
                tier = "good"
            elif any(k in _b for k in avg_kw):
                tier = "average"
            elif any(k in _b for k in bad_kw):
                tier = "bad"
            if tier:
                talk_tiers[tier] += 1
                talk_seq.append((int(_i), tier))
        m["talk_tiers"] = talk_tiers
        m["talk_seq"] = talk_seq
        m["talk_n"] = sum(talk_tiers.values())

    # HR ladder + bursts from observe payloads
    obs = load_observe(run_dir)
    ladder, bursts, hr_seq = {}, 0, []
    for o in obs:
        ev = o.get("events") or ""
        for fm in HR_RE.finditer(ev):
            face = fm.group(1)
            grade = dict(HR_LADDER).get(face, face)
            ladder[grade] = ladder.get(grade, 0) + 1
            hr_seq.append(grade)
        if "打了水漂" in ev:
            bursts += 1
    m["hr_ladder"] = ladder
    m["hr_seq"] = hr_seq
    m["bursts"] = bursts
    m["observe_n"] = len(obs)

    # --- 职级截断占用率（识别「钳制空转」）--------------------------------
    #
    # 引擎让 skill/output/network 在职级 L 上的上限 = **下一级晋升门槛 × clamp_factor**。
    # 一旦某项顶到上限，**后续对它的所有投入被直接丢弃**。故「某维长期贴在
    # 上限」= 该维的可用空间为 0，继续投它是纯浪费；此时唯一有效的方向是
    # (a) 冲击晋升以抬高上限，或 (b) 把钱花在未被钳制的维度 / 生存变量上。
    #
    # 本局（R3）实测：L1 的 network 上限 3 == L1->L2 的 network 门槛 3 ⇒ **余量为 0**，
    # 任何月间折算都会把该值打到门槛之下，导致 M6 窗口因差 1 点而不放行。
    clamp_occ = {}
    capped_field_time = {}
    dur_series: list = []
    _prev_lv = None
    for o in obs:
        cs = o.get("current_state") or {}
        st = cs.get("status") or {}
        lv = st.get("level")
        c = LEVEL_CLAMP.get(lv)
        if lv != _prev_lv:
            dur_series.append((((cs.get("time") or {}).get("current_month")), lv))
            _prev_lv = lv
        if not c:
            continue
        bucket = clamp_occ.setdefault(lv, {"n": 0, "sum": [0.0, 0.0, 0.0], "capped_any": 0,
                                           "capped_all": 0, "capped_pairs": {}})
        bucket["n"] += 1
        vals = (st.get("skill") or 0, st.get("output") or 0, st.get("network") or 0)
        hits = []
        for idx, (v, cc) in enumerate(zip(vals, c)):
            bucket["sum"][idx] += (v / cc) if cc else 0.0
            if cc and v >= 0.95 * cc:
                hits.append(idx)
        if hits:
            bucket["capped_any"] += 1
            if len(hits) == 3:
                bucket["capped_all"] += 1
            elif len(hits) == 2:
                key = "/".join(("skill", "output", "network")[k] for k in hits)
                bucket["capped_pairs"][key] = bucket["capped_pairs"].get(key, 0) + 1
        for k in hits:
            name = ("skill", "output", "network")[k]
            capped_field_time[f"{lv}:{name}"] = capped_field_time.get(f"{lv}:{name}", 0) + 1

    occ_summary = {}
    for lv, b in clamp_occ.items():
        n = b["n"] or 1
        occ_summary[lv] = {
            "n": b["n"],
            "mean_use_ratio": {name: round(b["sum"][i] / n, 3)
                               for i, name in enumerate(("skill", "output", "network"))},
            "capped_any_ratio": round(b["capped_any"] / n, 3),
            "capped_all_ratio": round(b["capped_all"] / n, 3),
            "capped_pairs": b["capped_pairs"],
        }
    m["level_timeline"] = dur_series
    m["clamp_occupancy"] = occ_summary
    m["capped_field_months"] = capped_field_time
    return m


def tsv_row(m: dict) -> str:
    cols = [
        m.get("run_dir", ""),
        m.get("session", ""),
        str(m.get("grade", "")),
        str(m.get("score", "")),
        str(m.get("months", "")),
        str(m.get("final_level", "")),
        str(m.get("raw_level", "")),
        str(m.get("raw_wealth", "")),
        str(m.get("raw_skill", "")),
        str(m.get("raw_network", "")),
        str(m.get("raw_risk_control", "")),
        str(m.get("raw_resilience", "")),
        str(m.get("bursts", "")),
        str(m.get("tokens", "")),
        json.dumps(m.get("level_path", []), ensure_ascii=False),
        json.dumps(m.get("energy_actions", {}), ensure_ascii=False),
        json.dumps(m.get("main_actions", {}), ensure_ascii=False),
        json.dumps(m.get("talk_tiers", {}), ensure_ascii=False),
        json.dumps(m.get("hr_ladder", {}), ensure_ascii=False),
    ]
    return "\t".join(cols)


TSV_HEADER = "\t".join([
    "run_dir", "session", "grade", "score", "months", "final_level", "raw_level",
    "raw_wealth", "raw_skill", "raw_network", "raw_risk_control", "raw_resilience",
    "bursts", "tokens", "level_path", "energy_actions", "main_actions", "talk_tiers",
    "hr_ladder",
])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: run_metrics.py <run_dir> [--tsv]", file=sys.stderr)
        sys.exit(2)
    rd = sys.argv[1]
    mm = metrics(rd)
    if "--tsv" in sys.argv:
        print(tsv_row(mm))
    else:
        print(json.dumps(mm, ensure_ascii=False, indent=2))
