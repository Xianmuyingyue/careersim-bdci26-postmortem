#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
month_walkthrough.py —— 逐月列出「事件标题 / 选项 / Agent 理由」，定位关键分歧。

用法：
  python3 analysis/month_walkthrough.py <run_id> [起月] [止月]

由于 observe 与 take_action 在同一回合成对出现，本脚本按 seq 顺序配对，
复原「这个月发生了什么、Agent 为什么这么选」。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")


def unesc(s: str) -> str:
    try:
        return s.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    except Exception:
        return s


def objs(run: str):
    d = os.path.join(OUT, run)
    fs = [f for f in os.listdir(d) if f.startswith("events-")]
    with open(os.path.join(d, fs[0]), encoding="utf-8") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:
                continue


def cut_json(s: str) -> str:
    i = s.find('{"current_state"')
    if i < 0:
        return ""
    depth, j = 0, -1
    for k in range(i, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                j = k
                break
    return s[i:j + 1] if j > 0 else ""


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else "20260927T042353Z"
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 48

    # observe 与 take_action 各有独立 tool_call_id，必须**按 seq 顺序配对**：
    # 每个 observe 后面遇到的第一条 take_action 就是它对应当回合的选择。
    events = []
    for o in objs(run):
        pay = o.get("payload") or {}
        k = o.get("kind")
        if k == "tool_result" and "observe" in str(pay.get("tool_name", "")):
            raw = pay.get("result") or ""
            body = cut_json(unesc(raw))
            if not body:
                continue
            try:
                j = json.loads(body)
            except Exception:
                continue
            cs = j.get("current_state") or {}
            events.append(("obs", o.get("seq"), {
                "month": (cs.get("time") or {}).get("current_month"),
                "st": cs.get("status") or {},
                "event": (j.get("current_event") or {}).get("title", ""),
                "nchoices": len(j.get("choices") or []),
                "choices": [(c.get("choice"), c.get("action")) for c in (j.get("choices") or [])],
            }))
        elif k == "tool_call":
            tc = (pay.get("tool_call")
                  or (pay.get("delta") or {}).get("tool_call") or {})
            if "take_action" not in str(tc.get("name", "")):
                continue
            try:
                a = json.loads(tc.get("arguments") or "{}")
            except Exception:
                a = {}
            events.append(("act", o.get("seq"), (a.get("choice"), a.get("notes", ""))))

    events.sort(key=lambda x: x[1])
    rows, pend = [], None
    for kind, seq, dat in events:
        if kind == "obs":
            if pend is not None:
                rows.append((pend[0], pend[1], None))
            pend = (seq, dat)
        else:
            if pend is not None:
                rows.append((pend[0], pend[1], dat))
                pend = None
    if pend is not None:
        rows.append((pend[0], pend[1], None))

    for seq, st, actd in rows:
        mo = st["month"]
        if mo is None or mo < lo or mo > hi:
            continue
        s = st["st"]
        choice, notes = (actd if actd else (None, "（未找到对应动作）"))
        print(f"[seq {seq:>5}] M{mo:<3} "
              f"S{s.get('skill')} O{s.get('output')} N{s.get('network')} "
              f"D{s.get('dignity')} H{s.get('health')} E{s.get('energy')} "
              f"{s.get('level')}")
        print(f"    事件: {st['event'][:60]}   选项数={st['nchoices']}")
        for cnum, ctxt in st["choices"][:8]:
            mark = " ★选了" if cnum == choice else ""
            print(f"      {cnum}. {str(ctxt)[:70]}{mark}")
        print(f"    理由: {notes[:260]}")
        print()


if __name__ == "__main__":
    main()
