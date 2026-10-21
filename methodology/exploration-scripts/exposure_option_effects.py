#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★★ 检验「负向语义清单」到底有没有判别力（可证伪）。

数据集构建：把每一局的**已执行动作**与它**真实的 Δstatus** 配对。
  · 沿 seq 顺序走：维护 last_state；遇到 take_action 记为 pending_call；
    下一个「状态与 last_state 不同」的快照即该动作的效果 ⇒ 结算 Δ，并把 last_state 推进。
  · 选项描述取自 pending_call 发生时那一刻的 `choices`（按 choice 索引取）。

然后做的检验：
  T1  全量：命中「原则族 / 投入族」关键词的选项 vs 未命中 ⇒ `ΔN` / `ΔO` 分布差异
  T2  分相位：暴露窗（month%6 ∈ {5}）内外的差异是否更强
  T3  ★ 同一事件节点在多局被选了不同选项 ⇒ 天然反事实对照（同题异选）
  T4  ★ 每个 M5 节点的选项集里，是否**存在**一个实测 ΔN≥0 且 ΔO≥0 的选项
  T5  被排除的两组在「风险 / 尊严 / 健康」上是否更优（排除它们的代价）
"""
import json, glob, re, pathlib, statistics
from collections import Counter, defaultdict

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
DEC = json.JSONDecoder()
KEYS = ("skill", "output", "network", "dignity", "health")

# 负向语义族（来自 v10b 的实测清单）
FAM = {
    "原则族": ["承认", "如实", "按事实", "提出异议", "异议", "拒绝", "守边界", "边界", "合规交接", "拒绝接收", "坚持原则"],
    "投入族": ["接下", "深入准备", "投入", "牵头", "搭建", "正式信", "表扬信", "当天补救", "补救", "完整搭建", "深度"],
}


def stream(path):
    out = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        st, call = None, None
        if "current_state" in line:
            t = line.replace('\\"', '"')
            i = t.find('{"current_state":{')
            while i != -1:
                try:
                    obj, _ = DEC.raw_decode(t[i:])
                except Exception:
                    obj = None
                if isinstance(obj, dict) and "current_state" in obj:
                    st = obj
                i = t.find('{"current_state":{', i + 1)
        if o.get("kind") == "tool_call":
            js = json.dumps(o, ensure_ascii=False)
            if "take_action" in js:
                a = re.search(r'"arguments": "((?:[^"\\]|\\.)*)"', js)
                if a:
                    raw = a.group(1)
                    args = None
                    for attempt in (lambda: json.loads('"' + raw + '"'),
                                    lambda: json.loads(raw.replace('\\"', '"'))):
                        try:
                            args = attempt()
                            break
                        except Exception:
                            continue
                    if args is None:
                        continue
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            continue
                    if not isinstance(args, dict):
                        continue
                    call = (args.get("choice"), args.get("notes") or "")
        out.append((o.get("seq"), o.get("kind"), st, call))
    return out


def status(st):
    s = st["current_state"]["status"]
    return tuple(s.get(k) for k in KEYS), s.get("level"), st["current_state"]["time"].get("current_month")


def fam_of(desc):
    hit = []
    for name, kws in FAM.items():
        if any(k in desc for k in kws):
            hit.append(name)
    return hit


def main():
    obs = []          # (run, month, title, choice, desc, delta_dict, phase)
    node_opts = defaultdict(dict)   # title -> choice_idx -> list of delta_dict
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        rows = stream(pathlib.Path(p))
        last = None          # (status_tuple, month, choices, title)
        pending = None       # (choice, notes)
        pending_prev = None
        for seq, kind, st, call in rows:
            if st is not None:
                cur = status(st)
                if last is None:
                    last = (cur[0], cur[2], st.get("choices") or [], (st.get("current_event") or {}).get("title", ""))
                    continue
                if cur[0] == last[0]:
                    continue                      # 重复渲染
                if pending is not None and pending_prev is not None:
                    d = {}
                    for k, a, b in zip(KEYS, last[0], cur[0]):
                        if a is not None and b is not None and a != b:
                            d[k] = b - a
                    ch, notes = pending
                    desc = ""
                    for c in (last[2] or []):
                        if c.get("choice") == ch:
                            desc = str(c.get("description") or c.get("action") or "")
                    obs.append(dict(run=rd, month=last[1], title=last[3], choice=ch,
                                    desc=desc, notes=notes, d=d, phase=(last[1] or 0) % 6))
                    node_opts[last[3]][ch] = node_opts[last[3]].get(ch, []) + [d]
                last = (cur[0], cur[2], st.get("choices") or [], (st.get("current_event") or {}).get("title", ""))
                pending = None
                continue
            if kind == "tool_call" and call:
                if call == pending:
                    continue
                pending_prev = pending
                pending = call

    print(f"=== 已配对「选项 → 真实 Δ」样本 {len(obs)} 条 ===")
    print("   月度分布 Top10:", Counter(o["month"] for o in obs).most_common(10))

    # ---------- T1 ----------
    print("\n【T1】负向语义族：命中 vs 未命中（全量）")
    g = defaultdict(list)
    for o in obs:
        if not o["desc"]:
            continue
        f = fam_of(o["desc"])
        key = "+".join(f) if f else "未命中"
        g[key].append(o["d"])
    for key in sorted(g, key=lambda k: -len(g[k])):
        v = g[key]
        dn = [x.get("network", 0) for x in v]
        do = [x.get("output", 0) for x in v]
        print(f"    {key:<14} n={len(v):<5} ΔN 均 {statistics.mean(dn):+.2f}  "
              f"ΔO 均 {statistics.mean(do):+.2f}  "
              f"P(ΔN<0)={sum(1 for x in dn if x<0)/len(dn)*100:4.0f}%  "
              f"P(ΔO<0)={sum(1 for x in do if x<0)/len(do)*100:4.0f}%")

    # ---------- T2 ----------
    print("\n【T2】分相位：暴露窗（month%6==5）")
    for ph in (5,):
        sub = [o for o in obs if o["phase"] == ph and o["desc"]]
        print(f"    month%6==5  n={len(sub)}")
        g2 = defaultdict(list)
        for o in sub:
            f = fam_of(o["desc"])
            g2["+".join(f) if f else "未命中"].append(o["d"])
        for key in sorted(g2, key=lambda k: -len(g2[k])):
            v = g2[key]
            dn = [x.get("network", 0) for x in v]
            do = [x.get("output", 0) for x in v]
            print(f"      {key:<14} n={len(v):<4} ΔN 均 {statistics.mean(dn):+.2f}  ΔO 均 {statistics.mean(do):+.2f}")

    # ---------- T3 ----------
    print("\n【T3】★ 同题异选（同一事件节点被 ≥2 种选项选过）——天然反事实对照")
    hits = 0
    for title, chmap in sorted(node_opts.items(), key=lambda kv: -sum(len(v) for v in kv[1].values())):
        if len(chmap) < 2:
            continue
        tot = sum(len(v) for v in chmap.values())
        if tot < 6:
            continue
        parts = []
        for ch in sorted(chmap, key=lambda c: (c is None, c)):
            v = chmap[ch]
            if len(v) < 2:
                continue
            dn = statistics.mean(x.get("network", 0) for x in v)
            do = statistics.mean(x.get("output", 0) for x in v)
            ds = statistics.mean(x.get("skill", 0) for x in v)
            parts.append(f"c{ch}(n={len(v)}): ΔN{dn:+.1f} ΔO{do:+.1f} ΔS{ds:+.1f}")
        if len(parts) >= 2:
            hits += 1
            print(f"    {title[:30]:<32} {' | '.join(parts)}")
        if hits >= 14:
            break

    # ---------- T4 ----------
    print("\n【T4】★ 每个 M5 节点的选项集中，是否存在「实测 ΔN≥0 且 ΔO≥0」的选项")
    m5nodes = defaultdict(dict)
    for o in obs:
        if o["phase"] != 5 or o["choice"] is None:
            continue
        m5nodes[o["title"]][o["choice"]] = o["d"]
    safe_nodes = total_nodes = 0
    node_rows = []
    for title, chmap in m5nodes.items():
        total_nodes += 1
        safe = [ch for ch, d in chmap.items() if d.get("network", 0) >= 0 and d.get("output", 0) >= 0]
        if safe:
            safe_nodes += 1
        node_rows.append((title, len(chmap), len(safe)))
    print(f"    覆盖 M5 节点 {total_nodes} 个；其中存在安全选项的 {safe_nodes} 个"
          f" = {safe_nodes/max(total_nodes,1)*100:.0f}%")
    for t, n, s in sorted(node_rows, key=lambda x: (x[2] == 0, -x[1]))[:14]:
        print(f"      {t[:34]:<36} 已观测选项 {n} 个，其中安全 {s} 个")

    # ---------- T5 ----------
    print("\n【T5】被排除两组的「其它维」代价（排除它们是否吃亏）")
    for name, kws in FAM.items():
        hi = [o["d"] for o in obs if o["desc"] and any(k in o["desc"] for k in kws)]
        lo = [o["d"] for o in obs if o["desc"] and not any(k in o["desc"] for k in kws)]
        if not hi:
            continue
        def m(v, k):
            return statistics.mean(x.get(k, 0) for x in v)
        print(f"    {name}  n={len(hi)}（对照 n={len(lo)}）")
        for k in ("network", "output", "skill", "dignity", "health"):
            print(f"         Δ{k:<8} 命中 {m(hi,k):+.2f}   未命中 {m(lo,k):+.2f}   差 {m(hi,k)-m(lo,k):+.2f}")


if __name__ == "__main__":
    main()
