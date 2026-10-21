#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★ 权威口径复算（唯一真相源）：M6 晋级的决定因素 + 「最后一击」影响。
输出全部用于报告，所有数字只从这里取。
"""
import json, glob, re, pathlib
from collections import Counter, defaultdict

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
AB = pathlib.Path("analysis/ab")
DEC = json.JSONDecoder()
KEY3 = ("skill", "output", "network")
TH1 = (8, 3, 3)
PROMO = re.compile(r"晋升通知")
OSC = re.compile(r"升迁节奏过快")


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
                    try:
                        call = json.loads(a.group(1).replace('\\"', '"'))
                    except Exception:
                        call = {}
        out.append((o.get("seq"), o.get("kind"), st, call))
    return out


def ok(s, th):
    return all((s.get(k) or 0) >= t for k, t in zip(KEY3, th))


def main():
    rows = []
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        st = stream(pathlib.Path(p))
        snaps = [(i, s) for i, (sq, k, s, c) in enumerate(st) if s]
        rev = base = None
        for i, s in snaps:
            if s["current_state"]["time"].get("current_month") == 6 and "【半年谈话】" in (s.get("events") or ""):
                rev = (i, s)
                break
        if rev is None:
            continue
        ri, rst = rev
        for i, s in snaps:
            if i >= ri:
                break
            if s["current_state"]["time"].get("current_month") == 5:
                base = (i, s)
        if base is None:
            continue
        bi, bst = base
        b, r = bst["current_state"]["status"], rst["current_state"]["status"]
        ev = rst.get("events") or ""
        # 中间未渲染动作
        seen, mc = set(), []
        for j in range(bi, ri):
            sq, k, s, c = st[j]
            if k == "tool_call" and c:
                key = (c.get("choice"), c.get("notes"))
                if key not in seen:
                    seen.add(key)
                    mc.append(c)
        rows.append(dict(rd=rd, b=b, r=r, promo=bool(PROMO.search(ev)),
                         prev_ok=ok(b, TH1), now_ok=ok(r, TH1), mc=mc))

    N = len(rows)
    print(f"=== M6 有评审快照的局数 = {N} ===")
    P = [x for x in rows if x["promo"]]
    NP = [x for x in rows if not x["promo"]]
    print(f"晋级 {len(P)} / 未晋级 {len(NP)}")

    print("\n【A】评审快照三维合取 ⟺ 晋级")
    tp = sum(1 for x in rows if x["now_ok"] and x["promo"])
    fn = sum(1 for x in rows if x["now_ok"] and not x["promo"])
    fp = sum(1 for x in rows if not x["now_ok"] and x["promo"])
    tn = sum(1 for x in rows if not x["now_ok"] and not x["promo"])
    print(f"    达标且晋级 {tp} / 达标未晋 {fn} / 不达标却晋 {fp} / 不达标未晋 {tn}"
          f"  ⇒ 准确率 {(tp+tn)/N*100:.1f}%")

    print("\n【B】M5 月末快照三维合取 ⟺ 晋级（可观测口径）")
    tp2 = sum(1 for x in rows if x["prev_ok"] and x["promo"])
    fn2 = sum(1 for x in rows if x["prev_ok"] and not x["promo"])
    fp2 = sum(1 for x in rows if not x["prev_ok"] and x["promo"])
    tn2 = sum(1 for x in rows if not x["prev_ok"] and not x["promo"])
    print(f"    达标且晋级 {tp2} / 达标未晋 {fn2} / 不达标却晋 {fp2} / 不达标未晋 {tn2}"
          f"  ⇒ 准确率 {(tp2+tn2)/N*100:.1f}%")
    print(f"    ⇒ 「最后一击」翻坏 {fn2} 局（{fn2/N*100:.0f}%）、翻好 {fp2} 局")

    print("\n【C】未晋级局的缺口分解（以评审快照为准）")
    dec = Counter()
    for x in NP:
        miss = [k for k, t in zip(KEY3, TH1) if (x["r"].get(k) or 0) < t]
        dec["+".join(miss) or "(无缺口)"] += 1
    for k, v in dec.most_common():
        print(f"    {k:<18} {v} 局")

    print("\n【D】L1 的 CAP 与门槛（零余量的证据）")
    print("    CAP(L1) = floor(TH×1.2) = skill int(8×1.2)=9 / output int(3×1.2)=3 / network int(3×1.2)=3")
    print("    TH(L2)  =                8 / 3 / 3")
    print("    ⇒ 截断余量 = +1 / +0 / +0   ★ output 与 network 余量恒为 0")
    caps = Counter((x["b"].get("skill"), x["b"].get("output"), x["b"].get("network")) for x in rows)
    print(f"    M5 月末 (S,O,N) 组合 Top5: {caps.most_common(5)}")

    print("\n【E】未渲染动作条数")
    print("   ", Counter(len(x["mc"]) for x in rows).most_common())

    print("\n【F】13 局「翻坏」清单（供报告引用）")
    bad = [x for x in rows if x["prev_ok"] and not x["now_ok"]]
    for x in bad:
        note = x["mc"][0].get("notes", "") if x["mc"] else "(无)"
        print(f"    {x['rd']}  S{x['b']['skill']} O{x['b']['output']} N{x['b']['network']}"
              f" → S{x['r']['skill']} O{x['r']['output']} N{x['r']['network']}   c{x['mc'][0].get('choice') if x['mc'] else '-'}")
        print(f"        {note[:88]}")

    # 升迁震荡
    print("\n【G】升迁震荡（全量 186 次晋级事件）")
    g = defaultdict(lambda: [0, 0])
    nfirst = nfirstosc = 0
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        st = stream(pathlib.Path(p))
        evs = {}
        for sq, k, s, c in st:
            if not s:
                continue
            ev = s.get("events") or ""
            if "【半年谈话】" not in ev:
                continue
            evs.setdefault(s["current_state"]["time"].get("current_month"), ev)
        last = None
        for mo in sorted(evs):
            if not PROMO.search(evs[mo]):
                continue
            o = bool(OSC.search(evs[mo]))
            if last is None:
                nfirst += 1
                nfirstosc += 1 if o else 0
            else:
                g[mo - last][0] += 1
                g[mo - last][1] += 1 if o else 0
            last = mo
    print(f"    首次晋级（无上次）: n={nfirst}  震荡={nfirstosc} = {nfirstosc/max(nfirst,1)*100:.0f}%")
    for k in sorted(g):
        a, b2 = g[k]
        print(f"    间隔 {k} 个月: {b2}/{a} = {b2/a*100:.0f}%")
    lt = sum(b2 for k, (a, b2) in g.items() if k < 12)
    ltn = sum(a for k, (a, b2) in g.items() if k < 12)
    ge = sum(b2 for k, (a, b2) in g.items() if k >= 12)
    gen = sum(a for k, (a, b2) in g.items() if k >= 12)
    print(f"    ★ 间隔 <12 月: {lt}/{ltn} = {lt/ltn*100:.0f}%    间隔 ≥12 月: {ge}/{gen} = {ge/max(gen,1)*100:.0f}%")


if __name__ == "__main__":
    main()
