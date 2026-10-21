#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
level_timeline.py —— 还原「职级 / 三维 / 月」时间线，并对照技能里的 CAP 表。

关键事实（本会话实测）：observe 返回的 status 只有 9 个键
（health/dignity/skill/network/level/duration_in_level/output/wealth/energy）
—— **没有 CAP**。CAP 只写在 SKILL 里，是 Agent 必须自己查表的东西。

⇒ 若 Agent 的职级跳了但没刷新 CAP 表，它会把「L2 状态」误判成「L1 顶格」，
  进而触发铁律 10（L1 锁定晋升优先模式）⇒ 主行动改选「低调避险」（零补量）。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

# 技能里的 CAP 表（四级，用于对照；来源见 situation-awareness §5.9）
CAP = {"L1": {"skill": 9, "output": 3, "network": 3},
       "L2": {"skill": 21, "output": 6, "network": 6},
       "L3": {"skill": 36, "output": 10, "network": 12},
       "L4": {"skill": 68, "output": 26, "network": 36},
       "L5": {"skill": 90, "output": 32, "network": 45}}

TARGETS = [("v10e/run2 (D 31.56 / 24月 / 炒鱿鱼)", "20260927T042353Z"),
           ("v10e/run1 (C 53.02 / 48月 / L4)", "20260927T032531Z"),
           ("v8_3/run1 (A 73.7?)", "20260925T161142Z"),
           ("v3/run1", "20260924T232910Z")]


def states(run: str):
    d = os.path.join(OUT, run)
    fs = [f for f in os.listdir(d) if f.startswith("events-")]
    if not fs:
        return
    seen = set()
    with open(os.path.join(d, fs[0]), encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("kind") != "tool_result":
                continue
            pay = o.get("payload") or {}
            if "observe" not in str(pay.get("tool_name", "")):
                continue
            tid = pay.get("tool_call_id") or o.get("seq")
            if tid in seen:
                continue
            seen.add(tid)
            raw = pay.get("result") or ""
            try:
                s = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
            except Exception:
                s = raw
            i = s.find('{"current_state"')
            if i < 0:
                continue
            # 花括号配对切出 JSON 主体（外层是 {'result': '...'} 的 python repr，rfind('}') 会切到 repr 尾巴）
            depth, j = 0, -1
            for k in range(i, len(s)):
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            if j < 0:
                continue
            try:
                obj = json.loads(s[i:j + 1])
            except Exception:
                continue
            st = (obj.get("current_state") or {}).get("status") or {}
            mo = ((obj.get("current_state") or {}).get("time") or {}).get("current_month")
            ev = (obj.get("current_event") or {}).get("title", "")
            yield o.get("seq"), mo, st, ev


def main() -> None:
    for label, run in TARGETS:
        print("=" * 96)
        print(f"### {label}   ({run})")
        print("=" * 96)
        print(f"{'seq':>6}{'月':>4}{'职级':>6}{'skill':>7}{'CAP(S)':>8}{'output':>8}"
              f"{'CAP(O)':>8}{'network':>9}{'CAP(N)':>8}{'H':>4}{'剩余体':>7}  {'顶格判定':<16} 事件")
        last = None
        for seq, mo, st, ev in states(run):
            lv = st.get("level", "?")
            cap = CAP.get(lv, {})
            sk, ou, nw = st.get("skill"), st.get("output"), st.get("network")
            full = []
            for nm, val in (("S", sk), ("O", ou), ("N", nw)):
                c = cap.get({"S": "skill", "O": "output", "N": "network"}[nm])
                if c is not None and val is not None and val >= c:
                    full.append(nm)
            key = (mo, lv)
            mark = "" if key == last else " ←"
            # 只打印「月份/职级变化」的行 + 顶格状态变化
            if key != last:
                print(f"{seq:>6}{mo if mo is not None else '?':>4}{lv:>6}{sk:>7}"
                      f"{cap.get('skill','-'):>8}{ou:>8}{cap.get('output','-'):>8}"
                      f"{nw:>9}{cap.get('network','-'):>8}{st.get('health'):>4}"
                      f"{st.get('energy'):>7}  {'/'.join(full) + ' 顶格' if full else '未顶格':<16}  "
                      f"{ev[:26]}{mark}")
                last = key
        print()


if __name__ == "__main__":
    main()
