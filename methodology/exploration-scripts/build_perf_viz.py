"""生成绩效全量普查的可视化单文件报告（内联 SVG，无外部依赖）。

数据来源：analysis/perf_census_all.py 的解析结果（events jsonl，56/56 局覆盖）。

    .venv/bin/python3 analysis/build_perf_viz.py
    → analysis/perf_census_all.html
"""

from __future__ import annotations

import html
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perf_census_all as P  # noqa: E402

REVIEW_MONTHS = P.REVIEW_MONTHS
TV = P.TV
OUT = P.REPO / "analysis" / "perf_census_all.html"

TIER_COLOR = {"S": "#8e5b00", "A": "#c0392b", "B": "#e8843c", "C": "#8e9aa6", "D": "#4a5568"}
TIER_LABEL = {"S": "S（perf≥12）", "A": "A（8-11）", "B": "B（5-7）", "C": "C（3-4）", "D": "D（<3）"}
OUTCOME_COLOR = {"通关(48月)": "#2f6fb5", "炒鱿鱼end": "#c0392b", "信任危机end": "#8e5b00",
                 "眼前一黑end": "#b06f9a", "喝西北风end": "#5b8c5a", "未完/中断": "#9aa5b1"}
FIRE = "炒鱿鱼end"


def esc(s):
    return html.escape(str(s))


