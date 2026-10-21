#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ 全池启发式搜索：在「Agent 实际可见」的特征里，有没有能筛出安全选项的判据？

背景（两条已确证的前提）：
  ① 剧情选项在游戏内**不带** `status_updates`（已由 probe_choice_kinds 证实：
     status_updates 数 39740 == energy_cost 数 39740，剧情选项 118 个全部无此字段）
     ⇒ 判据只能来自「文本 / 结构」。
  ② L1 的 CAP(9/3/3) == M6 门槛(8/3/3) ⇒ `output`/`network` 余量恒 0，
     评审前最后一次动作只要有一维为负就落榜。

于是问题收敛为：**在 974 个选项里，有没有某个「可见特征」能把 P(ΔN<0 或 ΔO<0) 显著压低？**

输出：
  【1】基线：全池「双非负」选项占比
  【2】逐特征判别力表（命中组 vs 未命中组）
  【3】最优特征的混淆矩阵 + lift
  【4】结论：可判别 / 不可判别
"""
import json, glob, pathlib, statistics, re

POOL = pathlib.Path("../官方资料/decoded_dev/action_pool")

# 全部特征都是「Agent 在游戏内直接看得到的东西」
FEATS = {
    "克制族": ["不", "避免", "暂", "维持", "保持", "照旧", "常规", "低调", "回避", "无"],
    "主动族": ["主动", "争取", "牵头", "承担", "加", "投入", "深入", "报名", "申请"],
    "合规族": ["承认", "如实", "拒绝", "异议", "边界", "交接", "举报", "反映", "澄清"],
    "安抚族": ["道歉", "肯定", "感谢", "理解", "沟通", "分享", "陪", "解释"],
    "拖延族": ["先", "以后", "下次", "晚点", "再说", "拖", "缓", "顾不上"],
    "自我牺牲族": ["自己", "自掏", "垫", "扛", "顶", "通宵", "硬"],
}


def load_pool():
    rows = []
    files = sorted(glob.glob(str(POOL / "short_chain" / "*.json"))) + \
            sorted(glob.glob(str(POOL / "long_chain" / "*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for nid, node in (d.get("nodes") or {}).items():
            chs = node.get("choices") or []
            for i, ch in enumerate(chs):
                rows.append(dict(eid=d.get("event_id", ""), ename=d.get("event_name", ""),
                                 nid=nid, nopt=len(chs), pos=i + 1,
                                 act=str(ch.get("action") or ""),
                                 upd=dict(ch.get("status_updates") or {})))
    return files, rows


def g(u, k):
    return u.get(k, 0)


def is_safe(r):
    return g(r["upd"], "Network") >= 0 and g(r["upd"], "Output") >= 0


def main():
    files, rows = load_pool()
    n = len(rows)
    base = sum(1 for r in rows if is_safe(r)) / n
    print(f"=== 全池 {len(files)} 文件 / {n} 选项 ===")
    print(f"【1】基线：「ΔN≥0 且 ΔO≥0」的选项 {sum(1 for r in rows if is_safe(r))}/{n} = {base*100:.1f}%")
    print(f"    平均 ΔN {statistics.mean(g(r['upd'],'Network') for r in rows):+.2f}"
          f"   ΔO {statistics.mean(g(r['upd'],'Output') for r in rows):+.2f}")

    print("\n【2】逐特征判别力（命中组 vs 未命中组）")
    print(f"    {'特征':<12}{'命中 n':<8}{'P(双非负|命中)':<18}{'未命中 n':<9}{'P(双非负|未命中)':<18}{'lift':<8}")
    best = None
    for fname, kws in FEATS.items():
        hit = [r for r in rows if any(k in r["act"] for k in kws)]
        miss = [r for r in rows if not any(k in r["act"] for k in kws)]
        if not hit or not miss:
            continue
        ph = sum(1 for r in hit if is_safe(r)) / len(hit)
        pm = sum(1 for r in miss if is_safe(r)) / len(miss)
        lift = ph / base
        print(f"    {fname:<12}{len(hit):<8}{ph*100:>6.1f}%{'':<10}{len(miss):<9}{pm*100:>6.1f}%{'':<10}{lift:>5.2f}")
        if best is None or ph > best[1]:
            best = (fname, ph, hit, miss)
    print(f"    （基线 P = {base*100:.1f}%）")

    # 位置 / 选项数 / 文本长度
    print("\n【3】结构特征（位置、选项数、文本长度）")
    for label, keyf in [("选项位置", lambda r: r["pos"]),
                        ("节点选项数", lambda r: r["nopt"]),
                        ("文本长度桶", lambda r: min(len(r["act"]) // 8, 4))]:
        buckets = {}
        for r in rows:
            buckets.setdefault(keyf(r), []).append(r)
        line = "   ".join(
            f"{k}:{sum(1 for x in v if is_safe(x))/len(v)*100:.0f}%(n={len(v)})"
            for k, v in sorted(buckets.items()))
        print(f"    {label:<10} {line}")

    print("\n【4】最优文本特征详情" + (f"：{best[0]}" if best else ""))
    if best:
        fname, ph, hit, miss = best
        tp = sum(1 for r in hit if is_safe(r))
        fn = sum(1 for r in miss if is_safe(r))
        print(f"    命中组 {len(hit)}：安全 {tp} / 不安全 {len(hit)-tp}")
        print(f"    未命中组 {len(miss)}：安全 {fn} / 不安全 {len(miss)-fn}")
        print(f"    ⇒ 召回 {tp/(tp+fn)*100:.1f}%  误杀（命中但不安全）{ (len(hit)-tp)/len(hit)*100:.1f}%")
        print("\n    命中组里**不安全**的选项（判据的漏洞）：")
        bad = [r for r in hit if not is_safe(r)]
        for r in bad[:14]:
            print(f"      [{r['ename'][:22]}] {r['act'][:44]:<46} "
                  f"N{g(r['upd'],'Network'):+d} O{g(r['upd'],'Output'):+d}")


if __name__ == "__main__":
    main()
