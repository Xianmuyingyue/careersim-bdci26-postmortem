#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_bursts.py —— 用 replay 正文核实「爆雷」真实次数，对照 metrics 的 bursts 字段。

动机：metrics/*.json 的 bursts 字段已证误（v3_rerun2 RUN3 引擎明文「第二次爆雷」而字段记 1）。
口径：引擎每次爆雷会在月间播报印出「…一起炸了，最近半年的工作都打了水漂！」⇒ 计数该句。
"""
from __future__ import annotations

import glob
import json
import os
import re

OUT = ".career_sim_runner/career_emu/outputs/九问"
MD = "analysis/ab/metrics"

ARMS = {
    "v3_rerun  (旧批)": ["20260927T085137Z", "20260927T091800Z", "20260927T093827Z", "20260927T095512Z"],
    "v3_rerun2 (新批)": ["20260928T223943Z", "20260928T224634Z", "20260928T231132Z", "20260928T233302Z"],
    "v12": ["20260928T113941Z", "20260928T115042Z", "20260928T123048Z", "20260928T132134Z"],
    "v11": ["20260928T100916Z", "20260928T102548Z", "20260928T104248Z", "20260928T111337Z"],
    "v13": ["20260929T004231Z", "20260929T021657Z"],
    "v14": ["20260929T051757Z", "20260929T062953Z", "20260929T063708Z", "20260929T070350Z"],
}

# 崩溃局（attempt 收尾 WS 崩）没有 replay-*.md ⇒ 回退 events，
# 但 events 前若干行是开局 onboarding 文档，其「风言风语（隐患）」示例里
# 就含「一起炸了，最近半年的工作都打了水漂！」⇒ 必须跳过，否则每局虚增 2。
EVENTS_SKIP_HEAD = 12


def probe(d: str) -> dict:
    rp = glob.glob(os.path.join(OUT, d, "replay-*.md"))
    text = open(rp[0], encoding="utf-8").read() if rp else ""
    if rp:
        n_text = text.count("打了水漂")
    else:
        ev = glob.glob(os.path.join(OUT, d, "events-*.jsonl"))
        body = ""
        if ev:
            lines = open(ev[0], encoding="utf-8", errors="replace").read().splitlines()
            body = "\n".join(lines[EVENTS_SKIP_HEAD:])
        n_text = body.count("打了水漂")
    m = re.search(r"> \*\*出局:\*\* (\S+?)end", text)
    if m:
        end = m.group(1) + "end"
    elif rp:
        end = "completed"
    else:
        # 无 replay 的崩溃局：改由 score_report 的 ending_score 判生死
        end = "?"
        sp0 = os.path.join(OUT, d, "score_report.json")
        if os.path.exists(sp0):
            es0 = json.load(open(sp0)).get("ending_score") or {}
            if es0.get("completed"):
                end = "completed"
            elif es0.get("outcome"):
                end = str(es0.get("outcome"))
    mb = None
    mp = os.path.join(MD, f"{d}.json")
    if os.path.exists(mp):
        mb = json.load(open(mp)).get("bursts")
    score = months = None
    sp = os.path.join(OUT, d, "score_report.json")
    if os.path.exists(sp):
        es = json.load(open(sp)).get("ending_score") or {}
        score = es.get("quantitative_score")
        months = es.get("survival_months")
    return dict(dir=d, score=score, months=months, text_burst=n_text, metric_burst=mb, end=end)


def main() -> int:
    for arm, dirs in ARMS.items():
        print("=" * 16, arm)
        tot_text = tot_metric = 0
        for d in dirs:
            r = probe(d)
            tot_text += r["text_burst"]
            tot_metric += (r["metric_burst"] or 0)
            flag = "  <== 字段漏计" if (r["metric_burst"] or 0) != r["text_burst"] else ""
            print("  %s  score=%-6s months=%-3s 正文爆雷=%d  字段=%s  %-14s%s"
                  % (r["dir"], r["score"], r["months"], r["text_burst"], r["metric_burst"], r["end"], flag))
        print("  小计：正文爆雷 %d 次 / 字段 %d 次" % (tot_text, tot_metric))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