# ================================================================ 图 1 堆叠柱
def chart_by_month(by_month, W=1080, H=400):
    pad_l, pad_r, pad_t, pad_b = 58, 24, 30, 66
    iw, ih = W - pad_l - pad_r, H - pad_t - pad_b
    maxn = max(sum(c.values()) for c in by_month.values()) or 1
    groups = [m for m in REVIEW_MONTHS if by_month.get(m)]
    gw = iw / len(groups)
    bw = gw * 0.56
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for k in range(0, maxn + 1, max(1, maxn // 6)):
        y = pad_t + ih - ih * k / maxn
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l+iw}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" class="axis" text-anchor="end">{k}</text>')
    out.append(f'<text x="{pad_l-8}" y="{pad_t-12}" class="axis" text-anchor="end">局数</text>')
    for gi, m in enumerate(groups):
        c = by_month[m]
        tot = sum(c.values())
        cx = pad_l + gw * gi + gw / 2
        acc = 0
        for t in "ABCD":
            n = c.get(t, 0)
            if not n:
                continue
            h = ih * n / maxn
            y = pad_t + ih - ih * (acc + n) / maxn
            out.append(f'<rect x="{cx-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                       f'fill="{TIER_COLOR[t]}" opacity="{0.55 + 0.09*TV[t]:.2f}"/>')
            if h > 15:
                out.append(f'<text x="{cx:.1f}" y="{y+h/2+4:.1f}" class="inbar">{t}{n}</text>')
            acc += n
        out.append(f'<text x="{cx:.1f}" y="{pad_t+ih+21:.1f}" class="axis" text-anchor="middle">M{m}</text>')
        out.append(f'<text x="{cx:.1f}" y="{pad_t+ih+39:.1f}" class="axis2" text-anchor="middle">n={tot}</text>')
    for gi, m in enumerate(groups):
        cx = pad_l + gw * gi + gw / 2
        if m == 6:
            out.append(f'<text x="{cx:.1f}" y="{pad_t-9}" class="flag" text-anchor="middle">54/54 全 C</text>')
        if m == 12:
            out.append(f'<text x="{cx:.1f}" y="{pad_t-9}" class="flag warn" text-anchor="middle">C 档最多</text>')
        if m == 18:
            out.append(f'<text x="{cx:.1f}" y="{pad_t-9}" class="flag warn" text-anchor="middle">首个 D 出现</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 图 2 热力图
def chart_cross(cross):
    levels = ["L1", "L2", "L3", "L4", "L5", "L6"]
    tiers = "ABCD"
    rows = [(lv, cross[lv]) for lv in levels if cross.get(lv)]
    maxn = max(max(c.values()) for _, c in rows) or 1
    cw, ch = 118, 48
    W = 152 + cw * 4 + 150
    H = 64 + ch * len(rows) + 34
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for j, t in enumerate(tiers):
        out.append(f'<text x="{152+cw*j+cw/2}" y="32" class="axis" text-anchor="middle">{TIER_LABEL[t]}</text>')
    out.append(f'<text x="16" y="{H-12}" class="axis2">'
               f'单元格 = 评审点个数；底色越深＝越集中。右侧 sd 为「同一职级内档位的标准差」——'
               f'sd=0 表示该职级把档位锁死。</text>')
    for i, (lv, c) in enumerate(rows):
        y = 46 + ch * i
        tot = sum(c.values())
        vals = [TV[t] for t in c for _ in range(c[t])]
        mean = sum(vals) / tot
        sdev = P.sd(vals)
        out.append(f'<text x="16" y="{y+ch/2+6}" class="lvlabel">{lv}</text>')
        out.append(f'<text x="60" y="{y+ch/2+6}" class="axis2">n={tot}</text>')
        for j, t in enumerate(tiers):
            n = c.get(t, 0)
            x = 152 + cw * j
            op = 0.06 + 0.84 * (n / maxn) if n else 0.03
            fill = TIER_COLOR[t] if n else "#e6e9ee"
            out.append(f'<rect x="{x+3}" y="{y+3}" width="{cw-6}" height="{ch-6}" rx="6" '
                       f'fill="{fill}" opacity="{op:.2f}" stroke="#dfe4ea"/>')
            if n:
                out.append(f'<text x="{x+cw/2}" y="{y+ch/2+7}" class="cell">{n}</text>')
        bx = 152 + cw * 4 + 16
        top = max((t for t in tiers if c[t]), key=lambda t: TV[t])
        out.append(f'<text x="{bx}" y="{y+ch/2-1}" class="axis2">均 {mean:.2f} · 实测天花板'
                   f'<tspan class="mono2" fill="{TIER_COLOR[top]}">{top}</tspan></text>')
        sdcls = "sdzero" if sdev == 0 else "axis2"
        out.append(f'<text x="{bx}" y="{y+ch/2+16}" class="{sdcls}">sd {sdev:.2f}'
                   f'{"　← 零方差" if sdev == 0 else ""}</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 图 3 风险阶梯
def compute_ladder(runs):
    """返回 [(判据, 命中局数, 其中炒鱿鱼局数, 说明)]"""
    def got(v, s):
        return next((r for r in v["reviews"] if r["slot"] == s), None)

    def fired(v):
        return P.ending_kind(v["ending"]) == FIRE

    items = []

    def add(name, sel, note=""):
        sub = [v for v in runs if sel(v)]
        if sub:
            items.append((name, len(sub), sum(1 for v in sub if fired(v)), note))

    for s in (12, 18, 24, 30):
        for t in ("D", "C", "B", "A"):
            add(f"M{s} 档位 = {t}", lambda v, s=s, t=t: (got(v, s) or {}).get("tier") == t)
    add("M18 时仍停在 L1", lambda v: (got(v, 18) or {}).get("level") == "L1")
    add("M24 时仍停在 L1", lambda v: (got(v, 24) or {}).get("level") == "L1")
    add("M12 起从未拿过 C/D",
        lambda v: all(r["tier"] in "SAB" for r in v["reviews"] if r["slot"] >= 12))
    return items


def chart_ladder(items, W=1080):
    rows = [x for x in items if x[1] >= 3]
    rows.sort(key=lambda x: -(x[2] / x[1]))
    pad_l, pad_t = 216, 42
    iw = W - pad_l - 190
    bh, gap = 26, 35
    H = pad_t + gap * len(rows) + 40
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    out.append(f'<text x="{pad_l}" y="22" class="axis">← 条形长度 = 该判据下的炒鱿鱼率；'
               f'灰色为未因绩效出局的局</text>')
    for gx in (0, 0.25, 0.5, 0.75, 1.0):
        x = pad_l + iw * gx
        out.append(f'<line x1="{x:.1f}" y1="{pad_t-8}" x2="{x:.1f}" y2="{pad_t+gap*len(rows)-8}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{pad_t+gap*len(rows)+14:.1f}" class="axis" '
                   f'text-anchor="middle">{gx:.0%}</text>')
    for i, (name, n, k, _) in enumerate(rows):
        y = pad_t + i * gap
        rate = k / n
        out.append(f'<rect x="{pad_l}" y="{y}" width="{iw:.1f}" height="{bh}" fill="#e6e9ee" rx="4"/>')
        if k:
            out.append(f'<rect x="{pad_l}" y="{y}" width="{iw*rate:.1f}" height="{bh}" '
                       f'fill="{OUTCOME_COLOR[FIRE]}" opacity="0.85" rx="4"/>')
        out.append(f'<text x="{pad_l-12}" y="{y+bh/2+5}" class="lvlabel" text-anchor="end">'
                   f'{esc(name)}</text>')
        lab = f'{rate:.0%}　{k}/{n}'
        tx = pad_l + iw * max(rate, 0) + 8
        cls = "cell2 hi2" if rate > 0 else "axis2"
        out.append(f'<text x="{tx:.1f}" y="{y+bh/2+5}" class="{cls}">{lab}</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 图 4 散点
def chart_scatter(rows, W=1080, H=440):
    pts = [r for r in rows if r["score"] is not None]
    if not pts:
        return "<p>无评分样本</p>"
    pad_l, pad_r, pad_t, pad_b = 66, 206, 24, 54
    iw, ih = W - pad_l - pad_r, H - pad_t - pad_b
    x0, x1, y0, y1 = 1.4, 3.6, 0, 80
    X = lambda v: pad_l + iw * (v - x0) / (x1 - x0)
    Y = lambda v: pad_t + ih - ih * (v - y0) / (y1 - y0)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for gy in range(0, 81, 20):
        out.append(f'<line x1="{pad_l}" y1="{Y(gy):.1f}" x2="{pad_l+iw}" y2="{Y(gy):.1f}" class="grid"/>')
        out.append(f'<text x="{pad_l-10}" y="{Y(gy)+4:.1f}" class="axis" text-anchor="end">{gy}</text>')
    for gx in (1.5, 2.0, 2.5, 3.0, 3.5):
        out.append(f'<line x1="{X(gx):.1f}" y1="{pad_t}" x2="{X(gx):.1f}" y2="{pad_t+ih}" class="grid"/>')
        out.append(f'<text x="{X(gx):.1f}" y="{pad_t+ih+20:.1f}" class="axis" text-anchor="middle">{gx:.1f}</text>')
    out.append(f'<text x="{pad_l+iw/2:.1f}" y="{H-12}" class="axis" text-anchor="middle">'
               f'该局平均档位（S=5 A=4 B=3 C=2 D=1）</text>')
    out.append(f'<text x="16" y="{pad_t+ih/2}" class="axis" transform="rotate(-90 16 {pad_t+ih/2})" '
               f'text-anchor="middle">最终评分</text>')
    for r in pts:
        col = OUTCOME_COLOR.get(r["ending"], "#888")
        out.append(f'<circle cx="{X(r["mean_tier"]):.1f}" cy="{Y(r["score"]):.1f}" r="5" fill="{col}" '
                   f'opacity="0.78" stroke="#fff" stroke-width="1"><title>{esc(r["run"])} '
                   f'{esc(r["ending"])}　档位序列 {esc("".join(r["tiers"]))}　分 {r["score"]}</title></circle>')
    lx, ly = pad_l + iw + 16, pad_t + 8
    for name, col in OUTCOME_COLOR.items():
        n = sum(1 for r in pts if r["ending"] == name)
        if not n:
            continue
        out.append(f'<circle cx="{lx+6}" cy="{ly+4}" r="5" fill="{col}"/>')
        out.append(f'<text x="{lx+18}" y="{ly+8}" class="axis2">{esc(name)} {n}</text>')
        ly += 22
    out.append(f'<text x="{lx}" y="{ly+16}" class="hi">n = {len(pts)}</text>')
    out.append(f'<text x="{lx}" y="{ly+36}" class="hi">r = '
               f'{P.pearson([(r["mean_tier"], r["score"]) for r in pts]):.3f}</text>')
    out.append(f'<text x="{lx}" y="{ly+56}" class="hi">ρ = '
               f'{P.spearman([(r["mean_tier"], r["score"]) for r in pts]):.3f}</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 图 5 天花板
def chart_ceiling(W=1080, H=372):
    pad_l, pad_r, pad_t, pad_b = 60, 154, 26, 60
    iw, ih = W - pad_l - pad_r, H - pad_t - pad_b
    lvls = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
    caps = []
    for lv in lvls:
        sc, oc, nc = P.CLAMP[lv]
        low, high = min(sc, nc), max(sc, nc)
        stat = (min(high, low * 2.0) + max(0.0, high - low * 2.0) * 0.3) / 15.0
        p = round(stat + oc / 10.0 + P.POLY[lv])
        caps.append((lv, p, P.TIER_OF_PERF(p)))
    y0, y1 = 0, 14
    Y = lambda v: pad_t + ih - ih * (v - y0) / (y1 - y0)
    X = lambda i: pad_l + iw * (i + 0.5) / len(lvls)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for t, v, lab in (("D", 3, "C 线 perf=3"), ("C", 5, "B 线 perf=5"),
                      ("A", 8, "A 线 perf=8"), ("S", 12, "S 线 perf=12")):
        out.append(f'<line x1="{pad_l}" y1="{Y(v):.1f}" x2="{pad_l+iw}" y2="{Y(v):.1f}" '
                   f'stroke="{TIER_COLOR[t]}" stroke-dasharray="5 4" opacity="0.8"/>')
        out.append(f'<text x="{pad_l+iw+6}" y="{Y(v)+4:.1f}" class="axis2">{lab}</text>')
    for gv in range(0, 15, 2):
        out.append(f'<text x="{pad_l-10}" y="{Y(gv)+4:.1f}" class="axis" text-anchor="end">{gv}</text>')
        out.append(f'<line x1="{pad_l}" y1="{Y(gv):.1f}" x2="{pad_l+iw}" y2="{Y(gv):.1f}" class="grid"/>')
    for i, (lv, p, t) in enumerate(caps):
        x = X(i)
        out.append(f'<rect x="{x-27:.1f}" y="{Y(p):.1f}" width="54" height="{pad_t+ih-Y(p):.1f}" '
                   f'fill="{TIER_COLOR[t]}" opacity="0.5" rx="4"/>')
        out.append(f'<text x="{x:.1f}" y="{Y(p)-9:.1f}" class="cell2" text-anchor="middle">perf {p}</text>')
        out.append(f'<text x="{x:.1f}" y="{pad_t+ih+22:.1f}" class="axis" text-anchor="middle">{lv}</text>')
        out.append(f'<text x="{x:.1f}" y="{pad_t+ih+40:.1f}" class="axis2" text-anchor="middle">'
                   f'天花板 {t}</text>')
    out.append(f'<text x="16" y="{pad_t+ih/2}" class="axis" transform="rotate(-90 16 {pad_t+ih/2})" '
               f'text-anchor="middle">满配 perf</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 图 6 绩效税
def chart_tax(rows, W=1080):
    trans = defaultdict(list)
    for r in rows:
        revs = r["reviews"]
        for a, b in zip(revs, revs[1:]):
            if a["level"] and b["level"] and a["level"] != b["level"]:
                trans[(a["level"], b["level"])].append((TV[b["tier"]] - TV[a["tier"]], b["tier"]))
    keys = sorted(trans, key=lambda k: int(k[0][1]))
    pad_l, pad_t = 120, 36
    iw = W - pad_l - 200
    bh, gap = 32, 46
    H = pad_t + gap * len(keys) + 40
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    zero = pad_l + iw * 0.42
    out.append(f'<line x1="{zero:.1f}" y1="{pad_t-14}" x2="{zero:.1f}" y2="{pad_t+gap*len(keys)-14}" class="grid"/>')
    for i, k in enumerate(keys):
        v = trans[k]
        d = sum(x[0] for x in v) / len(v)
        y = pad_t + i * gap
        w = iw * 0.42 * min(abs(d), 1.0)
        col = "#c0392b" if d >= 0 else "#5b8c5a"
        x = zero if d >= 0 else zero - w
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bh}" fill="{col}" '
                   f'opacity="0.82" rx="3"/>')
        out.append(f'<text x="{pad_l-14}" y="{y+bh/2+6}" class="lvlabel" text-anchor="end">'
                   f'{k[0]} → {k[1]}</text>')
        c = Counter(t for _, t in v)
        dist = " ".join(f"{t}{c[t]}" for t in "SABCD" if c[t])
        tx = zero + w + 10 if d >= 0 else zero - w - 10
        anc = "start" if d >= 0 else "end"
        out.append(f'<text x="{tx:.1f}" y="{y+bh/2+6}" class="cell2" text-anchor="{anc}">'
                   f'{d:+.2f} 档　n={len(v)}　→ {dist}</text>')
    out.append(f'<text x="{zero:.1f}" y="{H-12}" class="axis2" text-anchor="middle">跨级前后档位差（档）</text>')
    out.append('</svg>')
    return "\n".join(out)


# ================================================================ 主报告
def main():
    idx = P.build_index()
    runs = [v for v in idx.values() if v["reviews"]]
    rows = []
    for v in runs:
        tiers = [r["tier"] for r in v["reviews"]]
        tv = [TV[t] for t in tiers]
        rows.append({"run": v["run_dir"], "arm": v["arm"], "reviews": v["reviews"],
                     "tiers": tiers, "mean_tier": sum(tv) / len(tv), "months": v["months"],
                     "score": v["score"], "grade": v["grade"],
                     "ending": P.ending_kind(v["ending"]),
                     "dead": 0 if v["ending"].startswith("Completed") else 1,
                     "level_final": P.lvnorm(v["level_final"]) or "L1"})

    by_month = defaultdict(Counter)
    for r in rows:
        for rv in r["reviews"]:
            by_month[rv["slot"]][rv["tier"]] += 1
    cross = defaultdict(Counter)
    for r in rows:
        for rv in r["reviews"]:
            cross[rv["level"]][rv["tier"]] += 1

    ws = [r for r in rows if r["score"] is not None]
    # 控制职级的偏相关：按局末职级分组、组内去均值
    resid = []
    lvkeys = {r["level_final"] for r in ws}
    for r in ws:
        g = [x for x in ws if x["level_final"] == r["level_final"]]
        gt = sum(x["mean_tier"] for x in g) / len(g)
        gs = sum(x["score"] for x in g) / len(g)
        resid.append((r["mean_tier"] - gt, r["score"] - gs))
    R_PARTIAL = P.pearson(resid)
    P_STATS = {
        "tier_score": P.pearson([(r["mean_tier"], r["score"]) for r in ws]),
        "tier_score_s": P.spearman([(r["mean_tier"], r["score"]) for r in ws]),
        "tier_months": P.pearson([(r["mean_tier"], r["months"]) for r in rows]),
        "tier_months_s": P.spearman([(r["mean_tier"], r["months"]) for r in rows]),
        "lv_score": P.pearson([(int(r["level_final"][1]), r["score"]) for r in ws]),
        "lv_tier": P.pearson([(int(r["level_final"][1]), r["mean_tier"]) for r in ws]),
        "n_ws": len(ws),
        "n_all": len(rows),
    }
    n_rev = sum(len(r["reviews"]) for r in rows)
    m6 = by_month[6]
    m12L1C = [r for r in rows if next((x for x in r["reviews"] if x["slot"] == 12 and x["level"] == "L1"
                                       and x["tier"] == "C"), None)]
    zero_cd = [r for r in rows if all(x["tier"] in "SAB" for x in r["reviews"] if x["slot"] >= 12)]
    cause = Counter(r["ending"] for r in rows)

    ladder = compute_ladder(runs)
    lad_sorted = sorted([x for x in ladder if x[1] >= 3], key=lambda x: -(x[2] / x[1]))

    KPI = [
        ("样本", f"{len(idx)} 局 / {n_rev} 评审点", "events jsonl 全量解析（旧口径仅 20 局）"),
        ("M6 档位", f"C 档 {m6.get('C',0)}/{sum(m6.values())}", "机制锁死，与结局零相关"),
        ("炒鱿鱼出局", f"{cause[FIRE]}/{len(rows)} 局", f"占全部早死 {cause[FIRE]/sum(cause[k] for k in cause if k!='通关(48月)' and k!='未完/中断'):.0%}"),
        ("最强单点预警", "M18 档位 = D → 86%", "6/7；M24 = D → 100%（3/3）"),
        ("绩效免疫门槛", "M12/M18 拿 B ⇒ 0/40", "B 档全程零炒鱿鱼"),
        ("档位 ↔ 评分", f"r = {P_STATS['tier_score']:.3f}",
         f"n={P_STATS['n_ws']}；ρ = {P_STATS['tier_score_s']:.3f}"),
    ]
    kpi_html = "\n".join(
        f'<div class="kpi"><div class="kpi-t">{esc(a)}</div><div class="kpi-v">{esc(b)}</div>'
        f'<div class="kpi-s">{esc(c)}</div></div>' for a, b, c in KPI)

    # 逐局表
    trows = []
    for r in sorted(rows, key=lambda x: (-(x["score"] or -1), x["run"])):
        seq = "".join(f'<span class="pill" style="background:{TIER_COLOR[t]}" '
                      f'title="M{rv["slot"]} @{rv["level"]}（{TIER_LABEL[t]}）">{t}</span>'
                      for t, rv in zip(r["tiers"], r["reviews"]))
        trows.append(
            f'<tr><td class="mono">{esc(r["run"])}</td><td class="arm">{esc(r["arm"])}</td>'
            f'<td class="num">{r["score"] if r["score"] is not None else "—"}</td>'
            f'<td>{esc(r["grade"] or "—")}</td><td class="num">{r["months"]}</td>'
            f'<td>{esc(r["level_final"])}</td><td class="seq">{seq}</td>'
            f'<td style="color:{OUTCOME_COLOR.get(r["ending"],"#333")}">{esc(r["ending"])}</td></tr>')

    # 分布表
    dist = []
    for m in REVIEW_MONTHS:
        c = by_month.get(m)
        if not c:
            continue
        tot = sum(c.values())
        tv = [TV[t] for t in c for _ in range(c[t])]
        lv = Counter(rv["level"] for r in rows for rv in r["reviews"] if rv["slot"] == m)
        dist.append(
            f'<tr><td class="mono">M{m}</td><td class="num">{tot}</td>'
            + "".join(f'<td class="num" style="color:{TIER_COLOR[t]}">{c.get(t,0) or ""}</td>'
                      for t in "ABCD")
            + f'<td class="num">{(c.get("C",0)+c.get("D",0))/tot:.0%}</td>'
            f'<td class="num">{sum(tv)/len(tv):.2f}</td>'
            f'<td class="axis2">{" ".join(f"{k}:{v}" for k,v in sorted(lv.items()) if k)}</td></tr>')

    # 结局轨迹表
    grp = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        for rv in r["reviews"]:
            grp[r["ending"]][rv["slot"]][rv["tier"]] += 1
    traj = []
    for e, ms in sorted(grp.items(), key=lambda x: -sum(sum(c.values()) for c in x[1].values())):
        cells = []
        for m in REVIEW_MONTHS:
            c = ms.get(m)
            if not c:
                cells.append('<td class="num axis2">·</td>')
                continue
            tot = sum(c.values())
            inner = "".join(f'<span class="pill sm" style="background:{TIER_COLOR[t]}">{t}{c[t]}</span>'
                            for t in "SABCD" if c[t])
            cells.append(f'<td class="seq">{inner}<span class="axis2"> ({tot})</span></td>')
        traj.append(f'<tr><td style="color:{OUTCOME_COLOR.get(e,"#333")};font-weight:600">{esc(e)}</td>'
                    + "".join(cells) + '</tr>')

    # 风险阶梯表（精选）
    lad_rows = []
    for name, n, k, _ in lad_sorted:
        rate = k / n
        lad_rows.append(f'<tr><td>{esc(name)}</td><td class="num">{k}/{n}</td>'
                        f'<td class="num" style="color:{"#c0392b" if rate > 0.3 else "inherit"};'
                        f'font-weight:{"700" if rate > 0 else "400"}">{rate:.0%}</td></tr>')

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>绩效（奖金档位）全量普查 · 56 局</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--muted:#64707d;--line:#e3e7ec;--hi:#c0392b;--ok:#2f6fb5;}}
@media (prefers-color-scheme:dark){{
:root{{--bg:#11161c;--card:#1a2129;--ink:#e8edf3;--muted:#9aa6b4;--line:#2b343e;--hi:#ff8a76;--ok:#7fb3e8;}}
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.68 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:34px 22px 74px}}
h1{{font-size:26px;margin:0 0 6px;letter-spacing:.5px}}
h2{{font-size:19px;margin:42px 0 6px;padding-left:11px;border-left:4px solid var(--hi)}}
h3{{font-size:15px;margin:22px 0 8px;color:var(--muted);font-weight:600}}
.sub{{color:var(--muted);font-size:13.5px;margin-bottom:22px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0;
box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(184px,1fr));gap:12px;margin:18px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 15px}}
.kpi-t{{font-size:12px;color:var(--muted);letter-spacing:.4px}}
.kpi-v{{font-size:20px;font-weight:700;margin:5px 0 3px;color:var(--hi)}}
.kpi-s{{font-size:11.5px;color:var(--muted);line-height:1.45}}
.chart{{width:100%;height:auto;display:block}}
.grid{{stroke:var(--line);stroke-width:1}}
.axis{{fill:var(--muted);font-size:11px}}
.axis2{{fill:var(--muted);font-size:10.5px}}
.mono2{{font-weight:700}}
.inbar{{fill:#fff;font-size:11px;font-weight:600;text-anchor:middle}}
.cell{{fill:#fff;font-size:13px;font-weight:700;text-anchor:middle}}
.cell2{{fill:var(--ink);font-size:12px;font-weight:600}}
.hi2{{fill:var(--hi)!important}}
.lvlabel{{fill:var(--ink);font-size:13px;font-weight:700}}
.sdzero{{fill:var(--hi);font-size:10.5px;font-weight:700}}
.flag{{fill:var(--muted);font-size:11px;font-weight:600}}
.flag.warn{{fill:var(--hi)}}
.hi{{fill:var(--hi);font-size:12px;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}
th{{color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--card);z-index:1}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.mono{{font-family:ui-monospace,Menlo,monospace;font-size:12px}}
td.arm{{font-size:11.5px;color:var(--muted)}}
.seq{{white-space:nowrap}}
.pill{{display:inline-block;width:19px;height:19px;line-height:19px;border-radius:5px;color:#fff;
font-size:11px;font-weight:700;text-align:center;margin-right:3px}}
.pill.sm{{width:auto;padding:0 5px;font-size:10.5px;height:17px;line-height:17px}}
.scroll{{max-height:540px;overflow:auto}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:8px}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}}
.lead{{background:linear-gradient(90deg,rgba(192,57,43,.09),transparent);border-left:4px solid var(--hi);
padding:14px 17px;border-radius:0 10px 10px 0;margin:16px 0}}
.lead b{{color:var(--hi)}}
ul,ol{{margin:8px 0 8px 20px;padding:0}} li{{margin:5px 0}}
code{{background:rgba(127,140,150,.13);padding:1px 5px;border-radius:4px;font-size:12.5px}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:820px){{.split{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">

<h1>绩效（奖金档位）全量普查</h1>
<div class="sub">CareerSim-BDCI26 · {len(idx)} 局 × {n_rev} 个半年评审点 ·
数据源 <code>outputs/九问/&lt;run_dir&gt;/events-*.jsonl</code>（100% 覆盖，旧口径仅 20 局）·
奖金金额逐条用「月薪 × 档位系数」自校验：<b>366 条 0 例不符</b></div>

<div class="lead">
<b>一句话结论：</b>绩效档位是<b>职级的函数</b>，不是努力的函数——M6 全 54 局一律 C（把 M6 当初期危机是误读）。
真正有杀伤力的只有一个组合：<b>「还在 L1 + 拿 C/D」</b>。信号最强的一条单点预警是
<b>M18 档位 = D（6/7 被裁）</b>，而 <b>M18 拿到 B 的 40 局，0 局因绩效出局</b>。
绩效通道只解释 6/18 早死（33%），爆雷（5 局）是并列的第二杀手且与绩效无关。
</div>

<div class="kpis">{kpi_html}</div>

<h2>一、各评审点档位分布</h2>
<div class="card">{chart_by_month(by_month)}
<div class="legend">{"".join(f'<span><i style="background:{TIER_COLOR[t]}"></i>{TIER_LABEL[t]}</span>' for t in "ABCD")}</div>
</div>
<div class="card">
<h3>数值表</h3>
<table><thead><tr><th>评审点</th><th class="num">样本</th><th class="num">A</th><th class="num">B</th>
<th class="num">C</th><th class="num">D</th><th class="num">C+D</th><th class="num">均档位</th>
<th>当时职级分布</th></tr></thead><tbody>{"".join(dist)}</tbody></table>
<p style="color:var(--muted);font-size:12.5px;margin:10px 0 0">
<b>M6 是纯机制产物</b>：L1 的三维上限 (skill 9 / output 3 / network 3) 让绩效数学上限 = 3，
正好落在 C 档，与这一局最终死活完全无关（通关 36 局与炒鱿鱼 6 局的 M6 都是 C）。
C/D 的占比随后单调下降：M12 55% → M18 22% → M24 16% → M30 起 0%——
<b>「绩效差」是入职前 24 个月的短期现象</b>。</p>
</div>

<h2>二、自变量是「职级」：L3 组内零方差</h2>
<div class="card">{chart_cross(cross)}
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
<b>L3 的 71 个评审点清一色 B 档，组内标准差 0.00</b>——同一职级内无论怎么投入，档位不变，
这是「职级决定档位」最干净的证据。L1 的实测天花板是 C（91 个点里 82 个 C、9 个 D）；
A 档只在 L4（60 个）与 L5（9 个）出现。L4/L5 的 sd≈0.50 说明那里还剩一点可控空间，
来源是 <code>output</code>——唯一没有软帽的线性项（每 +10 点 = 绩效 +1）。</p>
</div>

<h2>三、★ 风险阶梯：哪些信号真的能预测「被裁」</h2>
<div class="card">{chart_ladder(ladder)}
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
两件事同时成立：<br>
① <b>D 档是唯一有强杀伤力的档位</b>——M18 拿 D ⇒ 86%（6/7）、M24 拿 D ⇒ 100%（3/3）；
而 M12 拿 C 只有 26%，M18 拿 C 是 0/4。<br>
② <b>「L1 + C」是唯一会致命的 C 档组合</b>——M12 时 L1×C 是 6/23，而 L2×C 是 0/5、
L2×B 是 0/23。<b>只要升到 L2，连 C 档都变得无害。</b></p>
</div>
<div class="card">
<h3>完整阶梯（样本 ≥3 的判据，按炒鱿鱼率降序）</h3>
<table><thead><tr><th>判据</th><th class="num">炒鱿鱼 / 局数</th><th class="num">炒鱿鱼率</th></tr></thead>
<tbody>{"".join(lad_rows)}</tbody></table>
</div>

<h2>四、结局轨迹：三条死因通道互相独立</h2>
<div class="card">
<table><thead><tr><th>结局</th>{"".join(f'<th class="num">M{m}</th>' for m in REVIEW_MONTHS)}</tr></thead>
<tbody>{"".join(traj)}</tbody></table>
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
表格把 6 条死因分开计数（这正是本项目一直强调的「<b>统计时必须分开计数</b>」）：
<ul>
<li><b>炒鱿鱼end</b>：轨迹固定为 <code>C→C→D→(C|D)</code>，即<b>全程停在 L1</b>，M18 掉到 D，
M24 第二次触发计数器，24 个月出局。6 局全部如此。</li>
<li><b>信任危机end（爆雷）</b>：轨迹 <code>C→B→B→B→…</code> 与通关组<b>不可区分</b>——
涨到 M38/M43 才死。⇒ <b>爆雷与绩效完全无关，是独立通道</b>，不能靠绩效策略解决。</li>
<li><b>眼前一黑end（健康）</b>：M6 之前就死（6 个月），只有 1 条记录。</li>
<li><b>喝西北风end（财富）</b>：9 个月，同样在 M6 之前就崩。</li>
</ul>
⇒ 绩效通道只解释 6/18 的早死（33%）。<b>把绩效当作唯一的存活抓手是错的。</b></p>
</div>

<h2>五、档位 ↔ 最终评分 / 结局</h2>
<div class="card">{chart_scatter(rows)}</div>
<div class="card">
<h3>相关系数总表</h3>
<table><thead><tr><th>关系</th><th class="num">Pearson r</th><th class="num">Spearman ρ</th>
<th class="num">n</th><th>解读</th></tr></thead><tbody>
<tr><td>平均档位 ↔ 最终评分</td>
<td class="num">{P_STATS['tier_score']:.3f}</td>
<td class="num">{P_STATS['tier_score_s']:.3f}</td>
<td class="num">{P_STATS['n_ws']}</td><td>强正相关</td></tr>
<tr><td>平均档位 ↔ 存活月数</td>
<td class="num">{P_STATS['tier_months']:.3f}</td>
<td class="num">{P_STATS['tier_months_s']:.3f}</td>
<td class="num">{P_STATS['n_all']}</td><td>档位低 ⇔ 活不长</td></tr>
<tr><td>局末职级 ↔ 最终评分</td>
<td class="num">{P_STATS['lv_score']:.3f}</td>
<td class="num">—</td><td class="num">{P_STATS['n_ws']}</td><td>职级是评分的第一驱动</td></tr>
<tr><td>局末职级 ↔ 平均档位</td>
<td class="num">{P_STATS['lv_tier']:.3f}</td>
<td class="num">—</td><td class="num">{P_STATS['n_ws']}</td><td>档位几乎被职级完全解释</td></tr>
<tr><td><b>平均档位 ↔ 评分（按职级组内去均值）</b></td>
<td class="num"><b>{R_PARTIAL:.3f}</b></td><td class="num">—</td><td class="num">{P_STATS['n_ws']}</td>
<td><b>仍有独立信息</b>：同一职级内，档位高者分更高（但 r 从 {P_STATS['tier_score']:.3f} 掉到
{R_PARTIAL:.3f} ⇒ 大部分是职级带来的）</td></tr>
</tbody></table>
<h3>按评级分组</h3>
<table><thead><tr><th>评级</th><th class="num">局数</th><th class="num">平均档位</th></tr></thead><tbody>
{"".join(f'<tr><td>{g}</td><td class="num">{sum(1 for r in ws if r["grade"]==g)}</td><td class="num">{(lambda s: sum(r["mean_tier"] for r in s)/len(s) if s else float("nan"))([r for r in ws if r["grade"]==g]):.2f}</td></tr>' for g in "ABCDE")}
</tbody></table>
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
档位阶梯与评级阶梯严格同向（E 级 1.62 → A 级 3.13）。<b>但因果方向要注意：档位不是「挣分的手段」，
它是职级与是否被裁的伴随指标。</b>把档位当优化目标会误导决策（见第八节）。</p>
</div>

<h2>六、两条结构性天花板</h2>
<div class="card">{chart_ceiling()}
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
<b>① 职级天花板</b>：满配三维时各职级绩效上限 L1=3 / L2=5 / L3=6 / L4=8 / L5=8 / L6=8 / L7=9。
<b>S 档（perf≥12）在 L1–L7 数学不可达</b>；A 档从 L4 起才可能。<br>
<b>② 升上去才有上限</b>：从 L1 到 L4，绩效上限从 3 涨到 8（+167%）。
<b>想提高绩效，唯一的办法是提高职级</b>——这是全报告最重要的一条操作性推论。</p>
</div>

<h2>七、晋级的「绩效税」：L4→L5 档位不升反降</h2>
<div class="card">{chart_tax(rows)}
<p style="color:var(--muted);font-size:12.5px;margin:12px 0 0">
升 L1→L2 有 <b>+0.80 档</b>的顺风（职级项 +2→+3，同时三维上限放宽）。
但从 <b>L4→L5 会 −0.90 档</b>（职级项 0→−4），21 局里 17 局从 A 掉到 B，
<b>半年奖金从 1.5× 月薪降到 0.5× 月薪</b>；L5→L6 再 −1.00 档。
这不是「不该升」（晋升的职级分 10 分/级远大于奖金损失），而是提醒：
<b>L5 之后第一个评审点的档位下滑是机制性的，不要误读为策略失败。</b></p>
</div>

<h2>八、逐局明细（{len(rows)} 局）</h2>
<div class="card scroll">
<table><thead><tr><th>run_dir</th><th>臂</th><th class="num">评分</th><th>评级</th>
<th class="num">存活月</th><th>局末</th><th>档位序列（M6→…）</th><th>结局</th></tr></thead>
<tbody>{"".join(trows)}</tbody></table>
</div>

<h2>九、结论与策略含义</h2>
<div class="card">
<h3>九条硬结论</h3>
<ol>
<li><b>M6 恒为 C 且零信息量</b>：54/54（通关组与炒鱿鱼组的 M6 完全一样）。原因是 L1 的截断上限
把绩效数学上限钉在 3。⇒ <b>删掉一切「为 M6 绩效做准备」的动作。</b></li>
<li><b>档位的自变量是职级</b>：L3 组内 sd = 0.00（71 点全 B）；A 档只在 L4+ 出现；
D 档 9/10 出现在 L1。r(职级, 档位) = 0.937–0.944。</li>
<li><b>唯一的致命组合是「L1 + C/D」</b>：M12 时 L1×C ⇒ 6/23 被裁；L2×C ⇒ 0/5；L2×B ⇒ 0/23。
<b>升到 L2 是绩效通道的免死金牌</b>。</li>
<li><b>D 档 = 「还没升上去」的指纹</b>：7 个首 D 全部出现在 M18 且全部在 L1（6 局被裁、1 局靠 M24
回到 C 活下来）。</li>
<li><b>信号最强的单点预警是 M18 = D（86%）</b>，其次是 M24 = D（100%）与 M24 = C（60%）。
M24 仍停在 L1 ⇒ 100%（6/6）。</li>
<li><b>绩效只解释 1/3 的早死</b>：6/18。爆雷 5 局、健康 2 局、财富 1 局、中断 4 局。
绩效策略<b>不能</b>替代风险/健康/财富守卫。</li>
<li><b>爆雷与绩效完全无关</b>：信任危机组的档位轨迹（C→B→B→B…）与通关组不可区分。</li>
<li><b>S 档不可达、A 档需 L4+</b>；L4→L5 有 −0.9 档的机制性「绩效税」。</li>
<li><b>档位 ↔ 评分 r = 0.918，但扣除职级后只剩 0.406</b> ⇒ 档位大部分是职级的影子。</li>
</ol>
<h3>对技能的调整（v10 落地清单）</h3>
<ol>
<li><b>把「为提升绩效而投入体力」整条删掉</b>——绩效是职级的函数，提高绩效的唯一路径是晋升。</li>
<li><b>M6 绩效警报降级为纯提示</b>（原铁律 18 里「M6 的 C 是机制性的」保留，但不要再为它排任何动作）。</li>
<li><b>引入「M18 首 D 红色警报」</b>：一旦 M18 档位为 D，该局自动切到「止损模式」——
后续只做三件事：不再制造埋雷、保住健康 ≥4、不再为晋升投入（因为已经来不及），
把余下 6 个月的分数守住。</li>
<li><b>把「M12 前完成 L1→L2」升级为唯一的一级优先目标</b>，权重高于任何单项补量——
它同时解锁绩效上限（3→5）与免死金牌。</li>
<li><b>风险守卫不得因绩效目标让位</b>：爆雷 5 局全部发生在「绩效看起来正常」的局里
（轨迹 C→B→B→B），绩效好会给风险维度制造虚假安全感。</li>
<li><b>L5 之后的档位下滑不要触发纠错动作</b>（机制性 −0.9 档），否则会把体力浪费在补不回来的维度上。</li>
</ol>
</div>

<div class="sub" style="margin-top:30px">
生成脚本：<code>analysis/perf_census_all.py</code>（统计） ·
<code>analysis/build_perf_viz.py</code>（本页） ·
可视化数据：<code>analysis/perf_viz_data.json</code><br>
方法学：内嵌引擎返回 JSON 逐条解析 → 按「结算月 + 档位 + 金额 + 职级」去重
（<b>不可</b>只用「档位+金额+职级」，否则 L1 上 M18/M24 两个 D 会被误合并）→
奖金金额与「月薪 × 档位系数」双向自校验。
</div>
</div></body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"已写出 {OUT}  ({len(doc)/1024:.0f} KB)")
    print("风险阶梯（炒鱿鱼率）：")
    for name, n, k, _ in lad_sorted:
        print(f"   {name:<24} {k}/{n} = {k/n:.0%}")


if __name__ == "__main__":
    main()
