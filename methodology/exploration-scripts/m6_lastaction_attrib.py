#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★ 核心：解释 M6 评审点为何 ≠ M5 月末状态。

机制假设（已在 20260924T161605Z 上验证）：
  「月推进」与「当月最后一个动作的效果」在同一帧结算 ⇒ 该动作的效果**首次可见**
  就是在评审快照里。若它扣 N/O，就把一个本来达标的局面推到达标线以下。

做法：对每一局，找出
  · 最后一次 M5 快照（基线状态）
  · 评审快照（M6）
  · 两者之间发生的 take_action 调用（"未渲染动作"）
然后看 Δ 与这些动作的对应关系。
"""
import json, glob, re
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
_DEC = json.JSONDecoder()
KEY3 = ("skill", "output", "network")
TH = dict(skill=8, output=3, network=3)


def parse_stream(path):
    """返回按出现顺序的事件列表：(seq, kind, state_dict|None, call_info|None)"""
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        seq, kind = o.get("seq"), o.get("kind")
        st = None
        call = None
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
                        args = json.loads(a.group(1).replace('\\"', '"'))
                    except Exception:
                        args = {}
                    call = args
        out.append((seq, kind, st, call))
    return out


def main():
    paths = sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl"))
    rows = []
    for p in paths:
        rd = Path(p).parent.name
        stream = parse_stream(Path(p))
        # 所有快照（按序）带索引
        snaps = [(i, s) for i, (sq, k, s, c) in enumerate(stream) if s]
        # 评审快照（M6 + 半年谈话）
        rev = None
        for i, s in snaps:
            st, ev, title = s
            if st["time"].get("current_month") == 6 and "【半年谈话】" in ev:
                rev = (i, s)
                break
        if rev is None:
            continue
        ri, (rst, rev_ev, _) = rev
        # 最后一次 M5 快照（在评审之前）
        base = None
        for i, s in snaps:
            if i >= ri:
                break
            if s[0]["time"].get("current_month") == 5:
                base = (i, s)
        if base is None:
            continue
        bi, (bst, _, btitle) = base

        # 中间发生的 take_action
        mid_calls = []
        for j in range(bi, ri):
            sq, k, s, c = stream[j]
            if k == "tool_call" and c:
                mid_calls.append((sq, c))
        # 去重（同一 call 出现两次）
        seenm, mc = set(), []
        for sq, c in mid_calls:
            key = (c.get("choice"), c.get("notes"))
            if key in seenm:
                continue
            seenm.add(key)
            mc.append((sq, c))

        d = {}
        for k in KEY3:
            va, vb = bst["status"].get(k), rst["status"].get(k)
            if va is not None and vb is not None:
                d[k] = vb - va

        prev_ok = all((bst["status"].get(k) or 0) >= TH[k] for k in KEY3)
        now_ok = all((rst["status"].get(k) or 0) >= TH[k] for k in KEY3)
        promo = bool(re.search(r"晋升通知", rev_ev))
        rows.append(dict(rd=rd, d=d, mc=mc, prev_ok=prev_ok, now_ok=now_ok, promo=promo,
                         bS=bst["status"], rS=rst["status"], btitle=btitle))

    print(f"=== 可分析局数 {len(rows)} ===")
    # 1) delta 分布
    print("\n【1】M5末快照 → M6评审快照 的 Δ 分布")
    c = Counter(tuple(sorted(r["d"].items())) for r in rows)
    for k, v in c.most_common():
        print(f"    {v:>4}  {dict(k) if k else '{}'}")

    # 2) 未渲染动作数
    print("\n【2】中间发生的「未渲染 take_action」条数")
    print("   ", Counter(len(r["mc"]) for r in rows).most_common())

    # 3) Δnetwork 与 未渲染动作 的对应
    print("\n【3】Δnetwork ≠ 0 的局：其未渲染动作（notes）")
    n0 = 0
    for r in rows:
        dn = r["d"].get("network", 0)
        if dn == 0:
            continue
        n0 += 1
        notes = " || ".join(f"c{c.get('choice')}:{c.get('notes','')[:70]}" for _, c in r["mc"])
        print(f"    {r['rd']:<22} ΔN={dn:+d}  ΔO={r['d'].get('output',0):+d}  ΔS={r['d'].get('skill',0):+d}")
        print(f"        {notes}")
    print(f"    （共 {n0} 局 Δnetwork≠0）")

    # 4) 翻转矩阵 + 预测力
    print("\n【4】以 M5 末快照预测 M6 晋级")
    tp = sum(1 for r in rows if r["prev_ok"] and r["promo"])
    fn = sum(1 for r in rows if r["prev_ok"] and not r["promo"])
    fp = sum(1 for r in rows if not r["prev_ok"] and r["promo"])
    tn = sum(1 for r in rows if not r["prev_ok"] and not r["promo"])
    print(f"    M5末达标 且 晋级 : {tp}")
    print(f"    M5末达标 但 未晋 : {fn}   ← 被最后动作翻盘")
    print(f"    M5末不达标 却 晋 : {fp}")
    print(f"    M5末不达标 未晋   : {tn}")
    print(f"    准确率 = {(tp+tn)/len(rows)*100:.1f}%")
    print("\n    以 M6 评审快照预测 M6 晋级")
    tp2 = sum(1 for r in rows if r["now_ok"] and r["promo"])
    fn2 = sum(1 for r in rows if r["now_ok"] and not r["promo"])
    fp2 = sum(1 for r in rows if not r["now_ok"] and r["promo"])
    tn2 = sum(1 for r in rows if not r["now_ok"] and not r["promo"])
    print(f"    达标且晋级 {tp2} / 达标未晋 {fn2} / 不达标却晋级 {fp2} / 不达标未晋 {tn2}"
          f"  ⇒ 准确率 {(tp2+tn2)/len(rows)*100:.1f}%")

    # 5) 余量分析：M6 评审点各维余量 → 晋级率
    print("\n【5】M6 评审点「余量」→ 晋级率（余量 = 实际 − 门槛）")
    for k in KEY3:
        g = defaultdict(lambda: [0, 0])
        for r in rows:
            marg = (r["rS"].get(k) or 0) - TH[k]
            marg = min(marg, 3)
            g[marg][0] += 1
            g[marg][1] += 1 if r["promo"] else 0
        s = "   ".join(f"余量{'+' if m>0 else ''}{m}: {a}/{b}" for m, (a, b) in sorted(g.items()))
        print(f"    {k:<9} {s}")

    # 6) 双维联合余量
    print("\n【6】M6 评审点 min(N余量, O余量) → 晋级率")
    g = defaultdict(lambda: [0, 0])
    for r in rows:
        m = min((r["rS"].get("network") or 0) - 3, (r["rS"].get("output") or 0) - 3)
        m = max(min(m, 3), -3)
        g[m][0] += 1
        g[m][1] += 1 if r["promo"] else 0
    for m, (a, b) in sorted(g.items()):
        print(f"    min余量 {m:+d}: {b}/{a} = {b/max(a,1)*100:.0f}%")


if __name__ == "__main__":
    main()
