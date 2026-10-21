#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
★ 暴露窗「最后一击」选项对照表。

对 M6 评审前最后一个动作：列出【完整选项单】+【实际被选】+【真实 Δ】。
目的：找出「语义承诺补 N/O、实际却扣 N/O」的选项族，写成可操作的负面清单。
"""
import json, glob, re, pathlib
from collections import Counter

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
DEC = json.JSONDecoder()


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


def main():
    print("=" * 78)
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
        prev_ok = b["skill"] >= 8 and b["output"] >= 3 and b["network"] >= 3
        now_ok = r["skill"] >= 8 and r["output"] >= 3 and r["network"] >= 3
        if not (prev_ok and not now_ok):
            continue
        # 找 base 的选项单与选中项
        chosen = None
        for j in range(bi, ri):
            sq, k, s, c = st[j]
            if k == "tool_call" and c:
                chosen = (sq, c)
        choices = bst.get("choices") or []
        title = (bst.get("current_event") or {}).get("title", "")
        print(f"\n■ {rd}   M5末 S{b['skill']} O{b['output']} N{b['network']} → 评审 S{r['skill']} O{r['output']} N{r['network']}")
        print(f"   事件：{title}")
        for ch in choices:
            idx = ch.get("choice")
            mark = "  ◀ 选中" if chosen and chosen[1].get("choice") == idx else ""
            desc = (ch.get("description") or ch.get("action") or "")
            print(f"     [{idx}] {str(desc)[:95]}{mark}")
        if chosen:
            print(f"   笔记：{chosen[1].get('notes','')}")


if __name__ == "__main__":
    main()
