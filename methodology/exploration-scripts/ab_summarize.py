"""Summarise an A/B session produced by `analysis/ab_driver.py`.

Usage:
    python3 analysis/ab_summarize.py                     # all arms found
    python3 analysis/ab_summarize.py arm_A arm_B         # subset, in order

Reads analysis/ab/results_<arm>.tsv and prints:
  - per-arm descriptive stats (mean / median / sd / min / max / early-death rate)
  - head-to-head table
  - the pre-registered acceptance criteria from
    solution/design/promotion_window_sprint.md §10.2

No statistics beyond descriptive + a Welch t-test approximation, because the
engine has no seed: two games share only ~52.8% of their plot, so per-arm n=4
cannot resolve small mean differences. Report effect size, not p-values.
"""

from __future__ import annotations

import math
import os
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
ABDIR = os.path.join(REPO, "analysis", "ab")

# v3 batch (pre-four-phase) baseline, from analysis/explore8_report.md
V3_BASELINE = {"label": "v3 (7 铁律, 前四相位)", "n": 4, "score": 65.30,
               "level": 5.00, "wealth": 31.25, "early_death": 0.00}


def read_arm(arm: str) -> list[dict]:
    path = os.path.join(ABDIR, f"results_{arm}.tsv")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        lines = [l.rstrip("\n") for l in fh if l.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        rows.append(dict(zip(header, cells)))
    return rows


def num(row: dict, key: str, default: float = float("nan")) -> float:
    try:
        return float(row.get(key, "nan"))
    except (TypeError, ValueError):
        return default


def describe(rows: list[dict], key: str) -> dict:
    vals = [num(r, key) for r in rows]
    vals = [v for v in vals if not math.isnan(v)]
    if not vals:
        return {"n": 0}
    n = len(vals)
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    sv = sorted(vals)
    med = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2
    return {"n": n, "mean": mean, "median": med, "sd": sd,
            "min": sv[0], "max": sv[-1]}


def level_num(s: str) -> float:
    s = (s or "").strip()
    return float(s[1:]) if s[:1] in "Ll" and s[1:].isdigit() else float("nan")


# ---------------------------------------------------------------------------
# 死因：直接读引擎印的结局名（见 ab_driver.ending_name 的注释）
# ★ 必须把「绩效死」与「爆雷死」分开计数：同一批技能会同时死于两种互不相干的机制，
#   只看均值会把它们混成一个数字，改技能时会对两个方向同时下药而无法归因。
# ---------------------------------------------------------------------------
# ★ 用**子串**匹配，不用精确键：引擎在不同路径下印的是「炒鱿鱼」/「炒鱿鱼end」/
#   「已完成」/`completed` 等多种形态。2026-09-26 实测：精确键曾把 `炒鱿鱼` 与 `已完成`
#   双双归成「其他」，使死因分布完全失真（v10 前两局被报成「绩效 0 · 通关 2」）。
DEATH_KIND = {
    "炒鱿鱼": "绩效",
    "信任危机": "爆雷",
    "眼前一黑": "健康",
    "喝西北风": "财富",
    "completed": "通关",
    "已完成": "通关",
}

ALL_KINDS = ("绩效", "爆雷", "健康", "财富", "其他", "未知", "通关")


def kind_of(e: str) -> str:
    if not e or e in ("?", "null"):
        return "未知"
    for k, v in DEATH_KIND.items():
        if k in e:
            return v
    return "其他"


def endings(rows: list[dict]) -> list[str]:
    try:
        import ab_driver  # 同目录
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ab_driver  # type: ignore
    out = []
    for r in rows:
        d = os.path.join(ab_driver.OUTROOT, r.get("run_dir", ""))
        out.append(ab_driver.ending_name(d))
    return out


def arm_report(arm: str) -> dict:
    rows = read_arm(arm)
    if not rows:
        return {"arm": arm, "n": 0}
    ends = endings(rows)
    return {
        "arm": arm,
        "n": len(rows),
        "score": describe(rows, "score"),
        "level": describe(rows, "raw_level"),
        "wealth": describe(rows, "raw_wealth"),
        "skill": describe(rows, "raw_skill"),
        "network": describe(rows, "raw_network"),
        "risk": describe(rows, "raw_risk_control"),
        "months": describe(rows, "months"),
        "bursts": describe(rows, "bursts"),
        "early_death": sum(1 for r in rows if num(r, "months") < 48) / len(rows),
        "grades": "".join(sorted(r.get("grade", "?") for r in rows)),
        "levels": ", ".join(f"L{num(r, 'raw_level'):.0f}"
                            if not math.isnan(num(r, "raw_level")) else "?"
                            for r in rows),
        "endings": ends,
        "death_kinds": {k: sum(1 for e in ends if kind_of(e) == k)
                        for k in ALL_KINDS},
        "rows": rows,
    }


def fmt(stats: dict, key: str, width: int = 6) -> str:
    if not stats.get("n"):
        return "-".rjust(width)
    if key == "mean":
        return f"{stats['mean']:.2f}".rjust(width)
    return f"{stats[key]:.0f}".rjust(width)


def main() -> int:
    arms = sys.argv[1:] or sorted(
        f[len("results_"):-len(".tsv")]
        for f in os.listdir(ABDIR)
        if f.startswith("results_") and f.endswith(".tsv")
    )
    reports = [arm_report(a) for a in arms]
    reports = [r for r in reports if r.get("n")]

    print("=" * 78)
    print("A/B 汇总 · CareerSim 职场生存赛")
    print("=" * 78)
    if not reports:
        print("尚无已完成的臂（analysis/ab/results_*.tsv 为空）。")
        return 1

    print(f"\n### 各臂明细（每局 n=1，无种子 ⇒ 只报告效应量，不报告 p 值）\n")
    hdr = f"{'臂':<24}{'n':>3}{'均值':>8}{'中位':>8}{'标准差':>8}{'最低':>8}{'最高':>8}{'早死':>7}{'职级':>7}{'财富':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in reports:
        print(f"{r['arm']:<24}{r['n']:>3}{fmt(r['score'],'mean',8)}{fmt(r['score'],'median',8)}"
              f"{fmt(r['score'],'sd',8)}{fmt(r['score'],'min',8)}{fmt(r['score'],'max',8)}"
              f"{r['early_death']*100:>6.0f}%{fmt(r['level'],'mean',7)}{fmt(r['wealth'],'mean',8)}")
    print(f"{V3_BASELINE['label']:<24}{V3_BASELINE['n']:>3}{V3_BASELINE['score']:>8.2f}"
          f"{'-':>8}{'-':>8}{'-':>8}{'-':>8}{V3_BASELINE['early_death']*100:>6.0f}%"
          f"{V3_BASELINE['level']:>7.2f}{V3_BASELINE['wealth']:>8.2f}")

    print("\n### 逐局成绩（分数 / 职级 / 存活月 / 结局名 → 死因）\n")
    for r in reports:
        print(f"- {r['arm']}（{r['grades']}）：")
        for x, e in zip(r["rows"], r["endings"]):
            lv = num(x, "raw_level")
            lv_s = f"L{lv:.0f}" if not math.isnan(lv) else "?"
            kind = kind_of(e)
            print(f"    {x.get('run_dir','?'):<20} {x.get('score','?'):>7}  {lv_s:>3}  "
                  f"{x.get('months','?'):>3}m  {e:<12} [{kind}]  bursts={x.get('bursts','?')}")
        k = r["death_kinds"]
        print(f"    → 死因分布：绩效 {k['绩效']} · 爆雷 {k['爆雷']} · 健康 {k['健康']} "
              f"· 财富 {k['财富']} · 其他 {k['其他']} · 未知 {k['未知']} · 通关 {k['通关']}")

    print("\n### 预登记验收标准（solution/design/promotion_window_sprint.md §10.2）\n")
    crit = [("均值分", 65.30, 70.00, "score"),
            ("平均职级", 5.00, 6.00, "level"),
            ("早死率", 0.00, 0.00, "early_death")]
    print(f"{'指标':<12}{'v3 基线':>10}{'目  标':>10}" + "".join(f"{r['arm'][:14]:>17}" for r in reports))
    for label, base, target, key in crit:
        line = f"{label:<12}{base:>10.2f}{target:>10.2f}"
        for r in reports:
            s = r[key]
            v = s if key == "early_death" else (s.get("mean", float('nan')) if isinstance(s, dict) else s)
            line += f"{v:>17.2f}"
        print(line)
    print("\n注：n=4 每臂只能分辨「早死/未早死」这类二元差异；")
    print("    均值差异的标准误 ≈ 18/√4 ≈ 9.0 分，故 <10 分的均差不可判定。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
