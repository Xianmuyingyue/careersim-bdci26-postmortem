"""Audit whether the submitter's own hard rules were actually FOLLOWED.

Rationale
---------
The R2 post-mortem showed that "writing a rule into the skill" and "executing it"
are different things. Judging policy quality therefore requires measuring
adherence, not just reading the skill text. This script computes, per run, how
often each of the five ironclad rules was respected.

The five rules (see solution/skills/decision-policy/SKILL.md):
    R1  keep network >= skill / 2
    R2  before each review month (M6,12,...,48) push every threshold to +2
    R3  once skill >= 120, never take a +Skill action
    R4  all 16 main actions default to "申请关键项目"
    R5  keep hidden_risk <= 1

Note on R1 vs promotion gates
-----------------------------
R1 (skill:network <= 2:1) is in tension with the promotion thresholds, whose
skill:network ratio is much steeper (L6 needs 130:45 ~= 2.9:1). A high R1
violation rate is therefore NOT automatically a defect — it may be a rational
trade of performance score for promotion speed. Read R1 together with the
final level before judging.

Usage:
    python3 analysis/audit_rules.py [run_dir ...]
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import (STAT_RE, THRESHOLDS, TURN_RE, load_replay,  # noqa: E402
                         _parse_status)

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
LOGDIR = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore")

KEY_MAIN = "申请关键项目"
LVL_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
REVIEW_MONTHS = (6, 12, 18, 24, 30, 36, 42, 48)
# The month banner is its own H2 heading placed BEFORE the turn heading:
#     ## 第 6 月 · 第 2 季度 · 第 1 年
#     ### 回合 21 · <title>
# TURN_RE's body stops at the next "\n## ", so the banner never lands inside a
# body. Month must therefore be resolved by character position, not by regex
# over the body.
MONTH_HDR_RE = re.compile(r"##+\s*第\s*(\d+)\s*月")


def state_series(run_dir: str) -> list[tuple[int, int | None, dict]]:
    """(turn, month, status) triples, mapping each turn to its month banner."""
    txt = load_replay(run_dir)
    if not txt:
        return []
    marks = [(m.start(), int(m.group(1))) for m in MONTH_HDR_RE.finditer(txt)]
    out = []
    for tm in TURN_RE.finditer(txt):
        pos = tm.start()
        month = None
        for mp, mn in marks:
            if mp <= pos:
                month = mn
            else:
                break
        sm = STAT_RE.search(tm.group(3))
        if sm:
            out.append((int(tm.group(1)), month, _parse_status(sm.group(1))))
    return out


def next_threshold(level: str):
    if level not in LVL_ORDER:
        return None
    idx = LVL_ORDER.index(level)
    if idx + 1 >= len(LVL_ORDER):
        return None
    nxt = LVL_ORDER[idx + 1]
    th = THRESHOLDS.get(nxt)
    return (nxt, th) if th else None


def _load_metric_json(run_dir: str) -> dict:
    p = os.path.join(LOGDIR, "metrics", f"{os.path.basename(run_dir)}.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def audit(run_dir: str) -> dict:
    series = state_series(run_dir)
    a: dict = {"run": os.path.basename(run_dir), "turns": len(series)}

    # --- R1: network >= skill / 2 -----------------------------------------
    viol = sum(1 for _i, _m, s in series
               if s.get("skill", 0) > 2 * max(1, s.get("network", 1)))
    a["R1_viol_rate"] = round(viol / len(series), 3) if series else None
    a["R1_max_ratio"] = round(max((s.get("skill", 0) / max(1, s.get("network", 1))
                                   for _i, _m, s in series), default=0), 2)

    # --- R2: promotion success at review months ---------------------------
    # NB: the level sampled AT a review month may already reflect a promotion
    # that occurred in that very month (promotions land exactly on review
    # months). Asking "does the state meet the NEXT threshold?" is therefore
    # the wrong question and always fails. The actionable questions are:
    #   (a) did a promotion actually happen at that review window?
    #   (b) how far from the next gate were we?
    gaps, n, seen = [], 0, set()
    for _i, mo, s in series:
        if mo is None or mo not in REVIEW_MONTHS or mo in seen:
            continue
        seen.add(mo)
        n += 1
        nt = next_threshold(s.get("level", ""))
        if nt:
            _nxt, (sk, ou, nw, dg) = nt
            v = (s.get("skill", 0), s.get("output", 0),
                 s.get("network", 0), s.get("dignity", 0))
            gaps.append(sum(max(0, t - x) for t, x in zip((sk, ou, nw, dg), v)))
    changes, prev = [], None
    for i, mo, s in series:
        lv = s.get("level")
        if lv != prev:
            if prev is not None:
                changes.append((i, mo, lv))
            prev = lv
    a["R2_review_n"] = n
    a["R2_promotions"] = sum(1 for _i, mo, _lv in changes if mo in REVIEW_MONTHS)
    a["R2_avg_gap"] = round(sum(gaps) / len(gaps), 1) if gaps else None
    a["R2_steps"] = len(changes)

    # --- R3: no +Skill action once skill >= 120 ---------------------------
    a["R3_skill_ge120_turns"] = sum(1 for _i, _m, s in series if s.get("skill", 0) >= 120)

    # --- R4: main actions default to the key project -----------------------
    ma = _load_metric_json(run_dir).get("main_actions", {}) or {}
    total_main = sum(ma.values())
    a["R4_main_total"] = total_main
    a["R4_key_projects"] = ma.get(KEY_MAIN, 0)
    a["R4_rate"] = round(ma.get(KEY_MAIN, 0) / total_main, 3) if total_main else None

    # --- R5: hidden_risk <= 1 (proxied by HR ladder readings) -------------
    ladder = _load_metric_json(run_dir).get("hr_ladder", {}) or {}
    safe = ladder.get("L0_safe", 0) + ladder.get("L1_mild", 0)
    bad = sum(v for k, v in ladder.items() if k in ("L2_accum", "L4_high", "L5_burst"))
    a["R5_safe_readings"] = safe
    a["R5_bad_readings"] = bad
    a["R5_bad_rate"] = round(bad / (safe + bad), 3) if (safe + bad) else None
    a["ladder"] = ladder
    return a


def main() -> int:
    dirs = sys.argv[1:] or sorted(
        d for d in glob.glob(os.path.join(OUTROOT, "*"))
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "score_report.json")))
    if not dirs:
        print("未找到已完成的对局。")
        return 0

    hdr = ("run", "turns", "R1违规率", "R1最大比", "R2晋升/评审月", "R2平均缺口",
           "R3≥120回合", "R4主行动率", "R5坏读数率")
    print("\t".join(hdr))
    for d in dirs:
        a = audit(d)
        print("\t".join(str(x) for x in (
            a["run"], a["turns"],
            f'{a["R1_viol_rate"]:.1%}' if a["R1_viol_rate"] is not None else "-",
            f'{a["R1_max_ratio"]:.2f}',
            f'{a["R2_promotions"]}/{a["R2_review_n"]}',
            a["R2_avg_gap"] if a["R2_avg_gap"] is not None else "-",
            a["R3_skill_ge120_turns"],
            f'{a["R4_rate"]:.1%}' if a["R4_rate"] is not None else "-",
            f'{a["R5_bad_rate"]:.1%}' if a["R5_bad_rate"] is not None else "-",
        )))
    return 0


if __name__ == "__main__":
    sys.exit(main())
