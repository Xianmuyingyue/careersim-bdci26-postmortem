"""绩效（奖金档位）全量普查：56 局 × 全部评审点，并做「档位 ↔ 评分 / 结局」相关性分析。

数据源（100% 覆盖，均为可观察的游戏内输出）
------------------------------------------
`.career_sim_runner/career_emu/outputs/九问/<run_dir>/events-*.jsonl`

每一行是 agent 与引擎的一次交互（tool_call / tool_result）。tool_result 里内嵌一段
被转义的引擎返回 JSON，展开后含：
    current_state.time.current_month / status.{level,skill,network,output,health,dignity,wealth}
    simulation_flags.{alive, failed, failure_reason}
    events  —— 引擎在本次结算点播报的文本，含
        「半年绩效奖金（X）：±N」   ← 档位（S/A/B/C/D）
        「本月基本工资到账：+M（Lx）」← 当时职级（可自校验：N = M × 档位系数）

旧口径（emulator_logs + transcript）只覆盖 20/57 局，本脚本改用 events jsonl ⇒ 56/56。

用法
----
    .venv/bin/python3 analysis/perf_census_all.py            # 汇总
    .venv/bin/python3 analysis/perf_census_all.py --per-run  # 逐局明细
    .venv/bin/python3 analysis/perf_census_all.py --json out.json
"""

from __future__ import annotations

import glob
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
AB = REPO / "analysis" / "ab"

REVIEW_MONTHS = [6, 12, 18, 24, 30, 36, 42, 48]
BONUS_MULT = {"S": 3.0, "A": 1.5, "B": 0.5, "C": -1.0, "D": -2.0}
TV = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}          # 档位数值化（用于相关/均值）
TIER_OF_PERF = lambda p: ("S" if p >= 12 else "A" if p >= 8 else "B" if p >= 5
                          else "C" if p >= 3 else "D")

POLY = {"L1": 2.0, "L2": 3.0, "L3": 2.0, "L4": 0.0,
        "L5": -4.0, "L6": -8.0, "L7": -12.0}
CLAMP = {"L1": (9, 3, 3), "L2": (21, 6, 7), "L3": (42, 16, 21),
         "L4": (108, 26, 36), "L5": (156, 38, 54), "L6": (204, 54, 72),
         "L7": (252, 72, 96)}

BONUS_RE = re.compile(r"半年绩效奖金（([SABCD])）：([+\-][\d.]+)")
SAL_RE = re.compile(r"本月基本工资到账：\+([\d.]+)（(L\d)）")

_DEC = json.JSONDecoder()


# ---------------------------------------------------------------- 解析
def iter_states(path: Path):
    """从一行 events jsonl 中抽出所有内嵌的引擎返回 JSON（含 current_state / events）。"""
    out = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "current_state" not in line:
            continue
        s = line.replace('\\"', '"')
        i = s.find('{"current_state":{')
        while i != -1:
            try:
                obj, _ = _DEC.raw_decode(s[i:])
            except Exception:
                obj = None
            if isinstance(obj, dict) and "current_state" in obj:
                key = (obj["current_state"].get("time", {}).get("current_month"),
                       obj.get("events", ""))
                if key not in seen:
                    seen.add(key)
                    out.append(obj)
            i = s.find('{"current_state":{', i + 1)
    return out


def perf_from_state(level: str, skill, network, output, talk_adj: int = 0) -> int:
    low, high = min(skill, network), max(skill, network)
    capped = min(high, low * 2.0)
    excess = max(0.0, high - low * 2.0)
    stat_term = (capped + excess * 0.3) / 15.0
    return round(stat_term + output / 10.0 + POLY.get(level, 0.0)) + talk_adj


