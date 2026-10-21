#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把所有「【半年谈话】评审快照」抽出来，看它相对【前一快照】的 Δ 属性 + 谈话措辞。

核心问题：M6 评审读到的状态 ≠ M5 月末状态。这中间的变化是谁造成的？
  · 若与谈话措辞相关（批评→扣 network）⇒ 是「谈话效应」，可预测。
  · 若非（同类措辞扣不同）⇒ 是「隐藏随机扰动」，不可控，只能在分配上留余量。
"""
import json, glob, re, sys
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
_DEC = json.JSONDecoder()
KEYS = ("skill", "output", "network", "dignity", "health")
TALK_RE = re.compile(r"【半年谈话】(.*?)。?Leader")
BONUS = re.compile(r"半年绩效奖金（([SABCD])）")
RISK = {
    "还不错": 0, "有点风险": 1, "自己好好处理好": 2, "皱着眉头": 2,
    "自求多福": 4, "神情复杂": 4, "早干啥去了": 5, "生气": 5, "偷偷": 1,
}


def raw_states(path):
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
                        ev=obj.get("events") or "",
                    ))
            i = s.find('{"current_state":{', i + 1)
    return out


def classify_risk(ev):
    for k, v in RISK.items():
        if k in ev:
            return v
    return None


def main():
    paths = sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl"))
    rows = []
    for p in paths:
        rd = Path(p).parent.name
        seq = raw_states(Path(p))
        for idx, s in enumerate(seq):
            ev = s["ev"]
            if "【半年谈话】" not in ev or "绩效奖金" not in ev:
                continue
            # 前一快照
            prev = seq[idx - 1] if idx > 0 else None
            d = {}
            if prev:
                for k in KEYS:
                    va, vb = prev["st"].get(k), s["st"].get(k)
                    if va is not None and vb is not None and va != vb:
                        d[k] = vb - va
            bonus = BONUS.search(ev)
            talk = TALK_RE.search(ev)
            rows.append(dict(
                rd=rd, month=s["month"], level=s["st"].get("level"),
                delta=d, prev_month=prev["month"] if prev else None,
                tier=bonus.group(1) if bonus else None,
                risk=classify_risk(ev),
                talk=(talk.group(1)[:60] if talk else ""),
                S=s["st"].get("skill"), O=s["st"].get("output"), N=s["st"].get("network"),
                pS=prev["st"].get("skill") if prev else None,
                pO=prev["st"].get("output") if prev else None,
                pN=prev["st"].get("network") if prev else None,
            ))

    print(f"=== 评审快照总数 {len(rows)} ===")
    # 按月统计 delta 分布
    bym = defaultdict(Counter)
    for r in rows:
        if r["prev_month"] == r["month"] - 1:
            bym[f"M{r['month']}"][tuple(sorted(r["delta"].items()))] += 1
    for m in sorted(bym, key=lambda x: int(x[1:])):
        c = bym[m]
        print(f"\n{m}  (n={sum(c.values())})")
        for k, v in c.most_common(6):
            print(f"    {v:>4}  {dict(k)}")

    print("\n\n=== M6 评审逐局：Δ 与谈话措辞 ===")
    print(f"{'run':<22} {'Δ':<40} {'tier':>4} {'risk':>4}  talk")
    for r in rows:
        if r["month"] != 6:
            continue
        d = " ".join(f"{k}{'+' if v>0 else ''}{v}" for k, v in sorted(r["delta"].items())) or "—"
        print(f"{r['rd']:<22} {d:<40} {str(r['tier']):>4} {str(r['risk']):>4}  {r['talk']}")

    # 关键交叉：Δnetwork 是否随 risk / talk 变化
    print("\n\n=== M6：Δnetwork 的分组 ===")
    g = defaultdict(list)
    for r in rows:
        if r["month"] != 6 or r["prev_month"] != 5:
            continue
        g[str(r["risk"])].append(r["delta"].get("network", 0))
    for k in sorted(g, key=lambda x: (x == "None", x)):
        v = g[k]
        print(f"  risk={k:<6} n={len(v):<3} Δnetwork 均值 {sum(v)/len(v):+.2f}  分布 {Counter(v).most_common()}")

    print("\n=== M6：Δnetwork 是否与「谈话是否为正面评价」相关 ===")
    pos = ("做得好", "不错", "认可", "欣赏", "表扬", "亮眼", "超出预期")
    neg = ("不好不坏", "还需要", "观察名单", "不够", "欠缺", "失望", "注意")
    gg = defaultdict(list)
    for r in rows:
        if r["month"] != 6 or r["prev_month"] != 5:
            continue
        t = r["talk"]
        lab = "正面" if any(w in t for w in pos) else ("中性/负面" if any(w in t for w in neg) else "其它")
        gg[lab].append(r["delta"].get("network", 0))
    for k, v in gg.items():
        print(f"  {k:<8} n={len(v):<3} Δnetwork 均值 {sum(v)/len(v):+.2f}  {Counter(v).most_common()}")

    # 汇总：M6 评审点是否达标 vs 前一快照是否达标
    print("\n\n=== ★ M6 评审点达标 vs M5 月末达标 的迁移矩阵（N/O 两维）===")
    mat = Counter()
    for r in rows:
        if r["month"] != 6 or r["prev_month"] != 5:
            continue
        prev_ok = (r["pN"] or 0) >= 3 and (r["pO"] or 0) >= 3
        now_ok = (r["N"] or 0) >= 3 and (r["O"] or 0) >= 3
        mat[(prev_ok, now_ok)] += 1
    for k in sorted(mat, key=lambda x: (not x[0], not x[1])):
        print(f"  M5末达标={k[0]!s:<5} → M6达标={k[1]!s:<5}: {mat[k]} 局")

    print("\n=== ★ M6 评审点达标 vs skill 维 ===")
    mats = Counter()
    for r in rows:
        if r["month"] != 6 or r["prev_month"] != 5:
            continue
        mats[((r["pS"] or 0) >= 8, (r["S"] or 0) >= 8)] += 1
    for k in sorted(mats, key=lambda x: (not x[0], not x[1])):
        print(f"  M5末 skill达标={k[0]!s:<5} → M6 skill达标={k[1]!s:<5}: {mats[k]} 局")


if __name__ == "__main__":
    main()
