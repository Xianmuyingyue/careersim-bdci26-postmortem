#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★ 「评审前最后一击」全评审月普查。

机制（已在 M5→M6 上确证）：
  每个月的**最后一个动作**与「月推进」在同一帧结算 ⇒ 该动作的隐藏效果**首次可见**就是
  下一个月的快照。若下个月恰好是评审月，这个效果就直接落在评审读到的状态上。

本脚本对 M6/M12/M18/M24/M30/M36/M42/M48 逐个月统计：
  · 评审快照 vs 上一月最后快照的 Δ 分布
  · 中间「未渲染动作」的条数与措辞
  · 有多少局因此发生「达标 → 不达标」翻转
"""
import json, glob, re
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
_DEC = json.JSONDecoder()
KEY3 = ("skill", "output", "network")
REVIEWS = [6, 12, 18, 24, 30, 36, 42, 48]
TH = {"L1": (8, 3, 3), "L2": (18, 5, 6), "L3": (35, 14, 18),
      "L4": (60, 20, 30), "L5": (87, 32, 45), "L6": (114, 45, 60), "L7": (140, 60, 80)}


def parse_stream(path):
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        seq, kind = o.get("seq"), o.get("kind")
        st, call = None, None
        if "current_state" in line:
            s = line.replace('\\"', '"')
            i = s.find('{"current_state":{')
            if i != -1:
                try:
                    obj, _ = _DEC.raw_decode(s[i:])
                    if isinstance(obj, dict) and "current_state" in obj:
                        st = (obj["current_state"], obj.get("events") or "",
                              (obj.get("current_event") or {}).get("title", ""))
                except Exception:
                    pass
        if kind == "tool_call":
            js = json.dumps(o, ensure_ascii=False)
            if "take_action" in js:
                a = re.search(r'"arguments": "((?:[^"\\]|\\.)*)"', js)
                if a:
                    try:
                        call = json.loads(a.group(1).replace('\\"', '"'))
                    except Exception:
                        call = {}
        out.append((seq, kind, st, call))
    return out


def lvnum(lv):
    m = re.search(r"(\d+)", str(lv or ""))
    return int(m.group(1)) if m else None


def main():
    paths = sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl"))
    allrows = []
    for p in paths:
        rd = Path(p).parent.name
        stream = parse_stream(Path(p))
        snaps = [(i, s) for i, (sq, k, s, c) in enumerate(stream) if s]
        for M in REVIEWS:
            rev = None
            for i, s in snaps:
                st, ev, title = s
                if st["time"].get("current_month") == M and "【半年谈话】" in ev:
                    rev = (i, s)
                    break
            if rev is None:
                continue
            ri, (rst, rev_ev, _) = rev
            base = None
            for i, s in snaps:
                if i >= ri:
                    break
                if s[0]["time"].get("current_month") == M - 1:
                    base = (i, s)
            if base is None:
                continue
            bi, (bst, _, _) = base
            seenm, mc = set(), []
            for j in range(bi, ri):
                sq, k, s, c = stream[j]
                if k == "tool_call" and c:
                    key = (c.get("choice"), c.get("notes"))
                    if key not in seenm:
                        seenm.add(key)
                        mc.append((sq, c))
            d = {}
            for k in KEY3:
                va, vb = bst["status"].get(k), rst["status"].get(k)
                if va is not None and vb is not None and va != vb:
                    d[k] = vb - va
            lv = bst["status"].get("level")
            th = TH.get(lv if isinstance(lv, str) else f"L{lvnum(lv)}") or TH["L1"]
            prev_ok = all((bst["status"].get(k) or 0) >= t for k, t in zip(KEY3, th))
            now_ok = all((rst["status"].get(k) or 0) >= t for k, t in zip(KEY3, th))
            promo = bool(re.search(r"晋升通知", rev_ev))
            allrows.append(dict(rd=rd, M=M, d=d, mc=mc, prev_ok=prev_ok, now_ok=now_ok,
                                promo=promo, lv=lv, th=th, bS=bst["status"], rS=rst["status"]))

    print("=== 评审快照总数", len(allrows), "===\n")
    print("【A】各评审月：Δ 分布 / 未渲染动作数")
    for M in REVIEWS:
        rs = [r for r in allrows if r["M"] == M]
        if not rs:
            continue
        c = Counter(tuple(sorted(r["d"].items())) for r in rs)
        ncalls = Counter(len(r["mc"]) for r in rs)
        print(f"\nM{M}  (n={len(rs)})  未渲染动作数分布 {ncalls.most_common()}")
        for k, v in c.most_common(5):
            print(f"     {v:>4}  {dict(k) if k else '{}'}")

    print("\n\n【B】★ 因「最后一击」发生『达标 → 不达标』翻转的局")
    flip_bad = [r for r in allrows if r["prev_ok"] and not r["now_ok"]]
    flip_good = [r for r in allrows if not r["prev_ok"] and r["now_ok"]]
    print(f"\n  翻坏的局: {len(flip_bad)}   翻好的局: {len(flip_good)}")
    for r in flip_bad:
        notes = " || ".join(f"c{c.get('choice')}:{(c.get('notes') or '')[:60]}" for _, c in r["mc"]) or "(无未渲染动作)"
        print(f"    M{r['M']:<3}{r['rd']:<22} {r['lv']} Δ{ {k:v for k,v in r['d'].items()} }  promo={r['promo']}")
        print(f"         {notes}")
    print("\n  --- 翻好的局 ---")
    for r in flip_good:
        notes = " || ".join(f"c{c.get('choice')}:{(c.get('notes') or '')[:60]}" for _, c in r["mc"]) or "(无未渲染动作)"
        print(f"    M{r['M']:<3}{r['rd']:<22} {r['lv']} Δ{ {k:v for k,v in r['d'].items()} }  promo={r['promo']}")
        print(f"         {notes}")

    print("\n\n【C】M6 晋级：缺口按维分解（以评审快照为准）")
    m6 = [r for r in allrows if r["M"] == 6]
    dec = Counter()
    for r in m6:
        if r["promo"]:
            continue
        miss = []
        for k, t in zip(KEY3, r["th"]):
            if (r["rS"].get(k) or 0) < t:
                miss.append(k)
        dec["+".join(miss) or "(无缺口却未晋级)"] += 1
    for k, v in dec.most_common():
        print(f"    {k:<18} {v} 局")

    print("\n【D】全部评审月：『达标 ⟺ 晋级』命中率（以评审快照为准）")
    hit = sum(1 for r in allrows if r["promo"] == r["now_ok"])
    print(f"    {hit}/{len(allrows)} = {hit/len(allrows)*100:.1f}%")
    print("\n【E】全部评审月：『上一月末达标 ⟺ 晋级』命中率（用可观测的月末状态预测）")
    hit2 = sum(1 for r in allrows if r["promo"] == r["prev_ok"])
    print(f"    {hit2}/{len(allrows)} = {hit2/len(allrows)*100:.1f}%")


if __name__ == "__main__":
    main()
