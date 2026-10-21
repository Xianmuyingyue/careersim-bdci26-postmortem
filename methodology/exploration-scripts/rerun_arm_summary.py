#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补测两臂（v3_rerun / v8_3_rerun）与历史臂的成绩对照。"""
import statistics as st

ARMS = [
    ("v3_rerun",    [73.12, 75.04, 30.80, 75.88], [6, 6, 3, 6], [48, 48, 24, 48],
     "2026-09-27 复测"),
    ("v8_3_rerun",  [56.92, 59.42, 72.96, 50.28], [4, 4, 6, 4], [48] * 4,
     "2026-09-27 复测"),
    ("v10c(历史)",  [70.26, 32.06, 63.88, 70.51], [6, 2, 5, 6], [48, 24, 48, 48],
     "2026-09-26"),
    ("v10e(历史)",  [53.02, 31.56],               [4, 2],       [48, 24],
     "2026-09-27 起 4 局仅 2 局跑成"),
]

print(f"{'臂':<14}{'n':>3}{'均值':>8}{'样本sd':>9}{'早死':>7}{'通关率':>8}   最终职级")
print("-" * 78)
for name, sc, lv, mo, note in ARMS:
    done = [s for s, m in zip(sc, mo) if m == 48]
    dead = len(sc) - len(done)
    sd = st.stdev(sc) if len(sc) > 1 else 0.0
    print(f"{name:<14}{len(sc):>3}{st.mean(sc):>8.2f}{sd:>9.2f}"
          f"{dead}/{len(sc):>5}{len(done)/len(sc)*100:>7.0f}%   {lv}")

print("\n完赛局（48 月）单独看：")
print(f"{'臂':<14}{'n':>3}{'均值':>8}{'样本sd':>9}")
print("-" * 40)
for name, sc, lv, mo, note in ARMS:
    done = [s for s, m in zip(sc, mo) if m == 48]
    if not done:
        continue
    sd = st.stdev(done) if len(done) > 1 else 0.0
    print(f"{name:<14}{len(done):>3}{st.mean(done):>8.2f}{sd:>9.2f}")

print("\n备注：")
for name, sc, lv, mo, note in ARMS:
    print(f"  {name:<14} {note}")
