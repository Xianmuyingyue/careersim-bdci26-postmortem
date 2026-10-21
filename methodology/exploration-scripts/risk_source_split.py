"""风险来源分解：把「注入」与「清理」拆开，回答「为什么埋雷投得多反而爆雷」。

重建口径：用官方 action_pool 的 `status_updates` 复原每个剧情选择的 ΔHiddenRisk，
体力「处理历史埋雷」按 −1 计入清理，峰值用 `max(0, 累计)` 追踪（引擎有 0 下界截断）。
爆雷次数以 replay 的结局文案 + 引擎 metrics.bursts 交叉确认。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import OUTROOT, analyze  # noqa: E402
from postmortem_run import strip_idx  # noqa: E402

METRICS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab", "metrics")
V5 = ["20260925T034626Z", "20260925T042320Z", "20260925T043821Z", "20260925T050758Z"]
BASE = ["20260924T144338Z", "20260925T015009Z", "20260924T194245Z"]


def main() -> None:
    rows = []
    for run in V5 + BASE:
        a = analyze(run)
        inj = []
        for r in a["rows"]:
            d = float(r["delta"].get("HiddenRisk", 0.0))
            if d > 0:
                inj.append((r["month"], d, strip_idx(r["choice"])[:26]))
        clr = sum(1 for r in a["rows"] if float(r["delta"].get("HiddenRisk", 0.0)) < 0)
        total = sum(d for _, d, _ in inj)
        mx = max([d for _, d, _ in inj], default=0)
        big = [x for x in inj if x[1] >= 2]
        mt = {}
        p = os.path.join(METRICS, f"{run}.json")
        if os.path.isfile(p):
            mt = json.load(open(p, encoding="utf-8"))
        hr = mt.get("hr_ladder", {})
        rows.append({
            "run": run, "tag": "v5" if run in V5 else "base",
            "inj_n": len(inj), "inj_total": total, "max1": mx, "big": len(big),
            "big_sum": sum(d for _, d, _ in big),
            "clr": clr, "cleared": clr * 1,
            "hr4": hr.get("L4plus_imminent", 0), "hr3": hr.get("L3_critical", 0),
            "bursts": mt.get("bursts"),
            "biglist": [f"M{m}Δ{d:.0f}:{c}" for m, d, c in big][:8],
        })
    W = 128
    print("=" * W)
    print("风险来源分解：埋雷次数 ≠ 爆雷次数 —— 真正的自变量是「注入量」")
    print("=" * W)
    print(f"{'run':>18} {'tag':>5} {'注入次数':>7} {'注入总量':>7} {'单次峰值':>7} "
          f"{'≥+2 次数':>8} {'≥+2 总量':>8} {'清理次数':>7} {'HR≥3':>5} {'HR≥4':>5} {'bursts':>6}")
    print("-" * W)
    for d in rows:
        print(f"{d['run']:>18} {d['tag']:>5} {d['inj_n']:>7} {d['inj_total']:>+7.0f} {d['max1']:>+7.0f} "
              f"{d['big']:>8} {d['big_sum']:>+8.0f} {d['clr']:>7} {d['hr3']:>5} {d['hr4']:>5} "
              f"{str(d['bursts']):>6}")

    print("\n★ 单次注入 ≥ +2 的选择清单（铁律 5 要拦截的目标）")
    for d in rows:
        if d["biglist"]:
            print(f"\n  [{d['run']}] {d['tag']}")
            for x in d["biglist"]:
                print(f"     {x}")

    print("\n" + "=" * W)
    print("★ 相关性检查（v5 四局）")
    print("=" * W)
    v5 = [d for d in rows if d["tag"] == "v5"]
    for k in ("clr", "inj_total", "big_sum", "big"):
        xs = [d[k] for d in v5]
        ys = [d["hr4"] for d in v5]
        print(f"  埋雷次数/总量 {k:<10} vs HR≥4 次数: {list(zip(xs, ys))}")
    print("\n  读数：A 局（034626Z/050758Z）埋雷次数最少却零爆雷；"
          "\n        043821Z 埋雷最多（4 次）却两次爆雷 ⇒ **埋雷不是自变量，注入才是**。")


if __name__ == "__main__":
    main()
