"""全批「瓶颈普查」v2 —— 按当前职级分层（修正 v1 的聚合缺陷）。

v1 的缺陷：M23 窗口上有的局在 L3（门槛 35/14/18）、有的在 L4（门槛 90/22/30），
两者混在同一格统计 ⇒ 得出「M23 瓶颈是 output」的误导性结论。
v2 按 (窗口, 当前职级) 分层：只有同一职级的样本才可比。

用法：
    env -u PYTHONPATH .venv/bin/python analysis/bottleneck_census.py [--levels]
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import GATES, OUTROOT, analyze  # noqa: E402

REVIEW_MONTHS = [5, 11, 17, 23, 29, 35, 41, 47]
KEYS = ["skill", "network", "output", "dignity"]


def level_at(a, month):
    mo = next((m for m in a["months"] if m["month"] == month), None)
    if mo is None:
        return None, None
    lv = None
    for t in mo["turns"]:
        if t["state"] and t["state"].get("level"):
            lv = t["state"]["level"]
    return mo, lv


def main():
    runs = sorted(d for d in os.listdir(OUTROOT)
                  if os.path.isdir(os.path.join(OUTROOT, d)))
    # (month, level) -> Counter of shortfall dims;  also promoted count
    cell = defaultdict(Counter)
    promoted = defaultdict(int)
    seen = 0
    for run in runs:
        try:
            a = analyze(run)
        except Exception:  # noqa: BLE001
            continue
        seen += 1
        for m in REVIEW_MONTHS:
            mo, lv = level_at(a, m)
            if mo is None or lv is None:
                continue
            g = GATES.get(lv)
            if g is None:
                continue
            s = mo["snap_end"]
            if mo["promo"]:
                promoted[(m, lv)] += 1
            else:
                for i, k in enumerate(KEYS):
                    if s[k] - g[i] < 0:
                        cell[(m, lv)][k] += 1

    print(f"有效局数 = {seen}\n")
    print("=" * 100)
    print("★★ 按 (窗口, 当前职级) 分层的短板分布  —— 只有同一职级的样本可比")
    print("=" * 100)
    print(f"{'窗口':>5} {'职级':>5} {'→':>4} {'通过':>5} {'未过':>5} | "
          f"{'skill':>7} {'network':>8} {'output':>7} {'dignity':>8} | 首位短板")
    for m in REVIEW_MONTHS:
        for lv in ("L1", "L2", "L3", "L4", "L5", "L6"):
            if (m, lv) not in cell and (m, lv) not in promoted:
                continue
            c = cell[(m, lv)]
            p = promoted[(m, lv)]
            n = sum(c.values())
            if p == 0 and n == 0:
                continue
            order = sorted(KEYS, key=lambda k: -c.get(k, 0))
            top = ", ".join(f"{k}×{c[k]}" for k in order if c.get(k, 0)) or "—"
            tgt = GATES.get(lv, ("",))[0] if False else ""
            print(f"M{m:<4} {lv:>5} {tgt:>4} {p:>5} {n:>5} | {c.get('skill',0):>7} "
                  f"{c.get('network',0):>8} {c.get('output',0):>7} {c.get('dignity',0):>8} | {top}")

    print("\n" + "=" * 100)
    print("★ 只保留 L4 与 L5 两个高段职级（这两段决定了 L6 能否达成）")
    print("=" * 100)
    agg = defaultdict(Counter)
    for (m, lv), c in cell.items():
        if lv in ("L4", "L5"):
            agg[lv].update(c)
    for lv in ("L4", "L5"):
        c = agg[lv]
        tot = sum(c.values())
        print(f"\n职级 {lv}（门槛 {GATES[lv][:4]}）未通过 {tot} 次：")
        print("   " + ", ".join(f"{k}×{v} ({v/tot*100:.0f}%)" for k, v in c.most_common()))

    print("\n" + "=" * 100)
    print("★ 全阶段 dignity 短板总数（验证「免费午餐」结论）")
    print("=" * 100)
    dig = sum(c.get("dignity", 0) for c in cell.values())
    tot = sum(sum(c.values()) for c in cell.values())
    print(f"  dignity 短板 {dig} 次 / 全部未通过记录 {tot} 次（{dig/tot*100:.1f}%）")


if __name__ == "__main__":
    main()
