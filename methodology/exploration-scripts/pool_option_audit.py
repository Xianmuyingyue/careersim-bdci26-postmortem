#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★★★ 用官方全池真值（decoded_dev/action_pool）严格检验「暴露窗零成本律」的可执行性。

回答三件事：
  Q1 全池有多少选项？关键词清单（原则族/投入族）在**全池**上的判别力如何？
  Q2 每个剧情节点的选项集中，**是否存在**「ΔN≥0 且 ΔO≥0」的安全选项？比例多少？
     （这才是「零成本模式可执行吗」的真答案——不是在已选样本上拟合）
  Q3 若强制改选安全选项，其它维（Health/Dignity/HiddenRisk）的代价有多大？

用法：.venv/bin/python3 analysis/pool_option_audit.py
"""
import json, glob, re, pathlib, statistics
from collections import Counter, defaultdict

POOL = pathlib.Path("../官方资料/decoded_dev/action_pool")
KEYS = ["Skill", "Output", "Network", "Dignity", "Health", "HiddenRisk", "Wealth"]

FAM = {
    "原则族": ["承认", "如实", "按事实", "提出异议", "异议", "拒绝", "守边界", "边界", "合规交接", "坚持原则", "澄清"],
    "投入族": ["接下", "深入准备", "投入", "牵头", "搭建", "正式信", "表扬信", "补救", "深度", "主动承担", "加班"],
}


def fam_of(text):
    return [n for n, kws in FAM.items() if any(k in text for k in kws)]


def load_pool():
    """返回 [(event_id, event_name, node_id, node_desc, choice_idx, action_text, updates)]"""
    rows = []
    files = sorted(glob.glob(str(POOL / "short_chain" / "*.json"))) + \
            sorted(glob.glob(str(POOL / "long_chain" / "*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        eid, ename = d.get("event_id", ""), d.get("event_name", "")
        for nid, node in (d.get("nodes") or {}).items():
            chs = node.get("choices") or []
            for i, ch in enumerate(chs):
                rows.append(dict(eid=eid, ename=ename, nid=nid,
                                 desc=node.get("description", ""),
                                 idx=i + 1,
                                 act=str(ch.get("action") or ""),
                                 upd=dict(ch.get("status_updates") or {})))
    return files, rows


def main():
    files, rows = load_pool()
    print(f"=== 全池：{len(files)} 个事件文件，{len(rows)} 个可选选项 ===")
    nodes = defaultdict(list)
    for r in rows:
        nodes[(r["eid"], r["nid"])].append(r)
    print(f"    其中带 choices 的节点 {len(nodes)} 个；平均每节点 {len(rows)/max(len(nodes),1):.2f} 个选项")

    def g(upd, k):
        return upd.get(k, 0)

    # ---------- Q1 ----------
    print("\n【Q1】keyword 清单在全池上的判别力（ΔN / ΔO 真值）")
    g1 = defaultdict(list)
    for r in rows:
        key = "+".join(fam_of(r["act"])) if fam_of(r["act"]) else "未命中"
        g1[key].append(r)
    base_n = statistics.mean(g(upd, "Network") for upd in [r["upd"] for r in rows])
    base_o = statistics.mean(g(upd, "Output") for upd in [r["upd"] for r in rows])
    print(f"    全池基线：ΔN 均 {base_n:+.2f}   ΔO 均 {base_o:+.2f}")
    for key in sorted(g1, key=lambda k: -len(g1[k])):
        v = g1[key]
        dn = [g(r["upd"], "Network") for r in v]
        do = [g(r["upd"], "Output") for r in v]
        print(f"    {key:<12} n={len(v):<5} ΔN 均 {statistics.mean(dn):+.2f}  ΔO 均 {statistics.mean(do):+.2f}"
              f"   P(ΔN<0)={sum(1 for x in dn if x<0)/len(dn)*100:4.0f}%  P(ΔO<0)={sum(1 for x in do if x<0)/len(do)*100:4.0f}%")

    # ---------- Q2 ----------
    print("\n【Q2】★ 每个节点是否存在「ΔN≥0 且 ΔO≥0」的安全选项")
    no_safe = []
    stat = Counter()
    for (eid, nid), opts in nodes.items():
        safe = [o for o in opts if g(o["upd"], "Network") >= 0 and g(o["upd"], "Output") >= 0]
        stat["total"] += 1
        if safe:
            stat["has_safe"] += 1
            stat["safe_cnt"] += len(safe)
        else:
            no_safe.append((opts[0]["ename"], nid, opts))
    print(f"    节点总数 {stat['total']}；**存在安全选项的 {stat['has_safe']} = {stat['has_safe']/stat['total']*100:.1f}%**"
          f"；安全选项共 {stat['safe_cnt']} 个（每节点均值 {stat['safe_cnt']/max(stat['has_safe'],1):.2f}）")
    print(f"    ⚠️ 无安全选项的节点 {len(no_safe)} 个：")
    for ename, nid, opts in no_safe[:16]:
        o = " ; ".join(f"[{x['idx']}]{x['act'][:22]}(N{g(x['upd'],'Network'):+d},O{g(x['upd'],'Output'):+d})" for x in opts)
        print(f"      {ename[:26]:<28} {o}")

    # ---------- Q3 ----------
    print("\n【Q3】安全选项 vs 全池：其它维的代价")
    safe_all, unsafe_all = [], []
    for (eid, nid), opts in nodes.items():
        for o in opts:
            (safe_all if (g(o["upd"], "Network") >= 0 and g(o["upd"], "Output") >= 0) else unsafe_all).append(o)
    def m(v, k):
        return statistics.mean(g(x["upd"], k) for x in v)
    print(f"    安全组 n={len(safe_all)}   非安全组 n={len(unsafe_all)}")
    for k in KEYS:
        print(f"      Δ{k:<11} 安全 {m(safe_all,k):+.2f}   非安全 {m(unsafe_all,k):+.2f}   差 {m(safe_all,k)-m(unsafe_all,k):+.2f}")

    # ---------- Q4 ----------
    print("\n【Q4】★ 攻顶情形：把「上一月末已顶格」的约束加进来")
    print("    （L1 顶格 = 目标维已达 CAP ⇒ 增益被丢弃、扣减全额生效）")
    # 在 L1 语境的真实代价：安全选项失去多少 skill/dignity/health
    print(f"    ⇒ 安全选项的 ΔSkill = {m(safe_all,'Skill'):+.2f}（非安全 {m(unsafe_all,'Skill'):+.2f}）")
    print(f"    ⇒ 安全选项的 ΔDignity = {m(safe_all,'Dignity'):+.2f}（非安全 {m(unsafe_all,'Dignity'):+.2f}）")
    print(f"    ⇒ 安全选项的 ΔHiddenRisk = {m(safe_all,'HiddenRisk'):+.2f}（非安全 {m(unsafe_all,'HiddenRisk'):+.2f}）")
    print(f"    ⇒ 安全选项的 ΔHealth = {m(safe_all,'Health'):+.2f}（非安全 {m(unsafe_all,'Health'):+.2f}）")

    # ---------- Q5 ----------
    print("\n【Q5】★ 上界核算：如果 M5 全月严格选安全选项，最多能救回几局")
    print("    观测事实（56 局）：M5 末顶格 (9,3,3) 的 34 局")
    print("    12 局因最后动作扣 N/O 落榜；若每次都在有安全选项的节点改选 ⇒ 理论上可全救")
    print("    ⇒ M6 晋级率天花板 = 30/56 → 42/56（53.6% → 75.0%）")
    print("    ⚠️ 但前提是：(a) 该节点存在安全选项；(b) Agent 能把它认出来；(c) 改选不带来新代价")


if __name__ == "__main__":
    main()
