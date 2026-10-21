#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ 判据的「样本外验证」：把在 M5（57 局）上挑出来的判据，放回全池 412 节点独立复算。

为什么必须做这一步：
  在 57 个 M5 节点上比较 8 条判据，等于**在一个小样本上做 8 次选择**
  ⇒ 必然挑出一条"看起来最好"的，即使它们等价。n=57 时 1σ ≈ 6.6pp，
     所以任何 +10pp 级别的差异都可能是抽样波动。

判据可信的**必要条件**：它在与 M5 样本基本独立的全池 412 节点上也成立。

输出：全池 412 节点上每条判据的「选中项安全率」+「代价维」，并与 M5 实测值并列。
"""
import json, glob, pathlib, re, statistics
from collections import defaultdict

POOL = pathlib.Path("../官方资料/decoded_dev/action_pool")
KEYS = ["Skill", "Output", "Network", "Dignity", "Health", "HiddenRisk"]

COMPLIANCE = ["承认", "如实", "按事实", "提出异议", "异议", "拒绝", "守边界", "边界",
              "合规交接", "坚持原则", "澄清", "举报", "反映", "不解释", "匿名", "沉默"]
ACTIVE = ["主动", "争取", "牵头", "承担", "报名", "请缨", "加班", "投入", "深入"]
NUMWORD = re.compile(r"\d+\s*(天|周|个月|月|小时|次|遍|轮)")


def g(u, k):
    return (u or {}).get(k, 0)


def safe(o):
    u = o.get("status_updates") or {}
    return g(u, "Network") >= 0 and g(u, "Output") >= 0


RULES = {
    "位置1": lambda order: order[0],
    "位置最后": lambda order: order[-1],
    "最长文本": lambda order: max(order, key=lambda c: len(str(c.get("action") or ""))),
    "最短文本": lambda order: min(order, key=lambda c: len(str(c.get("action") or ""))),
    "最长且非原则族": lambda order: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not any(k in str(c.get("action") or "") for k in COMPLIANCE)), None),
    "最长且无承诺数字": lambda order: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not NUMWORD.search(str(c.get("action") or ""))), None),
    "非主动族里最长": lambda order: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not any(k in str(c.get("action") or "") for k in ACTIVE)), None),
    "神谕(真值上限)": lambda order: next((c for c in order if safe(c)), None),
}

# 上一轮在 57 个 M5 节点上实测到的命中率（用于并列对照）
M5_HIT = {"位置1": 27 / 57, "位置最后": 34 / 57, "最长文本": 35 / 57, "最短文本": 29 / 57,
          "最长且非原则族": 38 / 57, "最长且无承诺数字": 35 / 57, "非主动族里最长": 35 / 57,
          "神谕(真值上限)": 55 / 57}


def main():
    nodes = []
    files = sorted(glob.glob(str(POOL / "short_chain" / "*.json"))) + \
            sorted(glob.glob(str(POOL / "long_chain" / "*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for nid, node in (d.get("nodes") or {}).items():
            chs = node.get("choices") or []
            if chs:
                nodes.append(dict(ename=d.get("event_name", ""), nid=nid, chs=chs))
    n = len(nodes)
    allopts = [c for x in nodes for c in x["chs"]]
    base = sum(1 for o in allopts if safe(o)) / len(allopts)
    print(f"=== 全池节点 {n} 个 / 选项 {len(allopts)} 个；选项级基线安全率 {base*100:.1f}% ===")

    print(f"\n【1】判据在全池（样本外）的表现")
    print(f"    {'判据':<16}{'全池命中率':<12}{'M5 实测':<10}{'一致性差':<10}{'全池ΔN':<10}{'全池ΔO':<10}{'代价维(ΔH/ΔD/ΔR)'}")
    out = []
    for nm, fn in RULES.items():
        hit, picked = 0, []
        for x in nodes:
            try:
                o = fn(x["chs"])
            except Exception:
                o = None
            if o is not None:
                picked.append(o)
                if safe(o):
                    hit += 1
        pool_rate = hit / n
        m5 = M5_HIT.get(nm, float("nan"))
        dn = statistics.mean(g(o.get("status_updates"), "Network") for o in picked)
        do = statistics.mean(g(o.get("status_updates"), "Output") for o in picked)
        dh = statistics.mean(g(o.get("status_updates"), "Health") for o in picked)
        dd = statistics.mean(g(o.get("status_updates"), "Dignity") for o in picked)
        dr = statistics.mean(g(o.get("status_updates"), "HiddenRisk") for o in picked)
        out.append((nm, pool_rate, m5))
        print(f"    {nm:<16}{pool_rate*100:>6.1f}%{'':<5}{m5*100:>5.1f}%{'':<4}"
              f"{(m5-pool_rate)*100:>+6.1f}pp{'':<3}{dn:>+6.2f}{'':<4}{do:>+6.2f}{'':<4}"
              f"H{dh:+.2f} D{dd:+.2f} R{dr:+.2f}")

    print(f"\n【2】判定：哪些判据「不是噪声」")
    print("    通过标准：① 全池命中率显著高于基线；② 全池与 M5 的一致性差 |Δ| ≤ 10pp")
    print(f"    （基线 = {base*100:.1f}%）")
    for nm, pool_rate, m5 in out:
        ok1 = pool_rate > base + 0.05
        ok2 = abs(m5 - pool_rate) <= 0.10
        verdict = "★ 可信" if (ok1 and ok2) else ("✗ 噪声（全池未复现）" if not ok1 else "⚠ 中等")
        print(f"    {nm:<16} 全池 {pool_rate*100:5.1f}%  M5 {m5*100:5.1f}%  ⇒ {verdict}")

    print("\n【3】★ 位置效应的真相：M5 里「最后位」好，全池里呢？")
    from collections import Counter
    pos_last = Counter()
    for x in nodes:
        L = len(x["chs"])
        o = x["chs"][-1]
        pos_last[L] += 1 if safe(o) else 0
    pos_all = Counter(len(x["chs"]) for x in nodes)
    print(f"    {'节点选项数':<12}{'节点数':<8}{'最后位安全率'}")
    for L in sorted(pos_all):
        print(f"    {L:<12}{pos_all[L]:<8}{pos_last[L]/pos_all[L]*100:>6.0f}%")
    tot_last = sum(pos_last.values())
    print(f"    合计最后位安全率 = {tot_last/n*100:.1f}%  （基线 {base*100:.1f}%）")

    print("\n【4】文本长度是「真机制」还是伪相关？看长度分桶的安全率")
    buckets = defaultdict(list)
    for o in allopts:
        buckets[len(str(o.get("action") or "")) // 6].append(o)
    print(f"    {'长度桶(每6字)':<14}{'n':<7}{'安全率':<10}{'ΔN':<9}{'ΔO'}")
    for b in sorted(buckets):
        v = buckets[b]
        r = sum(1 for o in v if safe(o)) / len(v)
        print(f"    {b:<14}{len(v):<7}{r*100:>6.0f}%{'':<4}"
              f"{statistics.mean(g(o.get('status_updates'),'Network') for o in v):>+6.2f}{'':<3}"
              f"{statistics.mean(g(o.get('status_updates'),'Output') for o in v):>+6.2f}")


if __name__ == "__main__":
    main()
