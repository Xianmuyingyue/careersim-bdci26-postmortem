#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描「月推进瞬间」的属性变化：last snapshot of month M → first snapshot of month M+1。

目的：判定 M5→M6 边界上 network −1 是不是引擎级的「月推进副作用」（而非剧情选项），
     进而解释「M5 末还达标、M6 评审却差 1 点」。
"""
import json, glob, sys
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
_DEC = json.JSONDecoder()
KEYS = ("skill", "output", "network", "dignity", "health")


def raw_states(path):
    """按原始出现顺序（不去重）返回 (month, status, title, events_head)"""
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "current_state" not in line:
            continue
        s = line.replace('\\"', '"')
        i = s.find('{"current_state":{')
        while i != -1:
            try:
                obj, _ = _DEC.raw_decode(s[i:])
            except Exception:
                obj = None
            if isinstance(obj, dict) and "current_state" in obj:
                st = obj["current_state"]
                if "status" in st and "time" in st:
                    out.append(dict(
                        month=st["time"].get("current_month"),
                        st=dict(st["status"]),
                        title=(obj.get("current_event") or {}).get("title", ""),
                        ev=(obj.get("events") or "")[:60],
                    ))
            i = s.find('{"current_state":{', i + 1)
    return out


def main():
    paths = sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl"))
    agg = defaultdict(Counter)      # transition → Counter of delta-tuple
    per_run = {}
    for p in paths:
        rd = Path(p).parent.name
        seq = raw_states(Path(p))
        if not seq:
            continue
        # 按月分组，取每月首末
        bym = defaultdict(list)
        for s in seq:
            bym[s["month"]].append(s)
        months = sorted(m for m in bym if isinstance(m, int))
        trans = []
        for a, b in zip(months, months[1:]):
            if b != a + 1:
                continue
            last_a = bym[a][-1]
            first_b = bym[b][0]
            d = {}
            for k in KEYS:
                va, vb = last_a["st"].get(k), first_b["st"].get(k)
                if va is None or vb is None:
                    continue
                d[k] = vb - va
            trans.append((a, b, d, last_a, first_b))
            key = f"M{a}→M{b}"
            agg[key][tuple(sorted(d.items()))] += 1
        per_run[rd] = trans

    print("=== 各月推进瞬间的属性变化分布（全部局）===")
    for key in sorted(agg, key=lambda s: int(s.split("→")[0][1:])):
        c = agg[key]
        items = c.most_common()
        tot = sum(c.values())
        print(f"\n{key}  (n={tot})")
        for k, v in items[:6]:
            print(f"    {v:>4}  {dict(k)}")

    # 聚焦 M5→M6
    print("\n\n=== 聚焦 M5→M6：逐局 ===")
    print(f"{'run':<22} {'S':>6} {'O':>6} {'N':>6} {'D':>6} {'H':>6}")
    netdrop = 0
    for rd, trans in sorted(per_run.items()):
        for a, b, d, la, fb in trans:
            if (a, b) == (5, 6):
                f = lambda k: f"{la['st'].get(k)}→{fb['st'].get(k)}"
                print(f"{rd:<22} {f('skill'):>6} {f('output'):>6} {f('network'):>6} {f('dignity'):>6} {f('health'):>6}")
                if d.get("network", 0) < 0:
                    netdrop += 1
    print(f"\n★ M5→M6 network 下降的局数: {netdrop}")

    # 各月推进中 network 下降的整体比例
    print("\n=== 所有月推进中「network 下降」比例 ===")
    for key in sorted(agg, key=lambda s: int(s.split("→")[0][1:])):
        dn = sum(v for k, v in agg[key].items() if dict(k).get("network", 0) < 0)
        tot = sum(agg[key].values())
        print(f"    {key}: {dn}/{tot} = {dn/max(tot,1)*100:.0f}%")


if __name__ == "__main__":
    main()
