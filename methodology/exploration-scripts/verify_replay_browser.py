#!/usr/bin/env python3
"""校验 replay_browser.html 的 DATA 负载：局数、分组、垃圾目录泄漏。"""
import json
import pathlib

HTML = pathlib.Path("<PROJECT_ROOT>/analysis/replay_browser.html")
h = HTML.read_text(encoding="utf-8")
start = h.find('{"runs":')
data, _ = json.JSONDecoder().raw_decode(h[start:])
runs = data["runs"]
print("总局数：", len(runs), " 文件大小：%.2f MB" % (HTML.stat().st_size / 1024 / 1024))
grouped = set()
for b in data["batches"]:
    ds = [r for r in runs if r["dir"] in b["dirs"]]
    grouped |= set(b["dirs"])
    print("  %-46s %d 局  %s" % (b["label"], len(ds),
          [(r["dir"][-10:], r["score"].get("grade"), r["score"].get("score")) for r in ds]))
print("未分组：", [r["dir"] for r in runs if r["dir"] not in grouped])
bad = [d for d in ("20260925T212921Z", "20260925T215817Z", "20260925T192124Z") if d in h]
print("垃圾目录泄漏：", bad or "无")
