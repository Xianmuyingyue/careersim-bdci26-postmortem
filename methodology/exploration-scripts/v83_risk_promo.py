#!/usr/bin/env python3
"""v8_3 vs v8_5：晋升节奏 + 爆雷控制（数据源 = 引擎 emulator_log，权威）。

权威标记（在 f4a7056f…log 中逐行确认）：
  [promotion] 晋升通知：半年组织评审通过，您已从 Lx 晋升至 Ly（…）。   ← 晋升
  [promotion] 升迁节奏过快，原有人脉圈还没消化…                        ← 晋升税（network−3）
  [warning]   之前的隐患好巧不巧一起炸了，最近半年的工作都打了水漂！      ← ★爆雷
  [talk]      【半年谈话】…                                            ← 谈话（结果在其后几行）
⚠️ 不能用 "引爆" 判爆雷——剧情文本里也有（"风险随时引爆"），会误判。
"""
import json
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
ELOG = os.path.join(REPO, ".career_sim_runner", "career_emu", "emulator_logs")
AB = os.path.join(REPO, "analysis", "ab")

MONTH_RE = re.compile(r"Month (\d+)")
PROMO_RE = re.compile(r"从 L(\d) 晋升至 L(\d)")
BURST = "之前的隐患好巧不巧一起炸了"
TAX = "升迁节奏过快"


def elog_of(run_dir):
    sc = os.path.join(OUT, run_dir, "score_report.json")
    if not os.path.exists(sc):
        return None
    sess = json.load(open(sc, encoding="utf-8")).get("session_id")
    p = os.path.join(ELOG, (sess or "") + ".log")
    return p if os.path.exists(p) else None


def scan(run_dir):
    p = elog_of(run_dir)
    if not p:
        return None
    r = {"promos": [], "bursts": [], "talks": [], "tax": []}
    cur = 0
    for line in open(p, encoding="utf-8", errors="replace"):
        m = MONTH_RE.search(line)
        if m:
            cur = int(m.group(1))
        if line.startswith("[promotion]"):
            pm = PROMO_RE.search(line)
            if pm:
                r["promos"].append((cur, "L%s→L%s" % (pm.group(1), pm.group(2))))
            elif TAX in line:
                r["tax"].append(cur)
        elif line.startswith("[warning]") and BURST in line:
            r["bursts"].append(cur)
        elif line.startswith("[talk]"):
            r["talks"].append(cur)
    return r


def rows(arm):
    tsv = os.path.join(AB, "results_%s.tsv" % arm)
    if not os.path.exists(tsv):
        return []
    return [l.split("\t") for l in open(tsv, encoding="utf-8").read().splitlines()[1:] if l.strip()]


def main():
    print("晋升节奏与爆雷控制对比（月 = 引擎 Month 口径，M6/M12/… = 评审窗）\n")
    hdr = "%-6s %-18s %-6s %-5s %-6s %-6s %-6s %s"
    print(hdr % ("arm", "run_dir", "score", "lvl", "终risk", "爆雷数", "爆雷月", "晋升时点"))
    print("-" * 118)
    summary = {}
    for arm in ("v8_3", "v8_5", "v8_4"):
        for c in rows(arm):
            run_dir, grade, score = c[0], c[2], c[3]
            lvl, risk, bursts = c[6], c[10], c[12]
            r = scan(run_dir)
            if not r:
                print(hdr % (arm, run_dir, score, lvl, risk, bursts, "-", "（无 log）"))
                continue
            bm = ",".join("M%d" % m for m in r["bursts"]) or "-"
            before = sum(1 for m in r["bursts"] if m < 42)
            after = len(r["bursts"]) - before
            print(hdr % (arm, run_dir, "%s %s" % (grade, score), lvl, risk, bursts, bm,
                         ",".join("%s@M%d" % (s, m) for m, s in r["promos"]) or "-"))
            print("       %-14s 爆雷：M42前 %d 次 / M42及以后 %d 次 | 晋升税(升迁过快)月：%s"
                  % ("", before, after, ",".join("M%d" % m for m in r["tax"]) or "无"))
            summary.setdefault(arm, []).append({
                "dir": run_dir, "score": float(score), "lvl": float(lvl),
                "risk": float(risk), "bursts": len(r["bursts"]),
                "before": before, "after": after,
                "windows": [m for m, s in r["promos"]],
            })

    print("\n" + "=" * 118)
    print("汇总")
    print("=" * 118)
    for arm, rs in summary.items():
        done = [x for x in rs if x["score"] > 30 or x["lvl"] >= 1]
        b = sum(x["bursts"] for x in rs)
        print("%-6s 局数 %d | 通关 %d | 平均分 %.2f | 终 risk 均值 %.2f | 爆雷合计 %d "
              "| M42 前爆雷 %d / M42 后 %d"
              % (arm, len(rs), sum(1 for x in rs if x["lvl"] >= 1 and x["dir"]), 
                 sum(x["score"] for x in rs) / len(rs), sum(x["risk"] for x in rs) / len(rs),
                 b, sum(x["before"] for x in rs), sum(x["after"] for x in rs)))


if __name__ == "__main__":
    main()
