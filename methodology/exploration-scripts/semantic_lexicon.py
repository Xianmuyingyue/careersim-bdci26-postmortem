"""从 Dev 事件池反推「语义 → 数值」启发式词典。

为什么需要它
------------
剧情选项的 `status_updates` 对 Agent **不可见**（只有体力/主行动的数值写在手册里）。
但晋升评审读的是「评审月最后一次决策后的状态」，所以 Agent 必须能预判选项会不会扣
`network` / `output`。本脚本用 Dev 全池 171 个事件文件做统计，给出可复用的语义线索。

方法
----
对每个选项（action 文案）统计 ΔNetwork / ΔOutput / ΔSkill / ΔHiddenRisk，
然后按「关键词命中」分组对比均值，挑出区分度最高的词。
只输出词表，不输出任何 event_id —— 避免把技能写成对 Dev 具体事件的硬编码。
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL = os.path.join(os.path.dirname(ROOT), "官方资料", "decoded_dev", "action_pool")

KEYS = ["Network", "Output", "Skill", "HiddenRisk", "Dignity", "Health"]
# 候选语义词：按「行为意图」分类，而不是具体事件
CAND = {
    "争取/主导": ["主动", "牵头", "承担", "争取", "负责", "主导", "推进", "报名", "揽下"],
    "回避/退缩": ["拒绝", "不报名", "拒绝挂名", "回避", "不参与", "置身事外", "低调", "事不关己", "不解释", "沉默"],
    "对抗/揭露": ["举报", "揭发", "越级", "对抗", "投诉", "当众指出", "质疑", "挑战", "举报VP", "曝光", "对质", "反映"],
    "私下/保密": ["私下", "保密", "不透露", "装不知", "隐瞒", "匿名", "留痕", "书面"],
    "自我宣传": ["突出个人", "个人品牌", "补充自己", "强调自己", "巩固", "炫耀"],
    "让利/合作": ["肯定", "感谢", "帮助", "协助", "共同", "分享", "轮流", "公平", "折中", "陪同"],
    "诚实/担责": ["承认", "如实", "主动坦承", "道歉", "揽下主责", "澄清"],
    "违规/捷径": ["默许", "签字", "合入", "通融", "变通", "顺水推舟", "睁一只眼"],
}


def main() -> None:
    recs = []
    for f in glob.glob(os.path.join(POOL, "*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for node, body in (d.get("nodes") or {}).items():
            for c in body.get("choices") or []:
                txt = (c.get("action") or "").strip()
                if not txt:
                    continue
                su = c.get("status_updates") or {}
                recs.append((txt, {k: float(su.get(k, 0)) for k in KEYS}))
    print(f"Dev 选项样本 = {len(recs)}\n")

    tot = {k: sum(r[1][k] for r in recs) for k in KEYS}
    print("全池均值（每个选项的期望值）: " + "  ".join(f"{k} {tot[k]/len(recs):+.3f}" for k in KEYS))

    print("\n" + "=" * 108)
    print("★ 语义词 × 数值（命中该词的选项均值 − 全池均值 = 该词的「边际效应」）")
    print("=" * 108)
    print(f"{'语义组':<12} {'词':<10} {'命中':>4} | {'ΔNet':>7} {'ΔOut':>7} {'ΔSkill':>7} "
          f"{'ΔRisk':>7} {'ΔDig':>7} | 判定")
    for grp, words in CAND.items():
        for w in words:
            hit = [r for r in recs if w in r[0]]
            if len(hit) < 4:
                continue
            m = {k: sum(r[1][k] for r in hit) / len(hit) for k in KEYS}
            d = {k: m[k] - tot[k] / len(recs) for k in KEYS}
            # 判定：是否值得作为「保护区」线索
            verdict = []
            if d["Network"] <= -0.35:
                verdict.append("扣N")
            if d["Output"] <= -0.5:
                verdict.append("扣O")
            if d["HiddenRisk"] >= 0.40:
                verdict.append("注入风险")
            if d["Network"] >= 0.35:
                verdict.append("补N")
            if d["HiddenRisk"] <= -0.40:
                verdict.append("降风险")
            print(f"{grp:<12} {w:<10} {len(hit):>4} | {d['Network']:>+7.2f} {d['Output']:>+7.2f} "
                  f"{d['Skill']:>+7.2f} {d['HiddenRisk']:>+7.2f} {d['Dignity']:>+7.2f} | "
                  f"{','.join(verdict) or '-'}")

    print("\n" + "=" * 108)
    print("★ 极端选项画像（用于识别「保护区红线选项」）")
    print("=" * 108)
    for name, pred in [
        ("ΔNetwork ≤ −2", lambda v: v["Network"] <= -2),
        ("ΔOutput ≤ −2", lambda v: v["Output"] <= -2),
        ("ΔHiddenRisk ≥ +2", lambda v: v["HiddenRisk"] >= 2),
        ("ΔHiddenRisk ≥ +3", lambda v: v["HiddenRisk"] >= 3),
    ]:
        hit = [r for r in recs if pred(r[1])]
        print(f"\n  {name}：{len(hit)} 个选项")
        kw = Counter()
        for txt, _ in hit:
            for w in ["举报", "越级", "对抗", "拒绝", "不报名", "回避", "隐瞒", "默许", "合入",
                      "主动", "牵头", "承担", "举报VP", "当众", "挑战", "私下", "保密", "承认",
                      "让", "抢", "争", "推", "沉默", "忍", "投诉", "对质", "曝光", "甩", "背锅"]:
                if w in txt:
                    kw[w] += 1
        print("    高频词: " + ", ".join(f"{k}×{v}" for k, v in kw.most_common(10)))
        for txt, v in hit[:6]:
            print(f"      [{txt[:46]}]  N{v['Network']:+.0f} O{v['Output']:+.0f} R{v['HiddenRisk']:+.0f}")

    print("\n" + "=" * 108)
    print("★ 剧情链「终点节点」画像：长链结局节点的数值分布（决定下游代价）")
    print("=" * 108)
    ends = []
    for f in glob.glob(os.path.join(POOL, "*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for node, body in (d.get("nodes") or {}).items():
            if "story_end" not in node:
                continue
            for c in body.get("choices") or []:
                su = c.get("status_updates") or {}
                if su:
                    ends.append((node, {k: float(su.get(k, 0)) for k in KEYS}))
    print(f"  有数值的结局节点数 = {len(ends)}")
    neg = [e for e in ends if e[1]["Network"] < 0 or e[1]["Output"] < 0]
    print(f"  其中扣 N 或 O 的 = {len(neg)}（{len(neg)/max(1,len(ends))*100:.0f}%）")
    for node, v in ends[:10]:
        print(f"    {node[:38]:<40} N{v['Network']:+.0f} O{v['Output']:+.0f} "
              f"S{v['Skill']:+.0f} R{v['HiddenRisk']:+.0f} D{v['Dignity']:+.0f}")


if __name__ == "__main__":
    main()
