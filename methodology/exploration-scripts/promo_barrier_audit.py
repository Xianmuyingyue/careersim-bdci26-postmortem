#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promo_barrier_audit.py —— 定位 L1→L5 各晋升窗的「卡点维度」。

方法（对局内可观察量）：
  * 评审在 month % 6 == 0 的**第一个回合**用即时状态结算 ⇒ 取该月**首个 `**状态:**` 行**当评审瞬间。
  * 晋升前职级 = 上一月首个状态行的 level；该月内出现 `晋升通知` 即判定晋升成功。
  * 门槛（DP §五 长期路线）：L1→L2 8/3/3 ｜ L2→L3 18/5/6 ｜ L3→L4 35/14/18 ｜
    L4→L5 90/22/30 ｜ L5→L6 130/32/45（skill / output / network）。
输出：每个 transition 的尝试次数、成功次数，以及失败时「缺哪一维、缺多少」的分布。
"""
from __future__ import annotations

import glob
import os
import re

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

ARMS = {
    "v3_rerun": ["20260927T085137Z", "20260927T091800Z", "20260927T093827Z", "20260927T095512Z"],
    "v3_rerun2": ["20260928T223943Z", "20260928T224634Z", "20260928T231132Z", "20260928T233302Z"],
    "v12": ["20260928T113941Z", "20260928T115042Z", "20260928T123048Z", "20260928T132134Z"],
    "v11": ["20260928T100916Z", "20260928T102548Z", "20260928T104248Z", "20260928T111337Z"],
    "v13": ["20260929T004231Z", "20260929T021657Z"],
    "v14": ["20260929T051757Z", "20260929T062953Z", "20260929T063708Z", "20260929T070350Z"],
}
TH = {
    "L1": (8, 3, 3),
    "L2": (18, 5, 6),
    "L3": (35, 14, 18),
    "L4": (90, 22, 30),
    "L5": (130, 32, 45),
}
EVAL_MONTHS = (5, 11, 17, 23, 29, 35, 41, 47)
STATE_RE = re.compile(
    r"level=(L\d+),\s*health=(-?\d+),\s*dignity=(-?\d+),\s*skill=(-?\d+),"
    r"\s*network=(-?\d+),\s*output=(-?\d+)")


def month_states(path: str) -> dict[int, list[dict]]:
    """{月号: [状态, ...]}，按出现顺序；状态含 level/skill/network/output。"""
    out: dict[int, list[dict]] = {}
    month = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^## 第 (\d+) 月", line)
        if m:
            month = int(m.group(1))
            out.setdefault(month, [])
            continue
        if month is None:
            continue
        s = STATE_RE.search(line)
        if s:
            out[month].append(dict(level=s.group(1), skill=int(s.group(4)),
                                   network=int(s.group(5)), output=int(s.group(6))))
    return out


def has_promo(path: str, month: int) -> bool:
    m = re.search(rb"", b"")  # placeholder to keep linters quiet
    del m
    text = open(path, encoding="utf-8").read()
    blocks = re.split(r"^## 第 (\d+) 月", text, flags=re.M)
    for i in range(1, len(blocks), 2):
        if int(blocks[i]) == month:
            return "晋升通知" in blocks[i + 1]
    return False


def main() -> int:
    stats: dict[str, dict] = {}
    rows = []
    for arm, dirs in ARMS.items():
        for d in dirs:
            rp = glob.glob(os.path.join(OUT, d, "replay-*.md"))
            if not rp:
                continue
            ms = month_states(rp[0])
            for e in EVAL_MONTHS:
                if e not in ms or not ms[e]:
                    continue
                # ★ 评审在评审月末结算（晋升通知印在该月内）⇒ 用该月**最后**一个状态行
                lvl = ms[e][-1]["level"]
                st = ms[e][-1]
                if lvl not in TH:
                    continue
                ts, to, tn = TH[lvl]
                gs = max(0, ts - st["skill"])
                go = max(0, to - st["output"])
                gn = max(0, tn - st["network"])
                ok = has_promo(rp[0], e)
                key = f"{lvl}→L{int(lvl[1]) + 1}"
                s = stats.setdefault(key, dict(att=0, ok=0, gs=[], go=[], gn=[],
                                               both=0, miss3=0))
                s["att"] += 1
                if ok:
                    s["ok"] += 1
                else:
                    if gs:
                        s["gs"].append(gs)
                    if go:
                        s["go"].append(go)
                    if gn:
                        s["gn"].append(gn)
                    shorts = sum(1 for g in (gs, go, gn) if g > 0)
                    if shorts >= 2:
                        s["both"] += 1
                    if shorts >= 3:
                        s["miss3"] += 1
                rows.append((arm, d, e, key, st["skill"], st["output"], st["network"],
                             gs, go, gn, "★晋升" if ok else "落榜"))

    print("逐局明细（评审瞬间值）")
    print("  臂/局             月  转段     S   O   N   缺S 缺O 缺N  结果")
    for r in rows:
        print("  %-11s %-15s %2d  %-6s %3d %3d %3d   %2d  %2d  %2d  %s"
              % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]))

    print("\n按转段汇总")
    for k, s in stats.items():
        def dist(v):
            return "/".join(str(x) for x in sorted(set(v))) if v else "—"
        print("  %-7s 尝试 %2d  晋升 %2d  成功率 %3.0f%%   失败时缺S∈{%s} 缺O∈{%s} 缺N∈{%s}  "
              "双缺 %d  三缺 %d"
              % (k, s["att"], s["ok"], 100.0 * s["ok"] / max(1, s["att"]),
                 dist(s["gs"]), dist(s["go"]), dist(s["gn"]), s["both"], s["miss3"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
