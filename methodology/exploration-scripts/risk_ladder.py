"""逐局「风险阶梯 + 爆雷链路」重建（真值口径）。

为什么必须用真值
----------------
`hidden_risk` 在 replay 的 `**状态:**` 行里**不出现**（面板只给 HR 语气词），
所以只能从 HR 提示词反推桶位，再用官方 action_pool 的 `status_updates` 复原注入量。
HR 词 -> 桶：笑着=0 / 偷偷=1 / 皱着眉头=2 / 神情复杂=3 / 生气=≥4（RISK_LEVEL_MAP 索引）。

爆雷判据（failure_conditions/risk_burst.data）
    hidden_risk >= 5  -> hidden_risk 归 0、output 回滚到 6 个月前快照、dignity −2、wealth −2、hp −2
    hp 预算 2  -> 两次爆雷即「信任危机end」出局
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTROOT = os.path.join(ROOT, ".career_sim_runner", "career_emu", "outputs", "九问")
POOL = os.path.join(os.path.dirname(ROOT), "官方资料", "decoded_dev", "action_pool")

MON_RE = re.compile(r"^##\s*第\s*(\d+)\s*月")
TURN_RE = re.compile(r"^###\s*回合\s*(\d+)\s*·\s*(.+?)\s*$")
OPT_RE = re.compile(r"^-\s*\[(\d+)\]\s*(.+?)\s*$")
CH_RE = re.compile(r"^\*\*选择:\*\*\s*(?:\[(\d+)\])?\s*(.+?)\s*$")
HR_RE = re.compile(r"(笑着|偷偷|皱着眉头|神情复杂|生气)地?(?:跟你说|说)")
HR_CODE = {"笑着": 0, "偷偷": 1, "皱着眉头": 2, "神情复杂": 3, "生气": 4}


def load_pool():
    import glob
    import json
    by = {}
    for f in glob.glob(os.path.join(POOL, "*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for node, body in (d.get("nodes") or {}).items():
            ch = body.get("choices") or []
            if ch:
                by[frozenset(c.get("action", "") for c in ch)] = {
                    "event": d.get("event_name"), "node": node, "choices": ch}
    return by


def scan(run: str, pool: dict) -> None:
    d = os.path.join(OUTROOT, run)
    rp = [f for f in os.listdir(d) if f.startswith("replay-")][0]
    cur, turns = None, []
    hr_by_month = {}
    for line in open(os.path.join(d, rp), encoding="utf-8"):
        m = MON_RE.match(line)
        if m:
            cur = int(m.group(1))
            continue
        t = TURN_RE.match(line)
        if t and cur:
            turns.append([cur, int(t.group(1)), t.group(2), [], None])
            continue
        if turns and cur:
            o = OPT_RE.match(line)
            if o:
                turns[-1][3].append(o.group(2))
                continue
            c = CH_RE.match(line)
            if c:
                turns[-1][4] = (c.group(2) or "").strip()
                continue
        h = HR_RE.search(line)
        if h and cur and cur not in hr_by_month:
            hr_by_month[cur] = (HR_CODE[h.group(1)], h.group(1))

    print("=" * 108)
    print(f"{run}   HR 语气阶梯（真值口径，hidden_risk 桶位）")
    print("=" * 108)
    risk = 0.0
    bursts, injected = [], []
    tol = 0
    for mo, n, title, opts, choice in turns:
        node = pool.get(frozenset(opts)) if opts else None
        dv = {}
        if node and choice:
            for c in node["choices"]:
                if c.get("action", "").strip() == choice:
                    dv = c.get("status_updates") or {}
                    break
        if not dv and opts:
            tol += 1
        dr = float(dv.get("HiddenRisk", 0))
        if dr:
            injected.append((mo, n, dr, title[:26], choice[:30]))
        risk = max(0.0, risk + dr)
        if risk >= 5:
            bursts.append((mo, n, title[:30], choice[:34]))
            risk = 0.0
    print(f"  重建峰值检查：注入事件 {len(injected)} 次，总注入 {sum(x[2] for x in injected):+.0f}，"
          f"未匹配回合 {tol}")
    ct = Counter()
    for mo in sorted(hr_by_month):
        code, word = hr_by_month[mo]
        ct[word] += 1
    print("  HR 语气分布: " + ", ".join(f"{k}×{v}" for k, v in ct.most_common()))
    print("\n  风险注入明细（HiddenRisk != 0 的选择）:")
    for mo, n, dr, title, ch in injected:
        flag = "  ★★★爆雷" if dr >= 3 else ""
        print(f"    M{mo:>2} #{n:<3} ΔRisk{dr:+.0f}  {title:<28} → {ch}{flag}")
    print(f"\n  推算爆雷次数 = {len(bursts)}")
    for b in bursts:
        print(f"    M{b[0]} #{b[1]} {b[2]} → {b[3]}")


if __name__ == "__main__":
    pool = load_pool()
    runs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not runs:
        runs = ["20260925T043821Z"]
    for r in runs:
        scan(r, pool)
