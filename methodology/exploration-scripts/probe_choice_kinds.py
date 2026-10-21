#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 2：把 choices 里的选项按「是否体力选项」分类，精确统计 status_updates 覆盖率。

关键问题（决定「零成本模式」能不能精确执行）：
  剧情选项（有 description、无 energy_cost）到底带不帶 status_updates？
    - 带 ⇒ Agent 可直接读真值，判据不必靠语义猜；
    - 不带 ⇒ 只能靠结构/语义启发式。
"""
import json, glob, pathlib, itertools
from collections import Counter

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
DEC = json.JSONDecoder()


def stream(path):
    out = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        st = None
        if "current_state" in line:
            t = line.replace('\\"', '"')
            i = t.find('{"current_state":{')
            while i != -1:
                try:
                    obj, _ = DEC.raw_decode(t[i:])
                except Exception:
                    obj = None
                if isinstance(obj, dict) and "current_state" in obj:
                    st = obj
                i = t.find('{"current_state":{', i + 1)
        out.append((o.get("seq"), o.get("kind"), st))
    return out


def main():
    cross = Counter()
    samples = {"BH": [], "B0": []}
    seen_snap = set()
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        st = stream(pathlib.Path(p))
        for sq, k, s in st:
            if not s:
                continue
            chs = s.get("choices") or []
            if not chs:
                continue
            # 同一快照会重复渲染，去重
            key = (rd, sq, json.dumps(chs, ensure_ascii=False)[:200])
            if key in seen_snap:
                continue
            seen_snap.add(key)
            for ch in chs:
                he = "energy_cost" in ch
                hd = "description" in ch
                hs = "status_updates" in ch
                cross[(he, hd, hs)] += 1
                if hd and not he and hs and len(samples["BH"]) < 6:
                    samples["BH"].append((rd, sq, ch))
                if hd and not he and not hs and len(samples["B0"]) < 6:
                    samples["B0"].append((rd, sq, ch))

    print("=== 交叉表： (有energy_cost, 有description, 有status_updates) ===")
    print(f"    {'energy':<8}{'desc':<8}{'status_updates':<16}{'count'}")
    for k, n in sorted(cross.items(), key=lambda x: -x[1]):
        print(f"    {str(k[0]):<8}{str(k[1]):<8}{str(k[2]):<16}{n}")
    tot = sum(cross.values())
    print(f"    合计 {tot}")

    print("\n=== 剧情选项（有 desc、无 energy_cost）中 带 status_updates 的样例 ===")
    if not samples["BH"]:
        print("    （无 —— 剧情选项一律不带 status_updates）")
    for rd, sq, ch in samples["BH"]:
        print(f"    {rd} seq={sq}")
        print("      ", json.dumps(ch, ensure_ascii=False)[:400])

    print("\n=== 剧情选项（有 desc、无 energy_cost）中 不带 status_updates 的样例 ===")
    for rd, sq, ch in samples["B0"]:
        print(f"    {rd} seq={sq}")
        print("      ", json.dumps(ch, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
