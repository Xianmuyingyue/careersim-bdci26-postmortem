#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
policy_citation_census.py —— 「规则写了但有没有被执行」的引用普查。

动机：v10e 的 SKILL 里明明有「约束12 · L1 毕业线保护（level==L1且month≥7 ⇒
把离开 L1 设为不可协商的最高目标）」，但 RUN2 在 L1 待到 M21 才走。
⇒ 需要量化：**技能里的各条规则，在对局中实际被 Agent 引用了几次**。

方法：提取每局每个 take_action 的 `notes`（Agent 自述的理由），
按关键词组统计命中率，并按版本对照。

输出：
  ① 行为级关键词密度（每 100 条决策的命中次数）
  ② 主行动决策的完整理由序列（人工核对用）
  ③ 各版本 notes 的平均长度（越长 = 越长篇论证 = 越可能在背规则）
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

RUNS = {
    "v3":   ["20260924T232910Z", "20260924T235818Z",
             "20260925T002312Z", "20260925T004806Z"],
    "v8_3": ["20260925T161142Z", "20260925T164951Z"],
    "v10e": ["20260927T032531Z", "20260927T042353Z"],
}

# 关键词组：跨版本可比（语义级，不依赖某版条款编号）
GROUPS = [
    ("晋升/职级",   ["晋升", "晋级", "L1", "L2", "L3", "L4", "毕业", "门槛"]),
    ("毕业线/M18",  ["毕业线", "M18", "离开L1", "离开 L1"]),
    ("避险/保守",   ["低调避险", "避险", "保留体力", "不行动", "按兵不动"]),
    ("赌本/安全垫", ["安全垫", "零容错", "收紧区", "自由区", "赌本", "回撤", "容错"]),
    ("顶格/截断",   ["顶格", "截断", "上限", "CAP", "余量"]),
    ("GAP/补缺口",  ["缺口", "g(", "增量恒", "增量=0", "增量恒为0"]),
    ("语义词典族",  ["原则族", "长度律", "维持族", "投入族", "描述最长", "桶"]),
    ("长链/整链",   ["长链", "整链", "整条链"]),
    ("绩效/perf",   ["绩效", "perf", "炒鱿鱼", "谈话", "奖金"]),
    ("健康/health", ["健康", "health", "体力", "血线"]),
    ("风险/爆雷",   ["风险", "hidden", "爆雷", "埋雷", "读数"]),
    ("财富/wealth", ["财富", "wealth", "西北风", "月薪"]),
    ("发展/成长",   ["发展", "成长", "投入", "冲刺", "关键项目", "汇报"]),
    ("红线/否决",   ["红线", "否决", "一票", "禁止", "不得"]),
    ("评审窗",      ["评审", "窗口", "暴露窗", "month%6", "相位"]),
]


def notes_of(run: str):
    """返回 [(month_hint, notes_text)]，按 seq 顺序，去重（同一 tool_call_id 有两种 payload 形态）。"""
    d = os.path.join(OUT, run)
    if not os.path.isdir(d):
        return []
    fs = [f for f in os.listdir(d) if f.startswith("events-")]
    if not fs:
        return []
    seen, out = set(), []
    with open(os.path.join(d, fs[0]), encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("kind") != "tool_call":
                continue
            pay = o.get("payload") or {}
            tc = pay.get("tool_call") or (pay.get("delta") or {}).get("tool_call") or {}
            if "take_action" not in str(tc.get("name", "")):
                continue
            tid = tc.get("tool_call_id")
            if tid in seen:
                continue
            seen.add(tid)
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except Exception:
                continue
            nt = args.get("notes") or ""
            if nt:
                out.append((o.get("seq"), nt))
    return out


def month_of(txt: str):
    m = re.search(r"M(\d{1,2})", txt)
    return int(m.group(1)) if m else None


def main() -> None:
    data = {v: [notes_of(r) for r in rs] for v, rs in RUNS.items()}

    print("=" * 90)
    print("① 规模")
    print("=" * 90)
    print(f"{'版本':<8}{'局数':>5}{'决策数':>8}{'notes 均长':>12}{'notes 中位':>12}")
    for v in RUNS:
        alln = [n for per in data[v] for _, n in per]
        if not alln:
            print(f"{v:<8}{0:>5}{0:>8}")
            continue
        sl = sorted(len(n) for n in alln)
        print(f"{v:<8}{len(data[v]):>5}{len(alln):>8}{sum(sl)/len(sl):>12.0f}"
              f"{sl[len(sl)//2]:>12}")

    print()
    print("=" * 90)
    print("② 关键词密度（每 100 条决策的命中条数）")
    print("=" * 90)
    hdr = f"{'组':<14}" + "".join(f"{v:>12}" for v in RUNS)
    print(hdr)
    for name, kws in GROUPS:
        row = f"{name:<14}"
        for v in RUNS:
            alln = [n for per in data[v] for _, n in per]
            if not alln:
                row += f"{'—':>12}"
                continue
            hit = sum(1 for n in alln if any(k in n for k in kws))
            row += f"{hit/len(alln)*100:>11.1f}"
        print(row)

    print()
    print("=" * 90)
    print("③ 主行动决策（notes 含「主行动」）的完整理由")
    print("=" * 90)
    for v in RUNS:
        for run, per in zip(RUNS[v], data[v]):
            mains = [(s, n) for s, n in per if "主行动" in n]
            if not mains:
                continue
            print(f"\n--- {v} / {run} —— 主行动 {len(mains)} 次 ---")
            for s, n in mains:
                print(f"  [seq {s}] {n[:220]}")

    print()
    print("=" * 90)
    print("④ 「避险/保守」类决策逐条（判定是否否决了发展机会）")
    print("=" * 90)
    for v in RUNS:
        for run, per in zip(RUNS[v], data[v]):
            hit = [(s, n) for s, n in per
                   if any(k in n for k in ("低调避险", "保留体力", "不行动"))]
            if not hit:
                continue
            print(f"\n--- {v} / {run} —— {len(hit)} 条 / 共 {len(per)} 条 ---")
            for s, n in hit[:12]:
                print(f"  [seq {s}] {n[:200]}")


if __name__ == "__main__":
    main()
