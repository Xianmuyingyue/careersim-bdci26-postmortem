#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zone_census.py —— 用量化方式验证「赌本分层的时间结构缺陷」。

做法：不依赖 Agent 的自述，而是用它写在技能里的公式
      **安全垫 = health − 4 × k，k = 距本季末月（季内第3月）的月数 ∈ {2,1,0}**
      配合 observe 实测到的 health，**独立重算**每个月的分区。

关注的不是"算得对不对"，而是**分区在时间轴上的分布**：
若 M4/M5（= month%6∈{4,5}，即暴露窗 / 评审前最后两月）恒定落在收紧区或零容错区，
则「赌本分层」与「暴露窗口保护区」的作用域**完全重叠**，
而 v10e 明确把赌本分层排在暴露窗之前 ⇒ 暴露窗保护被系统性架空。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

RUNS = [("v10e/run2", "20260927T042353Z"),
        ("v10e/run1", "20260927T032531Z"),
        ("v8_3/run1", "20260925T161142Z"),
        ("v10c/run1", "20260926T081346Z")]


def unesc(s):
    try:
        return s.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    except Exception:
        return s


def cut(s):
    i = s.find('{"current_state"')
    if i < 0:
        return ""
    d, j = 0, -1
    for k in range(i, len(s)):
        if s[k] == "{":
            d += 1
        elif s[k] == "}":
            d -= 1
            if d == 0:
                j = k
                break
    return s[i:j + 1] if j > 0 else ""


def health_by_month(run):
    d = os.path.join(OUT, run)
    fs = [f for f in os.listdir(d) if f.startswith("events-")]
    out, seen = {}, set()
    with open(os.path.join(d, fs[0]), encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("kind") != "tool_result":
                continue
            p = o.get("payload") or {}
            if "observe" not in str(p.get("tool_name", "")):
                continue
            tid = p.get("tool_call_id")
            if tid in seen:
                continue
            seen.add(tid)
            body = cut(unesc(p.get("result") or ""))
            if not body:
                continue
            try:
                j = json.loads(body)
            except Exception:
                continue
            cs = j.get("current_state") or {}
            mo = (cs.get("time") or {}).get("current_month")
            st = cs.get("status") or {}
            if mo is None:
                continue
            if mo not in out:                      # 取当月**首个**回合（月内最高血量）
                out[mo] = (st.get("health"), st.get("level"))
    return out


def zone(pad):
    if pad >= 3:
        return "自由区"
    if pad >= 0:
        return "收紧区"
    return "零容错区"


def main() -> None:
    for label, run in RUNS:
        hb = health_by_month(run)
        if not hb:
            print(f"### {label}: 无数据\n")
            continue
        print("=" * 92)
        print(f"### {label}   ({run})")
        print("=" * 92)
        print(f"{'月':>4}{'r':>3}{'k':>3}{'health':>8}{'安全垫=h-4k':>13}{'分区':>10}   标记")
        cnt = {"自由区": 0, "收紧区": 0, "零容错区": 0}
        crit = 0
        for mo in sorted(hb):
            h, lv = hb[mo]
            if h is None:
                continue
            r = mo % 6
            # k = 距本季末月（M3/M6/M9…）的月数。季划分 = r∈{1,2,3} / {4,5,0}。
            #   实测反推（v10e RUN2）：M4(health7)→安全垫−1⇒k=2；M5(6)→2⇒k=1；M6(5)→5⇒k=0
            k = {1: 2, 2: 1, 3: 0, 4: 2, 5: 1, 0: 0}[r]
            pad = h - 4 * k
            z = zone(pad)
            cnt[z] += 1
            tag = ""
            if r in (4, 5):
                tag = "★暴露窗"
                if z != "自由区":
                    tag += " ← ⚠️ 被降级！"
                    crit += 1
            print(f"{mo:>4}{r:>3}{k:>3}{h:>8}{pad:>13}{z:>10}   {tag}")
        tot = sum(cnt.values())
        print(f"\n  合计 {tot} 个月：自由区 {cnt['自由区']} / 收紧区 {cnt['收紧区']} / "
              f"零容错区 {cnt['零容错区']}")
        print(f"  ★ 暴露窗月被赌本分层降级（非自由区）的次数：{crit}\n")


if __name__ == "__main__":
    main()
