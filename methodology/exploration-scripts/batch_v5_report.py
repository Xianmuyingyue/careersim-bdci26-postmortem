"""v5 批次判读报告（真值口径）—— 4 局新策略 vs 2 局基线。

修正了两个旧版 bug
------------------
1. `hr_ladder` 旧版用字符串键查 `int` 键 ⇒ 全 0。现在**直接读 `analysis/ab/metrics/<run>.json`**，
   那是批次守护进程在跑局时同步采集的权威产物（含 `bursts` / `hr_seq` / `level_timeline` /
   `clamp_occupancy` / `capped_field_months`），比从 replay 反推更可靠。
2. `burst_crossings` 旧版用 `pre + delta >= 5` 判定，忽略 `hidden_risk` 的 0 下界截断 ⇒ 数字虚高。
   现在直接用 `metrics.bursts`（引擎侧计数）。

窗口审计改用 replay 的 `**状态:**` 行（Agent 亲自观测到的真值），不再用会被 `clamp_stats`
上限吸收效应污染的重建值（详见 `perf_gate_audit.py` 的说明）。

用法： env -u PYTHONPATH .venv/bin/python analysis/batch_v5_report.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from postmortem_run import OUTROOT, analyze  # noqa: E402
from perf_gate_audit import GATES, KEYS, perf_of, parse_replay  # noqa: E402

METRICS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab", "metrics")
BOUNDS = [6, 12, 18, 24, 30, 36, 42, 48]
V5 = ["20260925T034626Z", "20260925T042320Z", "20260925T043821Z", "20260925T050758Z"]
BASE = ["20260924T144338Z", "20260925T015009Z"]
ENERGY_NAMES = ("高强度工作", "技能学习", "人脉维护", "处理历史埋雷",
                "心理修复", "健康恢复", "准备汇报材料")
MAIN_NAMES = ("申请关键项目", "向领导汇报成果", "主动争取资源", "申请岗位轮岗",
              "主动曝光成果", "建立导师关系", "修复关键关系", "低调避险")
COST = {"技能学习": 2, "处理历史埋雷": 2, "高强度工作": 2}
HR_LABEL = {"L0_safe": "笑0", "L1_mild": "偷1", "L2_accum": "皱2",
            "L3_critical": "复3", "L4plus_imminent": "生气≥4"}


def strip_c(s: str) -> str:
    return re.sub(r"^\[\d+\]\s*", "", (s or "").strip()).split("—")[0].strip()


def load_metrics(run: str) -> dict:
    p = os.path.join(METRICS, f"{run}.json")
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def window_audit(run: str) -> list[str]:
    first, _last, promo, rapid = parse_replay(run)
    out = []
    for rk in BOUNDS:
        if rk not in first:
            break
        s = dict(first[rk])
        pv = promo.get(rk - 1)
        if pv:
            lv = pv[0]
            s["network"] -= GATES[lv][4]
            out.append(f"M{rk-1}末:{lv}→{pv[1]}✓" + ("$" if rapid.get(rk - 1) else ""))
        else:
            lv = s["level"]
            g = GATES[lv]
            miss = [f"{k}{s[k]-g[i]:+.0f}" for i, k in enumerate(KEYS) if s[k] - g[i] < 0]
            pf, _ = perf_of(s, lv, rk)
            if miss:
                out.append(f"M{rk-1}末:{lv}✗({','.join(miss)})")
            elif pf < g[5]:
                out.append(f"M{rk-1}末:{lv}✗(★perf{pf}<{g[5]})")
            else:
                out.append(f"M{rk-1}末:{lv}✗(★四门+perf全过)")
    return out


def main() -> None:
    rows = []
    for run in V5 + BASE:
        tag = "v5" if run in V5 else "base"
        a = analyze(run)
        mt = load_metrics(run)
        sr = json.load(open(os.path.join(OUTROOT, run, "score_report.json"), encoding="utf-8"))
        es = sr["ending_score"]
        energy, main = Counter(), Counter()
        for r in a["rows"]:
            c = strip_c(r["choice"])
            if c in ENERGY_NAMES:
                energy[c] += 1
            elif c in MAIN_NAMES:
                main[c] += 1
        txt = open(os.path.join(OUTROOT, run,
                                [f for f in os.listdir(os.path.join(OUTROOT, run))
                                 if f.startswith("replay-")][0]), encoding="utf-8").read()
        md = re.search(r"出局:\*\*\s*(.+?)(?:\n|$)", txt)
        rows.append({
            "run": run, "tag": tag,
            "grade": es["grade"], "score": es["quantitative_score"],
            "months": es["survival_months"],
            "reason": (md.group(1)[:22] if md else "完赛"),
            "raw": {d["name"]: d["raw_value"] for d in es["dimensions"]},
            "wins": window_audit(run),
            "energy": energy, "main": main,
            "epoints": sum(n * COST.get(k, 1) for k, n in energy.items()),
            "bursts": mt.get("bursts"),
            "hr": mt.get("hr_ladder", {}),
            "clamp": mt.get("clamp_occupancy", {}),
            "capped_months": mt.get("capped_field_months", {}),
        })

    W = 122
    print("=" * W)
    print("v5 批次判读（4 局新策略 vs 2 局基线）—— 窗口审计取 replay 状态行真值，风险取引擎计数")
    print("=" * W)
    print(f"{'run':>18} {'tag':>5} {'级':>2} {'分':>6} {'月':>3} {'S/N/O':>13} {'D/H':>6} "
          f"{'风险维':>6} {'爆雷':>4} {'体力点':>6}  结局")
    print("-" * W)
    for d in rows:
        r = d["raw"]
        print(f"{d['run']:>18} {d['tag']:>5} {d['grade']:>2} {d['score']:>6.2f} {d['months']:>3} "
              f"{r.get('skill',0):>5.0f}/{r.get('network',0):>3.0f}/{r.get('output',0):>3.0f}"
              f"{'':>2}{r.get('resilience',0):>4.0f}/{r.get('health',0) if 'health' in r else 0:>2.0f}"
              f"{r.get('risk_control',0):>7.1f} {str(d['bursts']):>4} {d['epoints']:>6}  {d['reason']}")

    print("\n" + "=" * W)
    print("★ 窗口审计（边界 = 评审结算所在的月末；✓ 晋升 / ✗ 未过）")
    print("=" * W)
    for d in rows:
        print(f"\n[{d['run']}] {d['tag']} {d['grade']}")
        for w in d["wins"]:
            print("   " + w)

    print("\n" + "=" * W)
    print("★ 体力构成（次数 → 折合体力点）")
    print("=" * W)
    acts = sorted({k for d in rows for k in d["energy"]})
    print(f"{'行动':<14}" + "".join(f"{d['run'][9:17]:>11}" for d in rows))
    for act in acts:
        print(f"{act:<14}" + "".join(f"{d['energy'].get(act,0):>7}"
                                     f"({d['energy'].get(act,0)*COST.get(act,1):>2})" for d in rows))
    print(f"{'合计点':<14}" + "".join(f"{d['epoints']:>11}" for d in rows))

    print("\n" + "=" * W)
    print("★ 主行动构成")
    print("=" * W)
    print(f"{'行动':<14}" + "".join(f"{d['run'][9:17]:>11}" for d in rows))
    for act in sorted({k for d in rows for k in d["main"]}):
        print(f"{act:<14}" + "".join(f"{d['main'].get(act,0):>11}" for d in rows))

    print("\n" + "=" * W)
    print("★ 风险阶梯真值（引擎侧 hr_ladder 计数）与封顶占用")
    print("=" * W)
    for d in rows:
        hr = d["hr"]
        tot = sum(hr.values()) or 1
        seg = "  ".join(f"{HR_LABEL.get(k,k)}:{v}({v/tot*100:.0f}%)" for k, v in
                        sorted(hr.items(), key=lambda x: str(x[0])))
        print(f"{d['run']:>18} {seg}   bursts={d['bursts']}")
    print("\n  封顶占用（capped_field_months 前 4 项）:")
    for d in rows:
        cm = sorted(d["capped_months"].items(), key=lambda x: -x[1])[:4]
        print(f"{d['run']:>18} " + ", ".join(f"{k}×{v}" for k, v in cm))
    print("\n  L4 段“output 与 network 同时封顶”的月份数（说明 skill 被饿着）:")
    for d in rows:
        c = d["clamp"].get("L4", {}).get("capped_pairs", {})
        mu = d["clamp"].get("L4", {}).get("mean_use_ratio", {})
        print(f"{d['run']:>18} pairs={c}  use_ratio={ {k: round(v,3) for k,v in mu.items()} }")

    v5 = [d for d in rows if d["tag"] == "v5"]
    base = [d for d in rows if d["tag"] == "base"]
    print("\n" + "=" * W)
    print("★ 批次结论")
    print("=" * W)
    for nm, g in (("v5 (4局)", v5), ("base (2局)", base)):
        n = len(g)
        print(f"  {nm}: 完赛 {sum(1 for d in g if d['months']>=48)}/{n}  "
              f"A 级 {sum(1 for d in g if d['grade']=='A')}/{n}  "
              f"平均分 {sum(d['score'] for d in g)/n:.2f}  "
              f"末级 {[int(d['raw'].get('level',0)) for d in g]}")
    print(f"\n  v5 内部分化：{', '.join(f'{d[run]=}'.split('=')[0] for d in [])}".rstrip() or "")
    print("  " + " | ".join(f"{d['run'][-6:]} {d['grade']}/{d['score']:.1f}/{d['months']}月"
                            for d in v5))


if __name__ == "__main__":
    main()
