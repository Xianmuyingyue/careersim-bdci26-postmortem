#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
token_speed_census.py —— 各臂的「token 成本」与「运算速度」对照。

为什么必须**按月归一化**：早死局只有 24 月，token 与墙钟天然更少 ⇒
直接比均值会把"跑得短"误读成"跑得快"。本报告一律用
    token/月（M tokens per month）
    秒/月（seconds per month）
两个口径。

数据来源
--------
- token 与月数：analysis/ab/results_<arm>.tsv（`tokens` / `months` 列）
- 墙钟：analysis/ab/driver.log 里每个 run_dir 的 `RUN i/n START` → `RUN i attempt 1 exit=0` 时间戳
  （同一 run_dir 可能在多次 session 里出现；只取「该 log 里最后一次 START/DONE 配对」）
- 技能体量：字符数（leriyan memory 里的实测值）
"""
from __future__ import annotations

import csv
import os
import re
import statistics as st
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AB = os.path.join(REPO, "analysis", "ab")
LOG = os.path.join(AB, "driver.log")

# 技能的参考体量（字符）—— 与技能 LOAD 到上下文的比例直接相关
SKILL_SIZE = {
    "v3_rerun": 13071, "v8_3_rerun": 43078, "v10c": None, "v10d": None,
    "v10e": 72556, "v3": 13071, "v8_3": 43078,
}
ARMS = ["v3_rerun", "v8_3_rerun", "v10c", "v10d", "v10e", "v8_5"]

START_RE = re.compile(r"^\[([^\]]+)\]\s+RUN (\d+)/(\d+) START")
DONE_RE = re.compile(r"^\[([^\]]+)\]\s+RUN (\d+) attempt \d+ exit=0")
DONE_DIR_RE = re.compile(r"RUN (\d+) DONE dir=(\S+)")


def read_results(arm):
    p = os.path.join(AB, f"results_{arm}.tsv")
    if not os.path.exists(p):
        return []
    rows = []
    with open(p, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            try:
                rows.append({
                    "dir": r.get("run_dir", "").strip(),
                    "months": int(float(r.get("months") or 0)),
                    "tokens": int(float(r.get("tokens") or 0)),
                    "score": float(r.get("score") or 0),
                    "level": r.get("raw_level", ""),
                })
            except Exception:
                continue
    return rows


def read_wallclock():
    """返回 {dirname: seconds}。driver.log 可能含多次 session，取最后一次完整配对。"""
    if not os.path.exists(LOG):
        return {}
    lines = open(LOG, encoding="utf-8").read().splitlines()
    out = {}
    i = 0
    cur_dir = None
    start_ts = None
    while i < len(lines):
        m0 = DONE_DIR_RE.search(lines[i])
        if m0:
            cur_dir = m0.group(2)
        m1 = START_RE.match(lines[i])
        if m1:
            start_ts = m1.group(1)
            # 往后找同一 RUN 的 exit=0 行
            j = i + 1
            while j < len(lines) and j < i + 60:
                m2 = DONE_RE.match(lines[j])
                m3 = DONE_DIR_RE.search(lines[j])
                if m2 or m3:
                    break
                j += 1
            if j < len(lines):
                m2 = DONE_RE.match(lines[j])
                if m2:
                    from datetime import datetime
                    f = "%Y-%m-%d %H:%M:%S"
                    try:
                        a = datetime.strptime(start_ts, f)
                        b = datetime.strptime(m2.group(1), f)
                        sec = (b - a).total_seconds()
                        dd = None
                        m4 = DONE_DIR_RE.search(lines[j]) or (
                            DONE_DIR_RE.search(lines[j + 1]) if j + 1 < len(lines) else None)
                        if m4:
                            dd = m4.group(2)
                        if dd and sec > 0:
                            out[dd] = sec
                    except Exception:
                        pass
            start_ts = None
        i += 1
    return out


def fmt(x, n=1):
    return f"{x:>{n}.2f}" if x is not None else "—"


def main() -> None:
    wc = read_wallclock()
    print("=" * 104)
    print("① 逐局明细（token / 月 与 秒 / 月 才是可比口径）")
    print("=" * 104)
    print(f"{'臂':<12}{'run_dir':<18}{'月':>4}{'总分':>9}{'token(M)':>10}"
          f"{'M/月':>8}{'分钟':>8}{'秒/月':>8}")
    for arm in ARMS:
        rows = read_results(arm)
        if not rows:
            continue
        for r in rows:
            d = r["dir"]
            mo = r["months"] or 1
            tpm = r["tokens"] / 1e6 / mo
            sec = wc.get(d)
            spm = sec / mo if sec else None
            print(f"{arm:<12}{d:<18}{mo:>4}{r['score']:>9.2f}{r['tokens']/1e6:>10.2f}"
                  f"{tpm:>8.3f}{(fmt(sec/60, 0) if sec else '—'):>8}"
                  f"{(fmt(spm,0) if spm else '—'):>8}")

    print()
    print("=" * 104)
    print("② 按臂聚合（★ 只用完赛 48 月局，避免早死局污染）")
    print("=" * 104)
    print(f"{'臂':<12}{'技能字符':>10}{'完赛n':>7}{'M/月':>9}{'秒/月':>9}{'分钟/局':>10}"
          f"{'完赛均分':>10}")
    print("-" * 104)
    summary = []
    for arm in ARMS:
        rows = [r for r in read_results(arm) if r["months"] == 48]
        if not rows:
            continue
        tpms = [r["tokens"] / 1e6 / r["months"] for r in rows]
        secs = [wc.get(r["dir"]) for r in rows if wc.get(r["dir"])]
        spms = [s / r["months"] for s, r in zip(secs, rows) if s] if len(secs) == len(rows) else []
        combined = [(wc.get(r["dir"]), r["months"]) for r in rows if wc.get(r["dir"])]
        spms = [s / m for s, m in combined] if combined else []
        row = {
            "arm": arm,
            "size": SKILL_SIZE.get(arm),
            "n": len(rows),
            "tpm": st.mean(tpms),
            "spm": st.mean(spms) if spms else None,
            "min_per": (st.mean(spms) * 48 / 60) if spms else None,
            "score": st.mean([r["score"] for r in rows]),
        }
        summary.append(row)

    for r in summary:
        print(f"{r['arm']:<12}{fmt(r['size'],0) if r['size'] else '—':>10}{r['n']:>7}"
              f"{r['tpm']:>9.3f}{(fmt(r['spm'],0) if r['spm'] else '—'):>9}"
              f"{(fmt(r['min_per'],1) if r['min_per'] else '—'):>10}"
              f"{r['score']:>10.2f}")

    print()
    print("=" * 104)
    print("③ v3_rerun vs v8_3_rerun：差值与解读")
    print("=" * 104)
    a = next((r for r in summary if r["arm"] == "v3_rerun"), None)
    b = next((r for r in summary if r["arm"] == "v8_3_rerun"), None)
    if a and b:
        dtok = (b["tpm"] - a["tpm"]) / a["tpm"] * 100
        print(f"  token / 月   v3 {a['tpm']:.3f} M  vs  v8_3 {b['tpm']:.3f} M"
              f"   ⇒ v8_3 {'多' if dtok>0 else '少'} {abs(dtok):.1f}%")
        if a["spm"] and b["spm"]:
            dspm = (b["spm"] - a["spm"]) / a["spm"] * 100
            print(f"  秒   / 月   v3 {a['spm']:.0f} s  vs  v8_3 {b['spm']:.0f} s"
                  f"   ⇒ v8_3 {'多' if dspm>0 else '少'} {abs(dspm):.1f}%")
        print(f"  技能体量     v3 {a['size']} 字符  vs  v8_3 {b['size']} 字符"
              f"   ⇒ 差 {b['size']-a['size']:+} 字符（{b['size']/a['size']:.1f}×）")
        print("\n  注：墙钟同时受 API 拥堵影响（v3_rerun 跑于 17–18 时、v8_3_rerun 跑于 19–21 时），")
        print("      故秒/月只能作粗略参考；token/月 才是反映技能体量的干净指标。")


if __name__ == "__main__":
    main()
