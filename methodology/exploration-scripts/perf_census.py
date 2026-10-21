"""绩效（奖金档位）普查：从 emulator_log 解析每局每个评审点的档位与当时职级。

数据源
------
`{arm}_runNN_play.log` 不保留引擎播报，但 `.career_sim_runner/career_emu/emulator_logs/<sid>.log`
完整保留了每个结算点的两行关键输出：
    [salary] 半年绩效奖金（X）：±N      # 每 6 个月一次，X = S/A/B/C/D 档
    [salary] 本月基本工资到账：+M（Lx）   # 紧随其后，给出当时职级与月薪

`run_dir` 与 `sid` 的映射：`outputs/九问/<run_dir>/transcript-*.log` 里的 `SESSION_ID=<32hex>`。

用法
----
    .venv/bin/python3 analysis/perf_census.py            # 全量普查
    .venv/bin/python3 analysis/perf_census.py --per-run   # 逐局明细
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
EMULOG = REPO / ".career_sim_runner" / "career_emu" / "emulator_logs"
METRICS = REPO / "analysis" / "ab" / "metrics"

SAL_RE = re.compile(r"\[salary\] 本月基本工资到账：\+([\d.]+)（(L\d)）")
BONUS_RE = re.compile(r"\[salary\] 半年绩效奖金（([SABCD])）：([+\-][\d.]+)")
PROMO_RE = re.compile(r"\[promotion\]")
SID_RE = re.compile(r"SESSION_ID=([0-9a-f]{32})")

# 月份序：奖金在同一结算点播报，第 n 个奖金 => M(6n)
REVIEW_MONTHS = [6, 12, 18, 24, 30, 36, 42, 48]

# 奖金档位系数（与结束分同源）
BONUS_MULT = {"S": 3.0, "A": 1.5, "B": 0.5, "C": -1.0, "D": -2.0}
# 由 perf 归纳的档位区间
TIER_RANGE = "S>=12 / A 8-11 / B 5-7 / C 3-4 / D<3"
# 职级多项式（perf 公式的 lvl_term）
POLY = {"L1": 2.0, "L2": 3.0, "L3": 2.0, "L4": 0.0, "L5": -4.0, "L6": -8.0, "L7": -12.0}
# 各职级的 (skill, output, network) 截断上限
CLAMP = {
    "L1": (9, 3, 3), "L2": (21, 6, 7), "L3": (42, 16, 21),
    "L4": (108, 26, 36), "L5": (156, 38, 54), "L6": (204, 54, 72),
}


def perf_from_state(level: str, skill: float, network: float, output: float, talk_adj: int = 0) -> int:
    """复算 perf（与引擎同式，见 situation-awareness 4.3）。"""
    low, high = min(skill, network), max(skill, network)
    capped = min(high, low * 2.0)
    excess = max(0.0, high - low * 2.0)
    stat_term = (capped + excess * 0.3) / 15.0
    return round(stat_term + output / 10.0 + POLY.get(level, 0.0)) + talk_adj


def map_runs():
    """run_dir 名 -> (emulator_log 路径, session_id, arm)"""
    out = {}
    for d in sorted(OUTROOT.iterdir()):
        if not d.is_dir():
            continue
        ts = list(d.glob("transcript-*.log"))
        if not ts:
            continue
        found = SID_RE.findall(ts[0].read_text(errors="ignore"))
        if not found:
            continue
        sid = found[-1]
        logp = EMULOG / f"{sid}.log"
        if not logp.exists():
            continue
        arm = "?"
        mj = METRICS / f"{d.name}.json"
        if mj.exists():
            try:
                arm = json.loads(mj.read_text()).get("arm") or "?"
            except Exception:
                pass
        out[d.name] = (logp, sid, arm)
    return out


def parse_log(logp: Path):
    """返回评审点列表 [(review_idx, level, tier, amount, month)] 与晋升序列。"""
    level = None
    reviews = []
    promos = []
    n = 0
    for line in logp.read_text(errors="ignore").splitlines():
        m = PROMO_RE.search(line)
        if m:
            pm = re.search(r"L(\d)", line)
            promos.append(pm.group(0) if pm else "?")
        mb = BONUS_RE.search(line)
        if mb:
            n += 1
            reviews.append({
                "idx": n,
                "month": REVIEW_MONTHS[n - 1] if n <= len(REVIEW_MONTHS) else 6 * n,
                "tier": mb.group(1),
                "amount": float(mb.group(2)),
                "level": level,          # 上一行工资给出的职级（若当月无工资行则为上一个月）
                "month_label": None,
            })
            continue
        ms = SAL_RE.search(line)
        if ms:
            level = ms.group(2)
            if reviews and reviews[-1]["level"] is None:
                reviews[-1]["level"] = level
    return reviews, promos


def main():
    per_run = "--per-run" in sys.argv
    mapping = map_runs()
    print(f"可用引擎日志覆盖的局数：{len(mapping)}")
    print(f"（全量 run_dir 数：{len([d for d in OUTROOT.iterdir() if d.is_dir()])}；"
          f"其余局的 emulator_log 已被引擎按 session 复用/清理）")
    print()

    by_month = defaultdict(list)              # month -> [(tier, level, run, arm)]
    by_arm = defaultdict(lambda: defaultdict(list))
    rows = []

    for run, (logp, sid, arm) in sorted(mapping.items()):
        reviews, promos = parse_log(logp)
        rows.append((run, arm, reviews, promos))
        for r in reviews:
            by_month[r["month"]].append((r["tier"], r["level"], run, arm))
            by_arm[arm][r["month"]].append((r["tier"], r["level"]))

    if per_run:
        print("=" * 96)
        print("逐局明细（评审点 -> 档位@职级）")
        print("=" * 96)
        for run, arm, reviews, promos in rows:
            seq = " ".join(f"M{r['month']}:{r['tier']}@{r['level'] or '?'}" for r in reviews)
            print(f"{run}  arm={arm:14s}  晋升 {len(promos)} 次\n    {seq}")
        print()

    print("=" * 96)
    print(f"按评审点汇总（档位分布）      奖金↔perf 映射：{TIER_RANGE}")
    print("=" * 96)
    print(f"{'评审点':<8}{'样本':<6}{'档位分布（S/A/B/C/D）':<34}{'C+D 占比':<10}{'职级分布'}")
    for m in REVIEW_MONTHS:
        obs = by_month.get(m)
        if not obs:
            continue
        c = Counter(t for t, _, _, _ in obs)
        tot = len(obs)
        cd = (c["C"] + c["D"]) / tot
        lv = Counter(l for _, l, _, _ in obs)
        lvs = " ".join(f"{k or '?'}:{v}" for k, v in sorted(lv.items(), key=lambda x: -x[1]))
        dist = " / ".join(f"{k}:{c[k]}" for k in "SABCD" if c[k])
        print(f"M{m:<7}{tot:<6}{dist:<34}{cd:>6.0%}    {lvs}")
    print()

    print("=" * 96)
    print("★ 关键交叉表：档位 × 当时职级（这是判断「自变量是职级还是三维」的核心证据）")
    print("=" * 96)
    cross = defaultdict(Counter)
    for m in REVIEW_MONTHS:
        for tier, level, _, _ in by_month.get(m, []):
            cross[(m, level)][tier] += 1
    print(f"{'评审点':<8}{'职级':<6}{'样本':<6}{'档位分布'}")
    for m in REVIEW_MONTHS:
        for level in ("L1", "L2", "L3", "L4", "L5", "L6"):
            c = cross.get((m, level))
            if not c:
                continue
            tot = sum(c.values())
            dist = " / ".join(f"{k}:{c[k]}" for k in "SABCD" if c[k])
            print(f"M{m:<7}{level:<6}{tot:<6}{dist}")
    print()

    print("=" * 96)
    print("按技能臂汇总")
    print("=" * 96)
    for arm in sorted(by_arm):
        print(f"\n-- arm {arm} --")
        for m in REVIEW_MONTHS:
            obs = by_arm[arm].get(m)
            if not obs:
                continue
            c = Counter(t for t, _ in obs)
            dist = " / ".join(f"{k}:{c[k]}" for k in "SABCD" if c[k])
            print(f"   M{m:<4} n={len(obs):<3} {dist}")

    print()
    print("=" * 96)
    print("★ 理论天花板 vs 实测（perf 公式外推，验证「M6 恒为 C 是机制锁死」）")
    print("=" * 96)
    for lv, (sc, oc, nc) in CLAMP.items():
        p_max = perf_from_state(lv, sc, nc, oc)
        p_min = perf_from_state(lv, 1, 1, 0)
        verdict = ("S" if p_max >= 12 else "A" if p_max >= 8 else "B" if p_max >= 5
                   else "C" if p_max >= 3 else "D")
        print(f"{lv}: 满配(S{sc}/N{nc}/O{oc}) -> perf {p_max} = {verdict} 档；"
              f"空配 -> perf {p_min}；poly={POLY[lv]:+.0f}")
    print()
    print("★ 长程上限（L6+) 用外推 CAP，检验 S 档是否可达：")
    for lv, th, cap in (("L5", (90, 22, 30), (156, 38, 54)),
                        ("L6", (130, 32, 45), (204, 54, 72)),
                        ("L7", (170, 45, 60), (252, 72, 96)),
                        ("L8", (210, 60, 80), (300, 90, 120))):
        sc, oc, nc = cap
        pol = POLY.get(lv, -4.0 * (int(lv[1]) - 4))
        low, high = min(sc, nc), max(sc, nc)
        capped = min(high, low * 2.0)
        excess = max(0.0, high - low * 2.0)
        stat = (capped + excess * 0.3) / 15.0
        p_max = round(stat + oc / 10.0 + pol)
        p_good = p_max + 2
        print(f"{lv}: 满配 stat={stat:.2f} out={oc/10:.1f} poly={pol:+.0f} "
              f"-> perf {p_max}（+谈话good = {p_good}）"
              f"{'  ← 可达 S' if p_good >= 12 else '  ← S 档不可达'}")
    print()

    print("=" * 96)
    print("★ 量化：档位 与 职级 的相关性（档位映射 S=5 A=4 B=3 C=2 D=1）")
    print("=" * 96)
    TV = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}

    def pearson(pairs):
        n = len(pairs)
        if n < 3:
            return float("nan"), 0
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
        sxx = sum((p[0] - mx) ** 2 for p in pairs)
        syy = sum((p[1] - my) ** 2 for p in pairs)
        if sxx == 0 or syy == 0:
            return float("nan"), n
        return sxy / (sxx ** 0.5 * syy ** 0.5), n

    allp = [(int(l[1]), TV[t]) for m in REVIEW_MONTHS for t, l, _, _ in by_month.get(m, []) if l]
    after = [(int(l[1]), TV[t]) for m in REVIEW_MONTHS if m >= 12
             for t, l, _, _ in by_month.get(m, []) if l]
    r_all, n_all = pearson(allp)
    r_aft, n_aft = pearson(after)
    print(f"全评审点 (n={n_all})：r(职级, 档位) = {r_all:.3f}")
    print(f"仅 M12 起 (n={n_aft})：r(职级, 档位) = {r_aft:.3f}")
    print()
    print("组内方差（同一职级内档位是否稳定）：")
    grp = defaultdict(list)
    for m in REVIEW_MONTHS:
        for t, l, _, _ in by_month.get(m, []):
            if l:
                grp[l].append(TV[t])
    for l in sorted(grp):
        v = grp[l]
        mean = sum(v) / len(v)
        sd = (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5
        print(f"   {l}: n={len(v):<3} 均值档位={mean:.2f}  组内 sd={sd:.2f}")
    print()
    print("★ 判读：若 r 高且组内 sd 低 ⇒ 「职级」是第一自变量；")
    print("  若某职级组内 sd 明显偏高 ⇒ 该档位存在「同职级内的可控变量」（通常是 output）。")


if __name__ == "__main__":
    main()