def parse_run(path: Path):
    """返回该局的 dict： reviews / states / ending / months / session / level_timeline。"""
    objs = iter_states(path)
    reviews, states = [], []
    ending, months = "?", 0
    sid = None
    for o in objs:
        cs = o.get("current_state", {})
        st = cs.get("status", {})
        t = cs.get("time", {})
        mo = t.get("current_month")
        sid = sid or cs.get("session_id")
        if isinstance(mo, int):
            months = max(months, mo)
            states.append({"month": mo, **st})
        fl = cs.get("simulation_flags", {})
        fr = fl.get("failure_reason")
        if fr:
            ending = fr
        ev = o.get("events") or ""
        mb = BONUS_RE.search(ev)
        if mb is not None:
            ms = SAL_RE.search(ev)
            lv = ms.group(2) if ms else st.get("level")
            m_sal = float(ms.group(1)) if ms else None
            reviews.append({
                "month": mo, "tier": mb.group(1), "amount": float(mb.group(2)),
                "level": lv, "salary": m_sal,
                "skill": st.get("skill"), "network": st.get("network"),
                "output": st.get("output"), "health": st.get("health"),
                "dignity": st.get("dignity"), "wealth": st.get("wealth"),
            })
            if lv and m_sal:
                exp = BONUS_MULT[mb.group(1)] * m_sal
                reviews[-1]["check_ok"] = abs(exp - float(mb.group(2))) < 1e-3
    # 评审序：同一结算点可能被多次 observe（events 文本略有差异）⇒ 按「结算月+档位+金额+职级」去重。
    # ⚠️ 不可用「档位+金额+职级」去重：连续两个评审点档位可能完全相同（如 L1 上 M18/M24 都是 D/-0.6/@L1），
    #    那样会把真实存在的第二个评审点吃掉（2026-09-26 踩坑）。
    uniq, seen = [], set()
    for r in reviews:
        k = (r["month"], r["tier"], round(r["amount"], 4), r["level"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: (r["month"] or 999))
    for i, r in enumerate(uniq):
        r["idx"] = i + 1
        mo = r["month"]
        r["slot"] = mo if (isinstance(mo, int) and mo % 6 == 0) else (
            REVIEW_MONTHS[i] if i < len(REVIEW_MONTHS) else 6 * (i + 1))
    return {"reviews": uniq, "states": states, "ending": ending,
            "months": months, "session": sid}


# ---------------------------------------------------------------- 局索引
def build_index():
    """run_dir -> {..., arm, grade, score, months_tsv, level_final}"""
    idx = {}
    for p in sorted(OUTROOT.glob("*/events-*.jsonl")):
        run = p.parent.name
        d = parse_run(p)
        d["run_dir"] = run
        d["arm"] = "?"
        d["score"] = None
        d["grade"] = None
        d["level_final"] = None
        idx[run] = d
    # 从 results_*.tsv / night_run 回填 arm / 分数
    for tsv in sorted(AB.glob("results_*.tsv")):
        arm = tsv.stem.replace("results_", "")
        lines = tsv.read_text(errors="ignore").splitlines()
        if not lines:
            continue
        hdr = lines[0].split("\t")
        for ln in lines[1:]:
            f = ln.split("\t")
            if len(f) < len(hdr):
                continue
            row = dict(zip(hdr, f))
            run = row.get("run_dir")
            if run in idx:
                idx[run]["arm"] = arm
                idx[run]["score"] = _f(row.get("score"))
                idx[run]["grade"] = row.get("grade")
                idx[run]["level_final"] = _f(row.get("raw_level"))
    nj = AB / "night_run" / "runs.jsonl"
    if nj.exists():
        for ln in nj.read_text(errors="ignore").splitlines():
            try:
                r = json.loads(ln)
            except Exception:
                continue
            run = r.get("run_dir")
            if run in idx:
                idx[run]["arm"] = r.get("arm") or idx[run]["arm"]
                idx[run]["score"] = _f(r.get("score")) or idx[run]["score"]
                idx[run]["grade"] = r.get("grade") or idx[run]["grade"]
    mdir = AB / "metrics"
    if mdir.exists():
        for p in mdir.glob("*.json"):
            try:
                m = json.loads(p.read_text())
            except Exception:
                continue
            run = p.stem
            if run in idx:
                idx[run]["score"] = m.get("score") or idx[run]["score"]
                idx[run]["grade"] = m.get("grade") or idx[run]["grade"]
                idx[run]["level_final"] = m.get("raw_level") or idx[run]["level_final"]
                idx[run]["level_timeline"] = m.get("level_timeline")
    return idx


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def lvnorm(v):
    """把 'L5' / 5.0 / '5.0' 统一成 'L5'。"""
    if v is None:
        return None
    if isinstance(v, str) and v.startswith("L"):
        return v
    try:
        return f"L{int(float(v))}"
    except (TypeError, ValueError):
        return None


def ending_kind(s: str) -> str:
    if s.startswith("Completed"):
        return "通关(48月)"
    for k in ("炒鱿鱼", "信任危机", "眼前一黑", "喝西北风"):
        if k in s:
            return k + "end"
    if s in ("?", "null") or "null" in s:
        return "未完/中断"
    return s[:12]


def pearson(pairs):
    n = len(pairs)
    if n < 3:
        return float("nan")
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx == 0 or syy == 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def spearman(pairs):
    def rank(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    xs = rank([p[0] for p in pairs])
    ys = rank([p[1] for p in pairs])
    return pearson(list(zip(xs, ys)))


def sd(vals):
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


# ---------------------------------------------------------------- 报告
def main():
    per_run = "--per-run" in sys.argv
    idx = build_index()
    runs = [v for v in idx.values() if v["reviews"]]
    print("=" * 100)
    print(f"样本：{len(idx)} 个 run_dir，其中 {len(runs)} 局解析出评审播报"
          f"；状态快照覆盖 {sum(1 for v in idx.values() if v['states'])} 局")
    n_rev = sum(len(v["reviews"]) for v in runs)
    print(f"评审点总数：{n_rev}")
    bad = [(v["run_dir"], r) for v in runs for r in v["reviews"] if r.get("check_ok") is False]
    print(f"奖金自校验（金额 == 月薪 × 档位系数）失败：{len(bad)} 例")
    print("=" * 100)
    print()

    if per_run:
        for v in sorted(runs, key=lambda x: x["run_dir"]):
            seq = " ".join(f"M{r['slot']}:{r['tier']}@{r['level']}" for r in v["reviews"])
            print(f"{v['run_dir']}  {ending_kind(v['ending']):<16} "
                  f"月={v['months']:<3} 分={v['score']}  {seq}")
        print()

    # ---- 1 各评审点档位分布
    by_month = defaultdict(list)
    for v in runs:
        for r in v["reviews"]:
            by_month[r["slot"]].append(r)
    print("=" * 100)
    print("【1】各评审点的档位分布（56 局全量）    档位↔perf：S≥12 / A 8-11 / B 5-7 / C 3-4 / D<3")
    print("=" * 100)
    print(f"{'评审点':<8}{'样本':<6}{'S':<4}{'A':<4}{'B':<4}{'C':<4}{'D':<4}"
          f"{'C+D占比':<9}{'平均档位':<9}{'职级分布'}")
    for m in REVIEW_MONTHS:
        obs = by_month.get(m)
        if not obs:
            continue
        c = Counter(r["tier"] for r in obs)
        tv = [TV[r["tier"]] for r in obs]
        cd = (c["C"] + c["D"]) / len(obs)
        lv = Counter(r["level"] for r in obs)
        lvs = " ".join(f"{k}:{v}" for k, v in sorted(lv.items()))
        print(f"M{m:<7}{len(obs):<6}{c['S']:<4}{c['A']:<4}{c['B']:<4}{c['C']:<4}{c['D']:<4}"
              f"{cd:>7.0%}  {sum(tv)/len(tv):<9.2f}{lvs}")
    print()

    # ---- 2 档位 × 职级
    print("=" * 100)
    print("【2】★ 档位 × 当时职级  交叉表（判断自变量是「职级」还是「三维」的核心证据）")
    print("=" * 100)
    cross = defaultdict(Counter)
    for v in runs:
        for r in v["reviews"]:
            cross[r["level"]][r["tier"]] += 1
    print(f"{'职级':<6}{'样本':<6}{'S':<4}{'A':<4}{'B':<4}{'C':<4}{'D':<4}"
          f"{'平均档位':<9}{'组内sd':<8}档位天花板(实测)")
    for lv in ("L1", "L2", "L3", "L4", "L5", "L6", "L7"):
        c = cross.get(lv)
        if not c:
            continue
        tot = sum(c.values())
        vals = [TV[t] for t in c for _ in range(c[t])]
        top = max((t for t in "SABCD" if c[t]), key=lambda t: TV[t])
        print(f"{lv:<6}{tot:<6}{c['S']:<4}{c['A']:<4}{c['B']:<4}{c['C']:<4}{c['D']:<4}"
              f"{sum(vals)/tot:<9.2f}{sd(vals):<8.2f}{top}")
    print()

    # ---- 2b ★ 点级相关性与方差分解（「职级是不是第一自变量」的可核验证据）
    lvmean = defaultdict(list)
    for v in runs:
        for r in v["reviews"]:
            lvmean[r["level"]].append(TV[r["tier"]])
    lvmean = {k: sum(x) / len(x) for k, x in lvmean.items()}
    pts = [(int(r["level"][1:]), TV[r["tier"]], lvmean[r["level"]], r["slot"])
           for v in runs for r in v["reviews"]]
    m_pt = sum(p[1] for p in pts) / len(pts)
    ss_tot = sum((p[1] - m_pt) ** 2 for p in pts)
    ss_within = sum((p[1] - p[2]) ** 2 for p in pts)
    pts12 = [p for p in pts if p[3] >= 12]
    print("=" * 100)
    print("【2b】★ 点级相关性与方差分解（「职级是第一自变量吗」的可核验证据）")
    print("=" * 100)
    print(f"  点级 r(职级, 档位) = {pearson([(p[0], p[1]) for p in pts]):.3f}（n={len(pts)}）"
          f"；仅 M12 起 = {pearson([(p[0], p[1]) for p in pts12]):.3f}（n={len(pts12)}）")
    print(f"  ρ(职级, 档位)      = {spearman([(p[0], p[1]) for p in pts]):.3f}"
          f"（秩相关，抗档位档距非线性）")
    print(f"  方差分解：职级（组间）解释 {1 - ss_within / ss_tot:.1%}；"
          f"组内残余 {ss_within / ss_tot:.1%} ← 同职级内可控变量（output / 谈话）的空间")
    print(f"  ⚠️ 若把它按「局」聚合（局末职级 vs 局平均档位）r 会虚高到 ≈0.94"
          f"——聚合抹掉了局内噪声，两者不可混用")
    print()

    # ---- 3 理论天花板
    print("=" * 100)
    print("【3】理论天花板（满配 skill/network/output 时的 perf 上限，谈话 good=+2）")
    print("=" * 100)
    print(f"{'职级':<6}{'满配三维':<20}{'stat_term':<11}{'out_term':<10}{'职级项':<8}"
          f"{'perf上限':<10}{'+good':<7}档位天花板")
    for lv, (sc, oc, nc) in CLAMP.items():
        low, high = min(sc, nc), max(sc, nc)
        capped = min(high, low * 2.0)
        excess = max(0.0, high - low * 2.0)
        stat = (capped + excess * 0.3) / 15.0
        p = round(stat + oc / 10.0 + POLY[lv])
        print(f"{lv:<6}{f'S{sc}/O{oc}/N{nc}':<20}{stat:<11.2f}{oc/10:<10.1f}"
              f"{POLY[lv]:<+8.0f}{p:<10}{p+2:<7}{TIER_OF_PERF(p+2) if p+2>=12 else TIER_OF_PERF(p)}")
    print("  ⇒ S 档（perf≥12）在 L1–L7 全部不可达；A 档（perf≥8）从 L4 起才可能。")
    print()

    # ---- 4 perf 模型在全体样本上的校验
    print("=" * 100)
    print("【4】perf 公式在 56 局全量样本上的回验（隐含谈话修正 talk_adj = 档位 − 复算perf）")
    print("=" * 100)
    adj_ct = Counter()
    ok_match = 0
    tot = 0
    for v in runs:
        for r in v["reviews"]:
            if None in (r["skill"], r["network"], r["output"]) or not r["level"]:
                continue
            p = perf_from_state(r["level"], r["skill"], r["network"], r["output"])
            need = min(abs(p + a - lo) for a, lo in
                       [(a, {"S": 12, "A": 8, "B": 5, "C": 3, "D": -99}[r["tier"]]) for a in range(-2, 3)])
            # 反解：哪些 adj 能把复算 perf 落进实测档位
            fits = [a for a in range(-2, 3) if TIER_OF_PERF(p + a) == r["tier"]]
            tot += 1
            if fits:
                ok_match += 1
                adj_ct[tuple(fits)] += 1
            else:
                adj_ct[("无解",)] += 1
    print(f"复算 perf 落在实测档位内的比例：{ok_match}/{tot} = {ok_match/tot:.1%}")
    print("可行的 talk_adj 组合分布：")
    for k, v in adj_ct.most_common(10):
        print(f"   {k}: {v}")
    print()

    # ---- 5 逐局：平均档位 vs 评分 / 结局
    print("=" * 100)
    print("【5】★ 逐局平均档位 ↔ 最终评分 / 结局")
    print("=" * 100)
    rows = []
    for v in runs:
        tiers = [r["tier"] for r in v["reviews"]]
        tv = [TV[t] for t in tiers]
        rows.append({
            "run": v["run_dir"], "arm": v["arm"],
            "tiers": tiers,
            "mean_tier": sum(tv) / len(tv),
            "n_rev": len(v["reviews"]),
            "n_CD": sum(1 for t in tiers if t in "CD"),
            "months": v["months"],
            "score": v["score"], "grade": v["grade"],
            "ending": ending_kind(v["ending"]),
            "dead": 0 if v["ending"].startswith("Completed") else 1,
            "level_final": lvnorm(v["level_final"]) or lvnorm(max((r["level"] or "L1") for r in v["reviews"])) or "L1",
        })
    with_score = [r for r in rows if r["score"] is not None]
    print(f"有评分的局：{len(with_score)}/{len(rows)}")
    print(f"r(平均档位, 最终评分)      = {pearson([(r['mean_tier'], r['score']) for r in with_score]):.3f}"
          f"   (n={len(with_score)})")
    print(f"ρ(平均档位, 最终评分)      = {spearman([(r['mean_tier'], r['score']) for r in with_score]):.3f}")
    print(f"r(平均档位, 存活月数)      = {pearson([(r['mean_tier'], r['months']) for r in rows]):.3f}"
          f"   (n={len(rows)})")
    print(f"ρ(平均档位, 存活月数)      = {spearman([(r['mean_tier'], r['months']) for r in rows]):.3f}")
    print(f"r(C+D 次数, 存活月数)      = {pearson([(r['n_CD'], r['months']) for r in rows]):.3f}")
    print()

    print("按结局分组：")
    grp = defaultdict(list)
    for r in rows:
        grp[r["ending"]].append(r)
    print(f"{'结局':<18}{'局数':<6}{'平均档位':<10}{'平均存活月':<11}{'平均评分':<10}档位序列样例")
    for e, rs in sorted(grp.items(), key=lambda x: -len(x[1])):
        mt = sum(x["mean_tier"] for x in rs) / len(rs)
        mm = sum(x["months"] for x in rs) / len(rs)
        sc = [x["score"] for x in rs if x["score"] is not None]
        ex = rs[0]
        print(f"{e:<18}{len(rs):<6}{mt:<10.2f}{mm:<11.1f}"
              f"{(sum(sc)/len(sc) if sc else float('nan')):<10.1f}"
              f"{''.join(ex['tiers'])}")
    print()

    print("★ 早死 vs 通关：")
    dead = [r for r in rows if r["dead"]]
    alive = [r for r in rows if not r["dead"]]
    if dead and alive:
        print(f"  早死 n={len(dead)} 平均档位={sum(x['mean_tier'] for x in dead)/len(dead):.2f} "
              f"snapshot月={sum(x['months'] for x in dead)/len(dead):.1f}")
        print(f"  通关 n={len(alive)} 平均档位={sum(x['mean_tier'] for x in alive)/len(alive):.2f}")
    print()

    print("★ 「M12 是否 C/D」→ 后续结局：")
    for cond_name, cond in (
        ("M12 档位 ∈ {C,D}", lambda r: r["tier"] in "CD"),
        ("M12 档位 ∈ {B,A}", lambda r: r["tier"] in "BA"),
    ):
        sub = []
        for v in runs:
            r = next((x for x in v["reviews"] if x["slot"] == 12), None)
            if r and cond(r):
                sub.append(v)
        if sub:
            d = sum(1 for v in sub if not v["ending"].startswith("Completed"))
            print(f"   {cond_name}: n={len(sub):<3} 早死 {d}/{len(sub)} = {d/len(sub):.0%}"
                  f"   平均存活月={sum(v['months'] for v in sub)/len(sub):.1f}")
    print("★ 「M12 时是否仍停在 L1」→ 后续结局：")
    for name, want in (("仍 L1", "L1"), ("已 ≥L2", "L2")):
        sub = []
        for v in runs:
            r = next((x for x in v["reviews"] if x["slot"] == 12), None)
            if r and ((want == "L1" and r["level"] == "L1") or (want == "L2" and r["level"] != "L1")):
                sub.append(v)
        if sub:
            d = sum(1 for v in sub if not v["ending"].startswith("Completed"))
            print(f"   {name:<8} n={len(sub):<3} 早死 {d}/{len(sub)} = {d/len(sub):.0%}"
                  f"   平均存活月={sum(v['months'] for v in sub)/len(sub):.1f}")
    print()

    # ---- 6 分评审点：档位 → 生存率
    print("=" * 100)
    print("【6】★ 分评审点：该点档位 → 后续存活率（预测力检验）")
    print("=" * 100)
    for m in [12, 18, 24, 30, 36]:
        cells = defaultdict(lambda: [0, 0])
        for v in runs:
            r = next((x for x in v["reviews"] if x["slot"] == m), None)
            if r is None:
                continue
            k = r["tier"]
            cells[k][0] += 0
            cells[k][1] += 1
            if v["ending"].startswith("Completed"):
                cells[k][0] += 1
        if not cells:
            continue
        s = "  ".join(f"{k}: {v[0]}/{v[1]}={v[0]/v[1]:.0%}" for k, v in sorted(cells.items(), key=lambda x: -TV[x[0]]))
        print(f"M{m:<4} 该点存活率  {s}")
    print()

    # ---- 7 控制职级后的偏相关
    print("=" * 100)
    print("【7】控制职级后，「平均档位」是否仍有独立信息（组内去均值）")
    print("=" * 100)
    resid_pairs = []
    for r in with_score:
        lv = r["level_final"]
        if not lv:
            continue
        grp_mt = [x["mean_tier"] for x in with_score if x["level_final"] == lv]
        grp_sc = [x["score"] for x in with_score if x["level_final"] == lv]
        resid_pairs.append((r["mean_tier"] - sum(grp_mt) / len(grp_mt),
                            r["score"] - sum(grp_sc) / len(grp_sc)))
    print(f"以「局末职级」分组去均值后：r(平均档位残差, 评分残差) = {pearson(resid_pairs):.3f}"
          f"  (n={len(resid_pairs)})")
    lm_pairs = [(int(r["level_final"][1]), r["score"]) for r in with_score if r["level_final"]]
    print(f"对照：r(局末职级, 评分) = {pearson(lm_pairs):.3f}  (n={len(lm_pairs)})")
    lmt = [(int(r["level_final"][1]), r["mean_tier"]) for r in with_score if r["level_final"]]
    print(f"对照：r(局末职级, 平均档位) = {pearson(lmt):.3f}")
    print()

    # ---- 8 D 档 / A 档的职级归属
    print("=" * 100)
    print("【8】D 档与 A 档的职级归属（验证「D = 仍停在 L1 的指纹」）")
    print("=" * 100)
    for tier in "DCAB":
        obs = [(r["level"], v["run_dir"]) for v in runs for r in v["reviews"] if r["tier"] == tier]
        if not obs:
            print(f"{tier} 档：无样本")
            continue
        c = Counter(l for l, _ in obs)
        print(f"{tier} 档 n={len(obs):<4} 职级分布 " +
              " ".join(f"{k}:{v}" for k, v in sorted(c.items())))
    print()

    # ---- 9 晋级带来的绩效落差（同一局内 L4→L5 前后的档位）
    print("=" * 100)
    print("【9】★ 晋级的「绩效税」：同一局内跨级前后的档位对比（职级项 pol 随级变化）")
    print("=" * 100)
    trans = defaultdict(list)
    for v in runs:
        for a, b in zip(v["reviews"], v["reviews"][1:]):
            if a["level"] and b["level"] and a["level"] != b["level"]:
                trans[(a["level"], b["level"])].append((TV[a["tier"]], TV[b["tier"]], b["tier"]))
    print(f"{'跨级':<12}{'样本':<6}{'跨级前均档':<11}{'跨级后均档':<11}{'落差':<9}跨级后档位分布")
    for k, vs in sorted(trans.items()):
        pre = sum(x[0] for x in vs) / len(vs)
        post = sum(x[1] for x in vs) / len(vs)
        c = Counter(x[2] for x in vs)
        print(f"{k[0]+'→'+k[1]:<12}{len(vs):<6}{pre:<11.2f}{post:<11.2f}{post-pre:<+9.2f}"
              + " ".join(f"{t}:{c[t]}" for t in "SABCD" if c[t]))
    print("  （落差为负 ⇒ 晋级当口绩效档位下滑；这是「职级项」在 L5/L6 为负的直接后果）")
    print()

    # ---- 10 各结局的档位轨迹
    print("=" * 100)
    print("【10】各结局在 M6/M12/M18/M24/M30/M36 的档位分布（轨迹对照）")
    print("=" * 100)
    grp2 = defaultdict(lambda: defaultdict(Counter))
    for v in runs:
        k = ending_kind(v["ending"])
        for r in v["reviews"]:
            grp2[k][r["slot"]][r["tier"]] += 1
    print(f"{'结局':<16}" + "".join(f"{'M'+str(m):<16}" for m in (6, 12, 18, 24, 30, 36)))
    for k, ms in sorted(grp2.items(), key=lambda x: -sum(sum(c.values()) for c in x[1].values())):
        cells = []
        for m in (6, 12, 18, 24, 30, 36):
            c = ms.get(m)
            if not c:
                cells.append("-")
            else:
                tot = sum(c.values())
                cells.append("".join(f"{t}{c[t]}" for t in "SABDC" if c[t]) + f"({tot})")
        print(f"{k:<16}" + "".join(f"{x:<16}" for x in cells))
    print()

    # ---- 导出
    out = {"runs": rows,
           "by_month": {str(m): Counter(r["tier"] for r in by_month.get(m, [])).most_common()
                        for m in REVIEW_MONTHS},
           "cross": {lv: dict(c) for lv, c in cross.items()},
           "ceilings": {lv: {"cap": list(cap)} for lv, cap in CLAMP.items()},
           "reviews": [{"run": v["run_dir"], "slot": r["slot"], "month": r["month"],
                        "tier": r["tier"], "level": r["level"], "amount": r["amount"],
                        "skill": r["skill"], "network": r["network"], "output": r["output"],
                        "health": r["health"], "wealth": r["wealth"]}
                       for v in runs for r in v["reviews"]]}
    jp = "--json"
    if jp in sys.argv:
        p = Path(sys.argv[sys.argv.index(jp) + 1])
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"已写出 {p}")


if __name__ == "__main__":
    main()
