#!/usr/bin/env python3
"""在 v8_5 各局里搜「未晋升 / 没晋升 / 评审未过」等自诊断，定位漏窗原因。

用法：python3 analysis/find_miss_reason.py <run_dir> [关键词...]
"""
import json
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
KW = ["未晋升", "没晋升", "未通过", "没通过", "评审没过", "挂门", "perf门", "缺口",
      "错失", "白等", "漏窗", "错过"]


def walk(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and ("notes" in k or k == "content"):
                out.append(v)
            else:
                walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, out)
    elif isinstance(obj, str) and obj.lstrip()[:1] in "{[":
        try:
            walk(json.loads(obj), out)
        except Exception:
            pass


def main():
    run_dir = sys.argv[1]
    kws = sys.argv[2:] or KW
    p = os.path.join(OUT, run_dir, "events-%s.jsonl" % run_dir)
    seen = set()
    for line in open(p, encoding="utf-8", errors="replace"):
        if not any(k in line for k in kws):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        got = []
        walk(o, got)
        for s in got:
            for k in kws:
                if k in s:
                    key = s[:100]
                    if key in seen:
                        break
                    seen.add(key)
                    m = re.search(r"\bM(\d+)", s)
                    print("M%-4s [%s] %s" % (m.group(1) if m else "?", k, s[:340]))
                    break


if __name__ == "__main__":
    main()
