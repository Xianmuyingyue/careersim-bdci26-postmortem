#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★「升迁震荡」触发条件普查。

评审文案里若带「升迁节奏过快…协作摩擦上升，办公室侧目增多」，
则晋升后会额外施加 network −3 / dignity −1（实测）。本脚本找它的触发条件。

候选自变量：
  · 晋级前在本级已待的任期（dur）——「节奏过快」的最直接读法
  · 距上一次晋级的月数
  · 职级 / 评审月
  · 是否有其它文案（爆雷、谈话差评）
"""
import json, glob, re, pathlib
from collections import Counter, defaultdict

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
DEC = json.JSONDecoder()
OSC = re.compile(r"升迁节奏过快")
PROMO = re.compile(r"晋升通知：.*?您已从 (L\d) 晋升至 (L\d)")


def stream_states(path):
    seq = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if "current_state" not in line:
            continue
        t = line.replace('\\"', '"')
        i = t.find('{"current_state":{')
        while i != -1:
            try:
                obj, _ = DEC.raw_decode(t[i:])
            except Exception:
                obj = None
            if isinstance(obj, dict) and "current_state" in obj:
                seq.append(obj)
            i = t.find('{"current_state":{', i + 1)
    return seq


def main():
    promos = []
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        seq = stream_states(p)
        seen = set()
        rows = []
        for obj in seq:
            st = obj["current_state"]
            ev = obj.get("events") or ""
            mo = st["time"].get("current_month")
            if "【半年谈话】" not in ev:
                continue
            key = (mo, ev)
            if key in seen:
                continue
            seen.add(key)
            rows.append((mo, st["status"].get("level"), st["status"].get("duration_in_level"), ev))
        # 沿着评审序列追晋级
        prev_lvl = None
        last_promo_month = None
        for mo, lv, dur, ev in rows:
            m = PROMO.search(ev)
            if m:
                osc = bool(OSC.search(ev))
                promos.append(dict(rd=rd, month=mo, frm=m.group(1), to=m.group(2),
                                   osc=osc, dur_at_review=dur,
                                   gap=(mo - last_promo_month) if last_promo_month else None))
                last_promo_month = mo

    print(f"总晋级事件 {len(promos)}；其中带「升迁节奏过快」{sum(p['osc'] for p in promos)}\n")

    print("【1】震荡 × 评审月")
    g = defaultdict(lambda: [0, 0])
    for p in promos:
        g[p["month"]][0] += 1
        g[p["month"]][1] += 1 if p["osc"] else 0
    for m in sorted(g):
        a, b = g[m]
        print(f"    M{m:<3} {b}/{a} = {b/a*100:>3.0f}%")

    print("\n【2】震荡 × 晋级前「距上次晋级的月数(gap)」")
    g = defaultdict(lambda: [0, 0])
    for p in promos:
        g[p["gap"]][0] += 1
        g[p["gap"]][1] += 1 if p["osc"] else 0
    for k in sorted(g, key=lambda x: (x is None, x)):
        a, b = g[k]
        print(f"    gap={str(k):<5} {b}/{a} = {b/a*100:>3.0f}%")

    print("\n【3】震荡 × 晋级后到达的职级")
    g = defaultdict(lambda: [0, 0])
    for p in promos:
        g[p["to"]][0] += 1
        g[p["to"]][1] += 1 if p["osc"] else 0
    for k in sorted(g):
        a, b = g[k]
        print(f"    → {k:<4} {b}/{a} = {b/a*100:>3.0f}%")

    print("\n【4】同局内：震荡是否在多次晋级间交替（抽 4 局看模式）")
    byrun = defaultdict(list)
    for p in promos:
        byrun[p["rd"]].append(p)
    for rd in list(byrun)[:6]:
        seqs = " ".join(f"M{p['month']}:{p['frm']}→{p['to']}{'★震荡' if p['osc'] else ''}" for p in byrun[rd])
        print(f"    {rd:<22} {seqs}")

    print("\n【5】gap=6（每次都踩着第一个窗口晋级）的局，震荡比例")
    g6 = [p for p in promos if p["gap"] == 6]
    print(f"    n={len(g6)}  震荡 {sum(p['osc'] for p in g6)} = {sum(p['osc'] for p in g6)/max(len(g6),1)*100:.0f}%")
    ggt = [p for p in promos if p["gap"] and p["gap"] > 6]
    print(f"    gap>6        n={len(ggt)}  震荡 {sum(p['osc'] for p in ggt)} = {sum(p['osc'] for p in ggt)/max(len(ggt),1)*100:.0f}%")

    print("\n【6】震荡的实际属性代价（相邻评审快照差分，只取有震荡的段）")
    # 用快照差分
    diffs = []
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        seq = stream_states(p)
        prev = None
        for obj in seq:
            st = obj["current_state"]
            ev = obj.get("events") or ""
            if "【半年谈话】" not in ev:
                continue
            if OSC.search(ev) and PROMO.search(ev):
                if prev:
                    d = {}
                    for k in ("skill", "output", "network", "dignity", "health"):
                        va, vb = prev["status"].get(k), st["status"].get(k)
                        if va is not None and vb is not None and va != vb:
                            d[k] = vb - va
                    diffs.append(d)
                break
            prev = st
    agg = Counter()
    for d in diffs:
        agg[tuple(sorted(d.items()))] += 1
    for k, v in agg.most_common(8):
        print(f"    {v:>4}  {dict(k)}")


if __name__ == "__main__":
    main()
