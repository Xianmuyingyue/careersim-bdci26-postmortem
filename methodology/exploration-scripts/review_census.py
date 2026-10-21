"""全批「晋升评审」普查 v3 —— 真值口径（replay 状态行），按职级分层。

演进
----
v1  用重建值 `snap_end`，且把不同职级的样本混在同一窗口 ⇒ 「M23 瓶颈=output」错。
v2  按 (窗口, 职级) 分层，但仍用重建值 ⇒ 被 clamp_stats 的**上限吸收效应**污染：
    L1 把 network 钉在 3、output 钉在 3，之后一个 -1 被上限"吃掉"，重建值仍报 3。
    实例：20260925T042320Z 的 M6 评审，重建 N3/O3（看似达标），真值 N2/O2（实际缺门）。
v3  改用 replay 的 `**状态:**` 行（Agent 亲自观测到的值）作为真值。
    评审坐在 replay-月 k 的边界上 ⇒ 评审状态 = replay 月 k 的**首条**状态行；
    若 k-1 月播报了晋升，则把晋升副作用（network 扣减）加回，得到评审当时的原值。

口径
----
promotion/config.data : on_month_modulo=6, min_duration_in_level=6
                      ⇒ 评审在 replay 月边界 6/12/18/24/30/36/42/48（= 引擎月同号）
performance_score     : 计算字段，须自算（failure_conditions.py:155）
                        optional_conditions 非空即强制（promotion_conditions.py:170）

用法：
    env -u PYTHONPATH .venv/bin/python analysis/review_census.py
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict

from perf_gate_audit import GATES, KEYS, OUTROOT, perf_of, parse_replay

BOUNDARIES = [6, 12, 18, 24, 30, 36, 42, 48]
LEVELS = ["L1", "L2", "L3", "L4", "L5"]


def collect():
    runs = sorted(d for d in os.listdir(OUTROOT)
                  if os.path.isdir(os.path.join(OUTROOT, d))
                  and any(f.startswith("replay-") for f in os.listdir(os.path.join(OUTROOT, d))))
    cell = defaultdict(Counter)      # (boundary, level) -> Counter(shortfall dim)
    promoted = defaultdict(int)      # (boundary, level) -> n
    perf_fail = defaultdict(int)     # (boundary, level) -> n
    perf_of_all = defaultdict(list)  # (boundary, level) -> [perf scores]
    used = 0
    detail = []
    for run in runs:
        first, last, promo, rapid = parse_replay(run)
        if not first:
            continue
        used += 1
        for rk in BOUNDARIES:
            if rk not in first:
                break
            s = dict(first[rk])
            pv = promo.get(rk - 1)
            if pv:
                lv = pv[0]
                s["network"] -= GATES[lv][4]      # undo promo cost
                promoted[(rk, lv)] += 1
                detail.append((run, rk, lv, "PROMO", None))
            else:
                lv = s["level"]
                g = GATES[lv]
                miss = [k for i, k in enumerate(KEYS) if s[k] - g[i] < 0]
                pf, _ = perf_of(s, lv, rk)
                if miss:
                    for k in miss:
                        cell[(rk, lv)][k] += 1
                    detail.append((run, rk, lv, "MISS", miss))
                elif pf < g[5]:
                    perf_fail[(rk, lv)] += 1
                    detail.append((run, rk, lv, "PERF", [f"perf{pf}<{g[5]}"]))
                else:
                    perf_fail[(rk, lv)] += 1
                    detail.append((run, rk, lv, "UNKNOWN", [f"perf{pf}"]))
            g = GATES.get(lv)
            if g:
                p, _ = perf_of(s, lv, rk)
                perf_of_all[(rk, lv)].append((p, g[5]))
    return used, cell, promoted, perf_fail, perf_of_all, detail


def main():
    used, cell, promoted, perf_fail, perf_all, detail = collect()
    print(f"有效局数 = {used}\n")

    print("=" * 108)
    print("★★ v3 真值口径：按 (评审边界, 评审时职级) 分层")
    print("=" * 108)
    print(f"{'边界':>5} {'职级':>5} {'门槛 S/N/O/D':>18} {'通过':>5} {'缺门':>5} {'卡perf':>7} | 短板分布")
    print("-" * 108)
    for rk in BOUNDARIES:
        for lv in LEVELS:
            if (rk, lv) not in cell and (rk, lv) not in promoted and (rk, lv) not in perf_fail:
                continue
            c = cell[(rk, lv)]
            p, pf = promoted[(rk, lv)], perf_fail[(rk, lv)]
            n = sum(c.values())
            g = GATES[lv][:4]
            dist = ", ".join(f"{k}×{c[k]}"
                             for k in sorted(KEYS, key=lambda x: -c.get(x, 0)) if c.get(k, 0))
            print(f"{rk:>5} {lv:>5} {str(g):>18} {p:>5} {n:>5} {pf:>7} | {dist or '—'}")

    print("\n" + "=" * 108)
    print("★ 按职级聚合（该职级所有未通过评审的短板构成）")
    print("=" * 108)
    agg = defaultdict(Counter)
    pro = Counter()
    for (rk, lv), c in cell.items():
        agg[lv].update(c)
    for (rk, lv), v in promoted.items():
        pro[lv] += v
    for lv in LEVELS:
        c = agg[lv]
        tot = sum(c.values())
        if tot == 0 and pro[lv] == 0:
            continue
        print(f"\n职级 {lv}（→ 门槛 {GATES[lv][:4]}，perf≥{GATES[lv][5]}）"
              f"  通过 {pro[lv]} 次 / 缺门 {tot} 次 / 卡perf {sum(v for (r,x),v in perf_fail.items() if x==lv)} 次")
        if tot:
            print("    " + ", ".join(f"{k}×{v} ({v/tot*100:.0f}%)" for k, v in c.most_common()))

    print("\n" + "=" * 108)
    print("★ 关键纪律核对")
    print("=" * 108)
    dg = sum(c.get("dignity", 0) for c in cell.values())
    tt = sum(sum(c.values()) for c in cell.values())
    print(f"  dignity 短板 {dg} 次 / 全部缺门 {tt} 次（{dg/tt*100:.1f}%）")
    for lv in ("L3", "L4", "L5"):
        c = agg[lv]
        tot = sum(c.values()) or 1
        print(f"  {lv} 段：skill 占 {c.get('skill',0)/tot*100:.0f}%  "
              f"output 占 {c.get('output',0)/tot*100:.0f}%  network 占 {c.get('network',0)/tot*100:.0f}%")
    print("\n  卡 perf 门的记录：")
    for (rk, lv), v in sorted(perf_fail.items()):
        if v:
            print(f"    边界 M{rk} {lv}: {v} 局")

    print("\n" + "=" * 108)
    print("★ 快晋升税收据（结构性成本）")
    print("=" * 108)
    tax = Counter()
    for run in sorted(d for d in os.listdir(OUTROOT) if os.path.isdir(os.path.join(OUTROOT, d))):
        try:
            _, _, _, rapid = parse_replay(run)
        except Exception:  # noqa: BLE001
            continue
        if rapid:
            tax[sum(rapid.values())] += 1
            print(f"  {run}: 吃税 {sum(rapid.values())} 次 → "
                  f"network -{3*sum(rapid.values())} / dignity -{sum(rapid.values())}")
    print(f"  分布：{dict(sorted(tax.items()))}")


if __name__ == "__main__":
    main()
