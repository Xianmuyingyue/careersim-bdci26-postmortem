"""逐月回合计序解剖：剧情回合 / 体力分配回合 / 主行动回合的先后顺序。

结论用途
--------
晋升评审读取的是「评审月最后一条决策结算后的状态」，所以：
    * 若「体力分配」排在当月剧情之后 ⇒ 评审前最后一次补救机会；
    * 若排在剧情之前 ⇒ 当月剧情一旦扣 network/output，评审必丢。
这决定了 M5/M11 两个月该怎么排兵布阵。
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

OUTROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".career_sim_runner", "career_emu", "outputs", "九问")

MON_RE = re.compile(r"^##\s*第\s*(\d+)\s*月")
TURN_RE = re.compile(r"^###\s*回合\s*(\d+)\s*·\s*(.+?)\s*$")
ENERGY_KW = ("季度体力", "体力行动分配")
MAIN_KW = ("主行动", "季度主行动")


def classify(title: str) -> str:
    if any(k in title for k in ENERGY_KW):
        return "E"
    if any(k in title for k in MAIN_KW):
        return "M"
    return "s"


def scan(run: str):
    d = os.path.join(OUTROOT, run)
    rp = [f for f in os.listdir(d) if f.startswith("replay-")][0]
    cur, months = None, {}
    for line in open(os.path.join(d, rp), encoding="utf-8"):
        m = MON_RE.match(line)
        if m:
            cur = int(m.group(1))
            months.setdefault(cur, [])
            continue
        t = TURN_RE.match(line)
        if t and cur:
            months[cur].append((int(t.group(1)), classify(t.group(2)), t.group(2)[:34]))
    return months


def main() -> None:
    runs = [a for a in sys.argv[1:] if not a.startswith("--")] or ["20260925T042320Z"]
    for run in runs:
        months = scan(run)
        print("=" * 104)
        print(f"{run}   总月数={max(months)}")
        print("=" * 104)
        for k in sorted(months):
            seq = "".join(x[1] for x in months[k])
            tot = len(months[k])
            flag = ""
            if k % 6 == 0:
                flag = "  <== 评审月（本月底结算）" if k != 0 else ""
            print(f"  M{k:>2} ({tot:>2}回) {seq}{flag}")
            if k <= 6:
                for n, kind, title in months[k]:
                    print(f"        #{n:<3} [{kind}] {title}")
        # 统计「评审月」末端回合类型
        cnt = Counter()
        for k in sorted(months):
            if k % 6 == 0 and k > 0:
                tail = "".join(x[1] for x in months[k][-3:])
                cnt[tail] += 1
        print(f"\n  评审月末 3 回合的类型串分布: {dict(cnt)}")


if __name__ == "__main__":
    main()
