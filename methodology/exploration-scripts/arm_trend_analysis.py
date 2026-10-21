#!/usr/bin/env python3
"""从 replay_browser.html 负载抽出全部对局，按臂 / 按日期做横向分解。

回答的问题：最近几臂分数下滑，是**采样波动**、**日期（剧本难度）**，还是**策略本身**？

用法：
    .venv/bin/python3 analysis/arm_trend_analysis.py
    .venv/bin/python3 analysis/arm_trend_analysis.py --csv analysis/_arm_runs.csv
"""
import argparse
import json
import os
import statistics as st

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(os.path.dirname(REPO), "analysis", "replay_browser.html")

# 臂的先后顺序（用于看趋势）；hist 放最前
ARM_ORDER = ["hist", "v1", "v2", "v3", "v5", "v7", "v8", "v8_1", "v8_2", "v8_3", "v8_4",
             "v8_5", "v9", "v10", "v10b", "v10c", "v10d", "v10e"]


def load_runs():
    h = open(HTML, encoding="utf-8").read()
    data, _ = json.JSONDecoder().raw_decode(h[h.find('{"runs":'):])
    arm_of = {}
    for b in data["batches"]:
        for dn in b["dirs"]:
            arm_of[dn] = b["tag"]
    runs = []
    for r in data["runs"]:
        dn = r["dir"]
        sc = r["score"] or {}
        m = r["metrics"] or {}
        # ⚠️ 负载里 `score["dims"]` 是**字典**（键=维名），不是列表
        dims = {}
        for k, v in (sc.get("dims") or {}).items():
            if isinstance(v, dict):
                dims[k] = v.get("raw_value")
        runs.append(dict(
            dir=dn,
            arm=arm_of.get(dn) or m.get("arm") or "?",
            date=dn[:8],
            score=sc.get("score"),
            grade=sc.get("grade"),
            outcome=sc.get("outcome"),
            months=sc.get("months") or m.get("months"),
            # ⚠️ metrics 里叫 `raw_level`（没有 final_level）
            level=m.get("raw_level"),
            bursts=m.get("bursts"),
            obs=m.get("observe_n"),
            tokens=sc.get("tokens"),
            capped=m.get("capped_field_months"),
            clamp=m.get("clamp_occupancy"),
            timeline=m.get("level_timeline"),
            hr=m.get("hr_ladder"),
            **{("d_" + k): v for k, v in dims.items()},
        ))
    return runs


def agg(rows):
    sc = [r["score"] for r in rows if isinstance(r["score"], (int, float))]
    mo = [r["months"] for r in rows if isinstance(r["months"], (int, float))]
    if not sc:
        return None
    early = sum(1 for r in rows if (r["outcome"] == "eliminated"))
    return dict(
        n=len(rows), mean=st.mean(sc), sd=(st.stdev(sc) if len(sc) > 1 else 0.0),
        lo=min(sc), hi=max(sc), early=early,
        mean_months=(st.mean(mo) if mo else 0.0),
        mean_bursts=st.mean([r["bursts"] or 0 for r in rows]),
        mean_level=st.mean([r["level"] or 0 for r in rows]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="把逐局明细写到这里")
    args = ap.parse_args()
    runs = load_runs()
    print("总局数 =", len(runs))

    hdr = ("arm", "n", "mean", "sd", "min", "max", "早死", "均月", "均爆发", "均职级")
    print("\n=== 按臂（按运行先后） ===")
    print("%-7s%3s%8s%7s%7s%7s%5s%7s%8s%7s" % hdr)
    for arm in ARM_ORDER:
        rows = [r for r in runs if r["arm"] == arm]
        if not rows:
            continue
        a = agg(rows)
        print("%-7s%3d%8.2f%7.2f%7.2f%7.2f%5d%7.1f%8.2f%7.2f" % (
            arm, a["n"], a["mean"], a["sd"], a["lo"], a["hi"],
            a["early"], a["mean_months"], a["mean_bursts"], a["mean_level"]))
    other = [r for r in runs if r["arm"] not in ARM_ORDER]
    if other:
        a = agg(other)
        print("%-7s%3d%8.2f%7.2f%7.2f%7.2f%5d%7.1f%8.2f%7.2f" % (
            "其他", a["n"], a["mean"], a["sd"], a["lo"], a["hi"],
            a["early"], a["mean_months"], a["mean_bursts"], a["mean_level"]))
        print("   其他臂 =", sorted({r["arm"] for r in other}))

    print("\n=== 按日期（检验「剧本难度是否随日期漂移」） ===")
    print("%-10s%3s%8s%7s%7s%5s%7s" % ("date", "n", "mean", "sd", "min", "早死", "均月"))
    for d in sorted({r["date"] for r in runs}):
        rows = [r for r in runs if r["date"] == d]
        a = agg(rows)
        print("%-10s%3d%8.2f%7.2f%7.2f%5d%7.1f" % (
            d, a["n"], a["mean"], a["sd"], a["lo"], a["early"], a["mean_months"]))

    print("\n=== 三臂聚焦：v3 / v8_3 / v10e ===")
    print("%-7s%3s%8s%7s%7s%7s%5s%7s%8s%7s" % hdr)
    for arm in ("v3", "v8_3", "v10e"):
        rows = [r for r in runs if r["arm"] == arm]
        a = agg(rows)
        print("%-7s%3d%8.2f%7.2f%7.2f%7.2f%5d%7.1f%8.2f%7.2f" % (
            arm, a["n"], a["mean"], a["sd"], a["lo"], a["hi"],
            a["early"], a["mean_months"], a["mean_bursts"], a["mean_level"]))

    print("\n=== 三臂逐局明细 ===")
    for arm in ("v3", "v8_3", "v10e"):
        print("--- %s" % arm)
        for r in sorted([x for x in runs if x["arm"] == arm], key=lambda x: x["dir"]):
            print("   %s  %s %6.2f  %2s月  L%-3s burst=%-2s obs=%-4s %s" % (
                r["dir"], r["grade"], r["score"], r["months"], r["level"],
                r["bursts"], r["obs"], r["outcome"]))

    if args.csv:
        keys = ["arm", "dir", "date", "grade", "score", "months", "level", "bursts",
                "obs", "outcome", "d_level", "d_wealth", "d_skill", "d_network",
                "d_risk_control", "d_resilience"]
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write(",".join(keys) + "\n")
            for r in runs:
                fh.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
        print("\n已写出逐局明细：%s" % args.csv)


if __name__ == "__main__":
    main()
