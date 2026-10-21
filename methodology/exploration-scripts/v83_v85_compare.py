#!/usr/bin/env python3
"""对比 v8_3（冒烟 2 局）与 v8_5（7 局）：晋升节奏 + 爆雷控制。

数据源：outputs/九问/<dir>/replay-<dir>.md
抽取：① 每月段头；② 晋升通知（含目标职级）；③ 谈话结果；④ HR 风险提示档位；⑤ 爆雷文本。
只做分析，不写任何技能文件。
"""
import csv
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
AB = os.path.join(REPO, "analysis", "ab")

MONTH_RE = re.compile(r"^##\s*第\s*(\d+)\s*月")
PROMO_RE = re.compile(r"晋升通知[：:].*?从\s*L(\d)\s*晋升至\s*L(\d)")
# HR 风险提示四档（用词由引擎固定）
HINT = [
    ("问题还不大", "L1_mild"),
    ("积攒了不少风险", "L2_accum"),
    ("风险已经很高", "L3_critical"),
    ("随时可能出事", "L4plus_imminent"),
]


def sections(path):
    """把 replay 切成 [(month, [lines...])]，month 为该段所属播报月。"""
    out, cur, buf = [], None, []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = MONTH_RE.match(line)
        if m:
            if cur is not None:
                out.append((cur, buf))
            cur, buf = int(m.group(1)), []
            continue
        buf.append(line)
    if cur is not None:
        out.append((cur, buf))
    return out


def analyse(dirname):
    p = os.path.join(OUT, dirname, f"replay-{dirname}.md")
    if not os.path.exists(p):
        return None
    r = {"dir": dirname, "promos": [], "bursts": [], "hints": {}, "counts": {}}
    for month, lines in sections(p):
        blob = "\n".join(lines)
        for m in PROMO_RE.finditer(blob):
            r["promos"].append((month, "L%s→L%s" % (m.group(1), m.group(2))))
        for kw, lv in HINT:
            if kw in blob:
                r["hints"].setdefault(lv, []).append(month)
                r["counts"][lv] = r["counts"].get(lv, 0) + blob.count(kw)
        if "爆雷" in blob or "埋雷引爆" in blob or "信任危机" in blob:
            for kw in ("爆雷", "埋雷引爆", "信任危机"):
                if kw in blob:
                    r["bursts"].append((month, kw))
                    break
    return r


def main():
    rows = {}
    for arm in ("v8_3", "v8_5", "v8_4"):
        p = os.path.join(AB, "results_%s.tsv" % arm)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            rows[arm] = list(csv.DictReader(f, delimiter="\t"))

    for arm in ("v8_3", "v8_5"):
        print("=" * 100)
        print(arm, "（播报月口径，引擎 replay 月；技能月 = 播报月 + 1）")
        print("=" * 100)
        for row in rows.get(arm, []):
            d = row["run_dir"]
            a = analyse(d)
            sc = "%s %s" % (row["grade"], row["score"])
            print("\n【%s】%s  月数=%s  终职级=L%s  财富=%s  终 risk=%s  爆雷=%s"
                  % (d, sc, row["months"], row["raw_level"], row["raw_wealth"],
                     row["raw_risk_control"], row["bursts"]))
            if not a:
                print("   （无 replay）")
                continue
            print("   晋升时点(播报月/技能月)：",
                  ", ".join("M%s(M%s) %s" % (m, m + 1, s) for m, s in a["promos"]) or "无")
            print("   爆雷时点：", ", ".join("M%s(%s)" % (m, k) for m, k in a["bursts"]) or "无")
            print("   风险提示出现月：", {k: v for k, v in a["hints"].items()} or "无")
            print("   风险提示次数：", a["counts"] or "无")
    print("\n" + "=" * 100)
    print("对照表：晋升速度")
    print("=" * 100)
    hdr = "%-10s %-22s %-6s %-6s %s"
    print(hdr % ("arm", "dir", "sc", "lvl", "晋升时点(播报月)"))
    for arm in ("v8_3", "v8_5"):
        for row in rows.get(arm, []):
            a = analyse(row["run_dir"])
            if not a:
                continue
            print(hdr % (arm, row["run_dir"], row["score"], row["raw_level"],
                         ",".join("%s@M%s" % (s, m) for m, s in a["promos"]) or "-"))


if __name__ == "__main__":
    sys.exit(main())
