#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M6 晋级归因：定位「M5 月末 n/o 都=3，M6 结算却掉到 2」的那 1 点是被谁吃掉的。

做法：
  1) 从 events-*.jsonl 抽两条流：
     A. 引擎状态快照流（含 current_state / choices / events）—— 平衡解析，按 (month, events) 去重
     B. take_action 流（实际选择：choice 序号 + notes 文本）
  2) 把两条流按 seq 顺序合并成逐回合时间线，于是每次「选项 → 状态变化」都能对齐。
  3) 只在 M4/M5/M6 窗口内，标出每一次 (skill, output, network) 的变化及其来源选项。

用法：
  .venv/bin/python3 analysis/m6_promo_attrib.py            # 汇总 + 异常局详情
  .venv/bin/python3 analysis/m6_promo_attrib.py --run 20260924T161605Z
"""
import sys, re, json, glob
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"

TH_L1 = dict(skill=8, output=3, network=3)
PROMO = re.compile(r"晋升通知：半年组织评审通过，您已从 (L\d) 晋升至 (L\d)")
BONUS = re.compile(r"半年绩效奖金（([SABCD])）：([+\-][\d.]+)")
_DEC = json.JSONDecoder()


def iter_events(path):
    """yield (seq, kind, payload_dict)"""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            pass


def extract_states(path):
    """从原始行里平衡抽出引擎 JSON（两层转义），保留出现顺序，按 (month, events) 去重"""
    out, seen = [], set()
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
                mo = st.get("time", {}).get("current_month")
                key = (mo, obj.get("events", ""), json.dumps(obj.get("choices", []), ensure_ascii=False))
                if key not in seen:
                    seen.add(key)
                    out.append(obj)
            i = s.find('{"current_state":{', i + 1)
    return out


def extract_actions(path):
    """抽 take_action 调用：(seq, month_hint, choice, notes)"""
    acts = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        pl = o.get("payload", {})
        s = json.dumps(pl, ensure_ascii=False)
        if "mcp_career-emulator_take_action" not in s:
            continue
        for m in re.finditer(r'"arguments":\s*"((?:[^"\\]|\\.)*)"', s):
            raw = m.group(1)
            try:
                args = json.loads(json.loads('"' + raw + '"'))
            except Exception:
                try:
                    args = json.loads(raw.replace('\\"', '"'))
                except Exception:
                    continue
            acts.append((o.get("seq"), args.get("choice"), (args.get("notes") or "")[:110]))
    # 去重（同一 tool_call_id 会出现在 delta 与平铺两处）
    seen, out = set(), []
    for seq, ch, notes in acts:
        k = (seq, ch, notes)
        if k in seen:
            continue
        seen.add(k)
        out.append((seq, ch, notes))
    return out


def st_brief(st):
    s = st["status"]
    return dict(
        health=s.get("health"), dignity=s.get("dignity"), skill=s.get("skill"),
        network=s.get("network"), output=s.get("output"), level=s.get("level"),
        dur=s.get("duration_in_level"), wealth=s.get("wealth"), energy=s.get("energy"),
    )


def analyse(path):
    states = extract_states(path)
    acts = extract_actions(path)
    rows = []
    for obj in states:
        st = obj["current_state"]
        mo = st.get("time", {}).get("current_month")
        ev = obj.get("events", "") or ""
        b = dict(st_brief(st))
        b["month"] = mo
        b["title"] = (obj.get("current_event") or {}).get("title")
        b["nchoices"] = len(obj.get("choices") or [])
        b["promo"] = PROMO.search(ev)
        b["promo"] = (b["promo"].group(1), b["promo"].group(2)) if b["promo"] else None
        b["tier"] = BONUS.search(ev)
        b["tier"] = b["tier"].group(1) if b["tier"] else None
        b["failed"] = st.get("simulation_flags", {}).get("failed")
        b["reason"] = st.get("simulation_flags", {}).get("failure_reason")
        rows.append(b)
    return rows, acts


def n_ok(b, th=TH_L1):
    return (b["skill"] or 0) >= th["skill"] and (b["output"] or 0) >= th["output"] and (b["network"] or 0) >= th["network"]


def main():
    only = None
    if "--run" in sys.argv:
        only = sys.argv[sys.argv.index("--run") + 1]

    paths = sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl"))
    runs = []
    for p in paths:
        rd = Path(p).parent.name
        if only and only not in rd:
            continue
        rows, acts = analyse(Path(p))
        if not rows:
            continue
        runs.append((rd, rows, acts))

    print(f"=== 局数 {len(runs)} ===")

    # ---- M6 分组 ----
    promoted, notpromoted, noscore = [], [], []
    for rd, rows, acts in runs:
        m6 = [b for b in rows if b["month"] == 6 and b["promo"]]
        # 取 M6 上的状态（最新一条 month==6 且有 promo 的）的 status
        m6stat = [b for b in rows if b["month"] == 6]
        if not m6stat:
            noscore.append(rd); continue
        last6 = m6stat[-1]
        (promoted if last6["promo"] else notpromoted).append((rd, last6, rows, acts))

    print(f"M6 晋级 {len(promoted)} 局 / 未晋级 {len(notpromoted)} 局 / 无 M6 快照 {len(noscore)} 局")

    # ---- 门槛对齐 ----
    hit = 0
    mism = []
    for grp, name in ((promoted, "晋级"), (notpromoted, "未晋级")):
        for rd, b, _, _ in grp:
            ok = n_ok(b)
            good = (ok and name == "晋级") or ((not ok) and name == "未晋级")
            hit += good
            if not good:
                mism.append((rd, name, b["skill"], b["output"], b["network"], b["level"], b["promo"]))
    tot = len(promoted) + len(notpromoted)
    print(f"\n★ 门槛对齐：「三维全达标 ⟺ 晋级」命中 {hit}/{tot} = {hit/max(tot,1)*100:.1f}%")
    for r in mism:
        print("   不符:", r)

    # ---- 未晋级缺项 ----
    print("\n--- 未晋级局的缺项分布 ---")
    cnt = Counter()
    for rd, b, _, _ in notpromoted:
        miss = []
        if (b["skill"] or 0) < 8: miss.append("skill")
        if (b["output"] or 0) < 3: miss.append("output")
        if (b["network"] or 0) < 3: miss.append("network")
        cnt["+".join(miss) if miss else "(全达标却未晋级)"] += 1
        # 记录缺几点
    for k, v in cnt.most_common():
        print(f"   {k:22s} {v} 局")

    # ---- 关键：M5 月末 n/o 都达标、M6 却掉下来的局 ----
    print("\n--- ★ M5 末 n/o 双达标却在 M6 脱落（差额=1）的局 ---")
    drops = []
    for rd, b6, rows, acts in runs:
        m5 = [b for b in rows if b["month"] == 5]
        if not m5:
            continue
        last5 = m5[-1]
        if last5["network"] is None:
            continue
        # M5末 n>=3 且 o>=3，但 M6 结算 n<3 或 o<3
        cond_m5 = (last5["network"] or 0) >= 3 and (last5["output"] or 0) >= 3
        m6s = [b for b in rows if b["month"] == 6]
        if not m6s:
            continue
        l6 = m6s[-1]
        cond_m6 = (l6["network"] or 0) < 3 or (l6["output"] or 0) < 3
        if cond_m5 and cond_m6:
            drops.append((rd, last5, l6, rows, acts))

    print(f"   共 {len(drops)} 局\n")
    for rd, l5, l6, rows, acts in drops:
        print(f"■ {rd}")
        print(f"    M5末 S{l5['skill']} O{l5['output']} N{l5['network']}  →  M6  S{l6['skill']} O{l6['output']} N{l6['network']}  "
              f"level {l5['level']}→{l6['level']}  promo={l6['promo']}")
        # 列出该局 M4/M5/M6 的所有状态变化
        seq = [b for b in rows if b["month"] in (4, 5, 6)]
        prev = None
        for b in seq:
            if prev is not None:
                d = []
                for k in ("skill", "output", "network", "dignity", "health"):
                    if b[k] is not None and prev[k] is not None and b[k] != prev[k]:
                        d.append(f"{k}{prev[k]}→{b[k]}")
                if d:
                    print(f"      M{b['month']:<2} Δ {' '.join(d):45s} | {b['title']}")
            prev = b
        # 该局 M4/M5 的选择
        rel = [a for a in acts if any(x in a[2] for x in ("M4", "M5", "M6", "第4", "第5", "第6"))]
        for seq_, ch, notes in rel[:12]:
            print(f"        [seq{seq_}] choice={ch}  {notes}")
        print()

    # ---- 全量：M1..M8 三维轨迹（便于人工核）----
    if only:
        for rd, rows, acts in runs:
            print(f"\n=== {rd} 三维轨迹 ===")
            print(f"{'M':>3} {'S':>4} {'O':>4} {'N':>4} {'L':>6} {'dur':>4} {'tier':>5} {'promo':>10}  标题")
            for b in rows:
                if b["month"] is None or b["month"] > 8:
                    continue
                print(f"{b['month']:>3} {str(b['skill']):>4} {str(b['output']):>4} {str(b['network']):>4} "
                      f"{str(b['level']):>6} {str(b['dur']):>4} {str(b['tier']):>5} "
                      f"{str(b['promo']):>10}  {b['title']}")
            print("\n--- take_action 全量 ---")
            for seq_, ch, notes in acts:
                print(f"  [seq{seq_}] c={ch}  {notes}")


if __name__ == "__main__":
    main()
