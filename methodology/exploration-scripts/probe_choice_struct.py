#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：游戏内 current_state.choices 的原始结构里，到底有没有数值字段？

这一步决定「零成本模式」的可执行性路线：
  - 若 choices 自带 status_updates ⇒ Agent 可直接读真值，判据无需猜；
  - 若不帶 ⇒ 只能靠结构启发式（并需在全池上验证）。
"""
import json, glob, pathlib, pprint

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
    seen_keys = {}
    n_choice_nodes = 0
    hit = None
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        st = stream(pathlib.Path(p))
        for sq, k, s in st:
            if not s:
                continue
            chs = s.get("choices") or []
            if not chs:
                continue
            n_choice_nodes += 1
            for ch in chs:
                for kk in ch.keys():
                    seen_keys[kk] = seen_keys.get(kk, 0) + 1
            if hit is None:
                hit = (rd, sq, chs, s)
    print("=== choices 元素出现过的全部 key（跨全量日志）===")
    for kk, n in sorted(seen_keys.items(), key=lambda x: -x[1]):
        print(f"  {kk:<24} {n}")
    print(f"\n带 choices 的快照数：{n_choice_nodes}")
    if hit:
        rd, sq, chs, s = hit
        print(f"\n=== 样例：{rd}  seq={sq} ===")
        print("current_event:", json.dumps(s.get("current_event"), ensure_ascii=False)[:300])
        print("choices 原始 JSON（前 2 项）：")
        print(json.dumps(chs[:2], ensure_ascii=False, indent=2)[:2200])
        print("\nstatus 全字段：", json.dumps(s["current_state"]["status"], ensure_ascii=False))
        print("current_state 顶层 keys：", list(s["current_state"].keys()))


if __name__ == "__main__":
    main()
