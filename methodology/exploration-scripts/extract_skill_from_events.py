#!/usr/bin/env python3
"""从 events jsonl 中还原「某局运行时用的那三份 SKILL.md 全文」。

原理：Agent 在开局调 `skill_tool`，工具返回里带 `skill_content` = SKILL.md 全文，
该 tool_result 会被完整写进 `events-*.jsonl`。⇒ **历史技能可逐字还原**（会话历史被清理也不影响）。

用法：
    .venv/bin/python3 analysis/extract_skill_from_events.py --run 20260924T232910Z --out /tmp/v3
    .venv/bin/python3 analysis/extract_skill_from_events.py --run 20260925T161142Z --out /tmp/v8_3
    .venv/bin/python3 analysis/extract_skill_from_events.py --run 20260927T032531Z --out /tmp/v10e

⚠️ payload 结构：
    kind=tool_result
      · `payload.delta.result`（delta_kind=custom）或
      · `payload.result`
    两者都是 **Python repr 字符串**：
        `success=True data={'skill_directory': ..., 'skill_content': ...} error=None`
    ⇒ 用 `ast.literal_eval` 解析 `data=` 之后、`} error=` 之前的那段字典。
    ★ 必须**按 `} error=` 截断**：直接把 `data=` 之后整段丢给 `literal_eval` 会因尾部
      ` error=None` 报 `invalid syntax`（本脚本第一版就栽在这里）。
"""
import argparse
import ast
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")


def iter_results(path):
    """产出每个 tool_result 的 (seq, result_string)。"""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("kind") != "tool_result":
                continue
            pay = obj.get("payload") or {}
            raw = None
            if isinstance(pay.get("result"), str):
                raw = pay["result"]
            elif isinstance(pay.get("delta"), dict) and isinstance(pay["delta"].get("result"), str):
                raw = pay["delta"]["result"]
            if raw:
                yield obj.get("seq"), raw


def extract(path):
    """返回 {skill_name: full_text}（取每份技能的第一次出现）。"""
    found = {}
    for seq, raw in iter_results(path):
        i = raw.find("data=")
        if i < 0:
            continue
        # ★ 字典在 `} error=` 之前结束；不截断会让 literal_eval 报 invalid syntax
        tail = raw.rfind("} error=")
        chunk = raw[i + 5:tail + 1] if tail >= 0 else raw[i + 5:]
        try:
            payload = ast.literal_eval(chunk)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        content = payload.get("skill_content")
        directory = payload.get("skill_directory") or ""
        if not content:
            continue
        name = os.path.basename(directory.rstrip("/")) or ("skill_%s" % seq)
        if name not in found:
            found[name] = content
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="outputs 下的 run_dir，例如 20260924T232910Z")
    ap.add_argument("--out", default=None, help="输出目录（默认只打印统计）")
    args = ap.parse_args()

    d = os.path.join(OUTROOT, args.run)
    if not os.path.isdir(d):
        print("目录不存在：%s" % d, file=sys.stderr)
        return 1
    evs = [f for f in os.listdir(d) if f.startswith("events-")]
    if not evs:
        print("无 events 文件", file=sys.stderr)
        return 1

    found = extract(os.path.join(d, evs[0]))
    if not found:
        print("未找到 skill_content（该局可能没调用 skill_tool）", file=sys.stderr)
        return 1

    total = 0
    print("run = %s" % args.run)
    for name in sorted(found):
        text = found[name]
        total += len(text)
        print("  %-22s chars=%-7d lines=%d" % (name, len(text), text.count("\n") + 1))
    print("  %-22s chars=%-7d" % ("合计", total))
    print("  文件总大小 = %.1f MB" % (os.path.getsize(os.path.join(d, evs[0])) / 1048576))

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for name, text in found.items():
            p = os.path.join(args.out, name, "SKILL.md")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(text)
        print("  已写出到 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
