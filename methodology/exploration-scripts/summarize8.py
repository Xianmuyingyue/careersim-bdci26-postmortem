"""Aggregate the exploration results into a summary report.

Reads ../.workbuddy/logs/explore/results.tsv (one row per finished run) and
prints a Markdown summary, plus a dedicated audit of whether the HR feedback
decoder actually predicts bursts.

Usage:
    python3 analysis/summarize8.py
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
TSV = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore", "results.tsv")

NUMERIC = ("score", "months", "raw_level", "raw_wealth", "raw_skill", "raw_network",
           "raw_risk_control", "raw_resilience", "bursts", "tokens")
# HR ladder severity order, used to test monotonicity against bursts
HR_ORDER = ["L0_safe", "L1_mild", "L2_accum", "L4_high", "L5_burst"]

# Exploration batches, grouped by skill version (see memory/2026-09-25.md).
#   v1 = five ironclad rules
#   v2 = added rule 6 (health survival floor) after RUN3 died at month 6
#   v3 = added rule 7 (quarterly energy must be spent 3/3, via three consecutive
#        picks) after RESUME1 died at month 24 with 9/24 energy spent
BATCH = {
    "v1 (5 铁律)": ["20260924T161605Z", "20260924T165627Z",
                    "20260924T173408Z", "20260924T173802Z"],
    "v2 (6 铁律 +health)": ["20260924T190936Z", "20260924T192438Z",
                            "20260924T194245Z", "20260924T204559Z"],
    "v3 (7 铁律 +体力用尽)": ["20260924T232910Z", "20260924T235818Z",
                              "20260925T002312Z", "20260925T004806Z"],
}


def load() -> list[dict]:
    if not os.path.exists(TSV):
        return []
    with open(TSV, encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        for k in NUMERIC:
            try:
                row[k] = float(row[k]) if k in ("score",) else int(float(row[k]))
            except (ValueError, TypeError):
                row[k] = None
        rows.append(row)
    return rows


def top_counts(values: list[str], limit: int = 8) -> str:
    counts: dict[str, int] = {}
    for v in values:
        if not v:
            continue
        counts[v] = counts.get(v, 0) + 1
    items = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return "、".join(f"{k}×{n}" for k, n in items) if items else "-"


def hr_hist(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        try:
            ladder = json.loads(r.get("hr_ladder") or "{}")
        except (ValueError, TypeError):
            continue
        for k, v in (ladder or {}).items():
            try:
                counts[k] = counts.get(k, 0) + int(v)
            except (TypeError, ValueError):
                continue
    if not counts:
        return "（无记录）"
    return "、".join(f"{k}={counts[k]}" for k in HR_ORDER if k in counts)


def main() -> int:
    rows = load()
    if not rows:
        print("尚无完成的局（results.tsv 只有表头或不存在）。")
        print(f"结果文件: {TSV}")
        return 0

    scores = [r["score"] for r in rows if r["score"] is not None]
    out: list[str] = []
    add = out.append

    add("# 8 局探索 · 汇总报告\n")
    add(f"- 完成局数：**{len(rows)}**")
    if scores:
        add(f"- 分数：均值 **{st.mean(scores):.2f}** / 中位 {st.median(scores):.2f} / "
            f"最低 {min(scores):.2f} / 最高 {max(scores):.2f}"
            + (f" / 标准差 {st.pstdev(scores):.2f}" if len(scores) > 1 else ""))
    add(f"- 等级分布：{top_counts([r.get('grade','') for r in rows])}")
    levels = [("L" + str(r["raw_level"])) if r["raw_level"] is not None else "" for r in rows]
    add(f"- 终局职级：{top_counts(levels)}")
    add(f"- 爆雷总数：**{sum(r['bursts'] or 0 for r in rows)}**"
        f"（涉及 {sum(1 for r in rows if (r['bursts'] or 0) > 0)}/{len(rows)} 局）")
    add(f"- token 总量：{sum(r['tokens'] or 0 for r in rows):,}")

    add("\n## 均值画像\n")
    add("| 指标 | 均值 | 最低 | 最高 |")
    add("|---|---|---|---|")
    for key, label in (("months", "存活月数"), ("raw_level", "终局职级"),
                       ("raw_skill", "Skill"), ("raw_network", "Network"),
                       ("raw_wealth", "财富"), ("raw_risk_control", "风险控制"),
                       ("raw_resilience", "身心健康")):
        vals = [r[key] for r in rows if r[key] is not None]
        if vals:
            add(f"| {label} | {st.mean(vals):.2f} | {min(vals)} | {max(vals)} |")

    add("\n## 逐局明细\n")
    add("| # | grade | score | 月数 | 职级 | 财富 | skill | network | 风险 | 爆雷 |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        add(f"| {i} | {r.get('grade','')} | {r.get('score','')} | {r.get('months','')} "
            f"| L{r.get('raw_level','')} | {r.get('raw_wealth','')} | {r.get('raw_skill','')} "
            f"| {r.get('raw_network','')} | {r.get('raw_risk_control','')} | {r.get('bursts','')} |")

    add("\n## 本次探索分批对比（按技能版本）\n")
    by_dir = {r["run_dir"]: r for r in rows}
    add("| 组 | 局数 | 均值 | 早死(<48月) | 平均月数 | 平均职级 | 平均财富 | 平均爆雷 |")
    add("|---|---|---|---|---|---|---|---|")
    for gname, dirs in BATCH.items():
        grp = [by_dir[d] for d in dirs if d in by_dir]
        if not grp:
            continue
        gs = [r["score"] for r in grp if r["score"] is not None]
        dead = sum(1 for r in grp if (r["months"] or 0) < 48)
        add(f"| {gname} | {len(grp)} | {st.mean(gs):.2f} | {dead} | "
            f"{st.mean([r['months'] or 0 for r in grp]):.1f} | "
            f"{st.mean([r['raw_level'] or 0 for r in grp]):.2f} | "
            f"{st.mean([r['raw_wealth'] or 0 for r in grp]):.2f} | "
            f"{st.mean([r['bursts'] or 0 for r in grp]):.2f} |")

    add("\n## 反馈解码表有效性审计\n")
    add(f"- HR 风险档位出现频次：{hr_hist(rows)}")
    add("- 判据：`L5_burst`（生气）出现后应紧随爆雷；`L0_safe` 区间应无爆雷。")
    bad = [r.get("run_dir", "?") for r in rows
           if "L5_burst" in (r.get("hr_ladder") or "") and (r["bursts"] or 0) == 0]
    if bad:
        add(f"- ⚠️ 出现 `L5_burst` 但零爆雷的局：{', '.join(bad)}（解码表待复核）")
    else:
        add("- ✅ 未发现「L5_burst 却零爆雷」的反例。")

    add("\n## 行动配比审计\n")
    add(f"- 体力行动模式：{top_counts([r.get('energy_actions','') for r in rows], 3)}")
    add(f"- 主行动模式：{top_counts([r.get('main_actions','') for r in rows], 3)}")
    add(f"- 谈话档位序列：{top_counts([r.get('talk_tiers','') for r in rows], 3)}")

    report = "\n".join(out)
    print(report)

    dest = os.path.join(os.path.dirname(TSV), "summary8.md")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\n（已写入 {dest}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
