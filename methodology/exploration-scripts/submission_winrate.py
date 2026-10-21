#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
submission_winrate.py —— 在「跑三次取最高分」赛制下，各臂的保底能力。

为什么不能只看均值：赛制是 **提交一次 → 引擎跑 3 局 → 记最高分**，
所以真正关心的是
    P( max(3 局) ≥ T ) = 1 − (1 − p)^3       p = P(单次 ≥ T)
    E[ max(3 局) ]
而不是均值 / sd。

p 用**经验频率**估计（n 很小，不做参数假设）：p = 该臂中 ≥T 的局数 / 总局数。
E[max3] 用该臂经验分布做 3 次有放回抽样的精确期望（枚举 4^n 种组合，n≤6 可行）。
"""
from __future__ import annotations

import itertools

ARMS = {
    "v3_rerun":   [73.12, 75.04, 30.80, 75.88],
    "v8_3_rerun": [56.92, 59.42, 72.96, 50.28],
    "v10c":       [70.26, 32.06, 63.88, 70.51],
    "v10d":       [20.40, 70.75, 64.50, 38.24],
    "v10e":       [53.02, 31.56],
    "v3(原批)":   [67.30, 66.17, 60.49, 67.22],
    "v8_5":       [71.42, 31.81, 68.15, 63.42, 28.15, 68.35, 65.78],
    # ★ v3 合并样本（09-24 原批 4 局 + 09-27 复测 4 局，同一份技能的实现语义）
    "v3 合并n=8": [73.12, 75.04, 30.80, 75.88, 67.30, 66.17, 60.49, 67.22],
    # ★ 09-29 扩样本批次：与 v3_rerun **同一套技能（md5 逐字一致）**再跑 4 局
    #   28.88 = M13 喝西北风end（财富线，项目首例）／57.62 = M45 信任危机end（二次爆雷）
    "v3_rerun2":  [28.88, 59.12, 57.62, 71.53],
    # ★★ 提交臂的真实样本 = v3_rerun 8 局合并（09-27 四局 + 09-29 四局）
    "v3_rerun合并n=8": [73.12, 75.04, 30.80, 75.88, 28.88, 59.12, 57.62, 71.53],
    # ★★★ v13 破壁臂（09-29 落盘，SA 逐字未改 / RG 加第 9+10 条 / DP 加 §七 逆风局破壁协议）
    #    76.28 = 首局（attempt1 收尾 WS 崩、经 salvage_score.py 抢救）通关 48 月 L6 / 0 爆雷
    #    48.89 = 第 2 局 48 月 **信任危机end（第二次爆雷）** D 级 / L5
    #    ⇒ 2/2 跑满 48 月（零早死），但爆雷 1.5/2（第 2 局第二次爆雷）
    #    ⚠️ n=2：P(max3≥60) 与 v3_rerun合并n=8 同为 87.5%，E[max3] 略高 72.86 vs 72.07
    "v13(破壁)n=2": [76.28, 48.89],
    # ★★★ v14（09-29，v13 + 四项修正：全局爆雷状态机 / L1 倒计时配额 / 硬裁定爆雷分支 / 引用修正）
    #    64.38(B/L5/0爆雷) / 30.88(D/M8 喝西北风end·财富线) / 68.97(B/L6/1爆雷) / 66.09(B/L5/0爆雷)
    #    ⇒ 3/4 完赛 ≥64 但 **0 局上 71**（天花板塌陷）；1/4 早死（新形态：晋升 L2 后仍死于财富线）
    "v14 n=4": [64.38, 30.88, 68.97, 66.09],
}
THRESHOLDS = (50, 60, 70)


def p_single(scores, t):
    return sum(1 for s in scores if s >= t) / len(scores)


def p_max_at_least(scores, t, k=3):
    p = p_single(scores, t)
    return 1 - (1 - p) ** k


def expected_max(scores, k=3):
    tot = 0.0
    for combo in itertools.product(scores, repeat=k):
        # 每个等长组合等概率
        tot += max(combo)
    return tot / (len(scores) ** k)


def main() -> None:
    print("=" * 100)
    print("「跑三次取最高」赛制下的保底能力（p 用经验频率，n 见最右列）")
    print("=" * 100)
    hdr = f"{'臂':<14}{'均值':>8}{'n':>3}"
    for t in THRESHOLDS:
        hdr += f"{f'≥{t}单次':>10}{f'三次取最高':>12}"
    hdr += f"{'E[max3]':>10}"
    print(hdr)
    print("-" * 100)
    rows = []
    for name, sc in ARMS.items():
        row = f"{name:<14}{sum(sc)/len(sc):>8.2f}{len(sc):>3}"
        rec = {"arm": name, "mean": sum(sc) / len(sc)}
        for t in THRESHOLDS:
            ps = p_single(sc, t)
            pm = p_max_at_least(sc, t)
            row += f"{ps*100:>9.0f}%{pm*100:>11.1f}%"
            rec[f"p60_single"] = p_single(sc, 60) if t == 60 else rec.get("p60_single")
            rec[f"p60_max3"] = p_max_at_least(sc, 60) if t == 60 else rec.get("p60_max3")
        em = expected_max(sc)
        row += f"{em:>10.2f}"
        rec["emax3"] = em
        rows.append(rec)
        print(row)

    print()
    print("=" * 100)
    print("关键结论")
    print("=" * 100)
    for r in rows:
        print(f"  {r['arm']:<14} 单次≥60 = {r['p60_single']*100:>3.0f}%   "
              f"三次取最高≥60 = {r['p60_max3']*100:>5.1f}%   "
              f"期望最高分 = {r['emax3']:.2f}")

    print("\n  注：n 很小（2–7 局），这些是经验估计而非精确概率；")
    print("      但\"三次取最高\"对 p 的放大效应是确定的 —— 单次 75% ⇒ 三次 98.4%，单次 25% ⇒ 三次仅 57.8%。")


if __name__ == "__main__":
    main()
