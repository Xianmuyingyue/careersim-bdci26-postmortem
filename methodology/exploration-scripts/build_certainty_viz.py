#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「M6 晋升确定性评估」配套可视化（单文件 HTML，内联 CSS + SVG，无外部依赖）。

数据来源（与本批评估口径一致）：
  · 全池 = 官方解码事件池 171 文件 / 974 选项 / 412 节点
  · 对局 = 57 局有 M6 评审快照的 run
  · 判据表来自样本外验证 + 节点级反事实（两口径并列）

用法：.venv/bin/python3 analysis/build_certainty_viz.py
产出：analysis/m6_certainty_viz.html
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "analysis" / "m6_certainty_viz.html"

BASE = 58.6            # 选项级基线：P(ΔN≥0 且 ΔO≥0)
W = 700                # 统一 viewBox 宽
C = dict(ok="#2e8b57", mid="#e0a800", bad="#c0392b", ref="#2f6fb5",
         pool="#2f6fb5", m5="#e07b39", grid="#dde5ee")

# (判据, 全池%, M5%, 判定)
RULES = [
    ("最长且非原则族", 72.1, 66.7, "ok"),
    ("非主动族里最长", 64.8, 61.4, "ok"),
    ("最长文本", 74.8, 61.4, "mid"),
    ("最长且无承诺数字", 74.8, 61.4, "mid"),
    ("位置 1", 73.5, 47.4, "bad"),
    ("位置最后", 42.7, 59.6, "bad"),
    ("最短文本", 45.6, 50.9, "bad"),
    ("神谕（读得到真值）", 93.4, 96.5, "ref"),
]
TAGWORD = {"ok": "★ 可信", "mid": "⚠ 中等", "bad": "✗ 不可用", "ref": "上限参考"}

# (长度下界, 长度上界, 安全率, ΔN)
LENB = [(0, 5, 62, 0.04), (6, 11, 50, -0.23), (12, 17, 46, -0.14), (18, 23, 61, 0.06),
        (24, 29, 74, 0.40), (30, 35, 85, 0.61), (36, 99, 88, 0.88)]

# (策略, 反事实晋级率%)
CF = [("现实（Agent 实际选择）", 50.9), ("位置 1", 54.4), ("最长文本", 63.2),
      ("最长且非原则族", 68.4), ("神谕（上限）", 77.2)]

# (职级, output 门槛, network 门槛, output 上限, network 上限, 备注)
MARGIN = [("L1 · M6", 3, 3, 3, 3, "余量 0 / 0　← 一击必落榜", True),
          ("L2 · M12", 5, 6, 6, 7, "余量 +1 / +1　能容忍 1 点", False),
          ("L3 · M18", 14, 18, 16, 21, "余量 +2 / +3　能容忍 2–3 点", False)]


def chart_rules():
    """哑铃图：每条判据「全池值 vs M5 值」，连线颜色 = 判定"""
    x0, x1, lo, hi = 170, 588, 38, 100
    k = (x1 - x0) / (hi - lo)
    rows, y, hgt = [], 34, 27
    bottom = y + len(RULES) * hgt - 6
    for v in (40, 50, 60, 70, 80, 90, 100):
        x = x0 + (v - lo) * k
        rows.append(f'<line x1="{x:.1f}" y1="22" x2="{x:.1f}" y2="{bottom}" stroke="{C["grid"]}"/>')
        rows.append(f'<text class="tick" x="{x:.1f}" y="14" text-anchor="middle">{v}%</text>')
    xb = x0 + (BASE - lo) * k
    rows.append(f'<line x1="{xb:.1f}" y1="22" x2="{xb:.1f}" y2="{bottom}" stroke="#94a3b8" '
                f'stroke-width="1.4" stroke-dasharray="5 4"/>')
    rows.append(f'<text class="tick" x="{xb:.1f}" y="{bottom+14}" text-anchor="middle" '
                f'fill="#64748b">基线 58.6%</text>')
    for name, p, m, verdict in RULES:
        col = C[verdict]
        xp, xm = x0 + (p - lo) * k, x0 + (m - lo) * k
        rows.append(f'<text class="rlabel" x="6" y="{y+4}">{name}</text>')
        rows.append(f'<line x1="{min(xp,xm):.1f}" y1="{y}" x2="{max(xp,xm):.1f}" y2="{y}" '
                    f'stroke="{col}" stroke-width="2.4" opacity="0.5"/>')
        rows.append(f'<circle cx="{xp:.1f}" cy="{y}" r="5.5" fill="{C["pool"]}" stroke="#fff" stroke-width="1.4"/>')
        rows.append(f'<circle cx="{xm:.1f}" cy="{y}" r="5.5" fill="{C["m5"]}" stroke="#fff" stroke-width="1.4"/>')
        rows.append(f'<text class="tag" x="598" y="{y+4}" fill="{col}">{TAGWORD[verdict]}</text>')
        y += hgt
    return f'<svg class="chart" viewBox="0 0 {W} {bottom+26}" role="img">{"".join(rows)}</svg>'


def chart_len():
    """长度单调曲线：安全率（柱）+ ΔNetwork（折线）"""
    x0, x1, top, bot = 120, 620, 40, 190
    k = (x1 - x0) / len(LENB)
    rows = []
    for v in (40, 60, 80, 100):
        y = bot - (v - 40) / 60 * (bot - top)
        rows.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{C["grid"]}"/>')
        rows.append(f'<text class="tick" x="{x0-8}" y="{y+4:.1f}" text-anchor="end">{v}%</text>')
    for i, (a, b, r, dn) in enumerate(LENB):
        cx = x0 + k * (i + 0.5)
        h = (r - 40) / 60 * (bot - top)
        col = "#2e8b57" if r >= 70 else ("#e0a800" if r >= 55 else "#c0392b")
        rows.append(f'<rect x="{cx-24:.1f}" y="{bot-h:.1f}" width="48" height="{h:.1f}" fill="{col}" '
                    f'opacity="0.82" rx="4"/>')
        rows.append(f'<text class="inbar2" x="{cx:.1f}" y="{bot-h-7:.1f}" text-anchor="middle">{r}%</text>')
        lab = f"{a}–{b}" if b < 99 else f"{a}+"
        rows.append(f'<text class="tick" x="{cx:.1f}" y="{bot+18}" text-anchor="middle">{lab}</text>')
        rows.append(f'<text class="tick" x="{cx:.1f}" y="{bot+34}" text-anchor="middle" '
                    f'fill="{"#c0392b" if dn < 0 else "#2e8b57"}">ΔN {dn:+.2f}</text>')
    rows.append(f'<text class="axis" x="6" y="{bot+58}">描述长度（字）　—— 18 字是拐点：'
                f'短选项＝单边下注，长选项＝折中兼顾式表述</text>')
    return f'<svg class="chart" viewBox="0 0 {W} {bot+72}" role="img">{"".join(rows)}</svg>'


def chart_cf():
    """反事实收益阶梯"""
    x0, x1, lo, hi = 200, 620, 45, 80
    k = (x1 - x0) / (hi - lo)
    rows, y, hgt = [], 30, 30
    for v in (50, 60, 70, 80):
        x = x0 + (v - lo) * k
        rows.append(f'<line x1="{x:.1f}" y1="16" x2="{x:.1f}" y2="{y+len(CF)*hgt-12}" stroke="{C["grid"]}"/>')
        rows.append(f'<text class="tick" x="{x:.1f}" y="10" text-anchor="middle">{v}%</text>')
    for i, (name, v) in enumerate(CF):
        col = "#c0392b" if i == 0 else ("#94a3b8" if i == 1 else ("#2e8b57" if i == len(CF)-1 else "#2f6fb5"))
        w = (v - lo) * k
        rows.append(f'<text class="rlabel" x="6" y="{y+6}">{name}</text>')
        rows.append(f'<rect x="{x0}" y="{y-9}" width="{w:.1f}" height="22" fill="{col}" rx="4" opacity="0.88"/>')
        rows.append(f'<text class="inbar2" x="{x0+w+8:.1f}" y="{y+6}">{v}%</text>')
        y += hgt
    xl = x0 + (77.2 - lo) * k
    rows.append(f'<line x1="{xl:.1f}" y1="16" x2="{xl:.1f}" y2="{y-12}" stroke="#2f6fb5" '
                f'stroke-width="1.6" stroke-dasharray="5 4"/>')
    rows.append(f'<text class="axis" x="6" y="{y+14}">虚线 = 77.2% 理论上限'
                f'（需读得到选项真值，游戏内不可得）</text>')
    return f'<svg class="chart" viewBox="0 0 {W} {y+26}" role="img">{"".join(rows)}</svg>'


def chart_margin():
    """余量衰减：门槛 vs 上限（output / network 双行）"""
    x0, MAXV, BW = 176, 22, 360
    rows, y = [], 18
    for name, th_o, th_n, cap_o, cap_n, note, alarm in MARGIN:
        col = "#c0392b" if alarm else "#2e8b57"
        rows.append(f'<text class="rlabel" x="6" y="{y+14}">{name}</text>')
        rows.append(f'<text class="tag" x="{x0+16}" y="{y+14}" fill="{col}">{note}</text>')
        for j, (th, cap, lab) in enumerate(((th_o, cap_o, "output"), (th_n, cap_n, "network"))):
            yy = y + 24 + j * 21
            wt, wc = th / MAXV * BW, cap / MAXV * BW
            rows.append(f'<text class="tick" x="{x0-8}" y="{yy+12}" text-anchor="end">{lab}</text>')
            rows.append(f'<rect x="{x0}" y="{yy}" width="{wc:.1f}" height="15" fill="#c9d6e4" rx="3"/>')
            rows.append(f'<rect x="{x0}" y="{yy}" width="{wt:.1f}" height="15" fill="#2f6fb5" rx="3"/>')
            rows.append(f'<text class="inbar2" x="{x0+wc+9:.1f}" y="{yy+12}" fill="#64748b" '
                        f'font-weight="400">门槛 {th} / 上限 {cap}</text>')
        y += 72
    rows.append(f'<text class="axis" x="6" y="{y+4}">浅色段 = 门槛到上限之间的余量（即"能容忍被扣几点"）；'
                f'L1 段 output/network 余量为 0</text>')
    return f'<svg class="chart" viewBox="0 0 {W} {y+20}" role="img">{"".join(rows)}</svg>'


def build():
    css = """
    :root{--bg:#f7f9fc;--card:#fff;--ink:#1f2933;--dim:#5a6572;--line:#e3eaf2}
    *{box-sizing:border-box}
    body{margin:0;padding:30px 22px 56px;background:var(--bg);color:var(--ink);
         font:15px/1.75 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif}
    .wrap{max-width:820px;margin:0 auto}
    h1{font-size:23px;margin:0 0 6px;letter-spacing:.3px}
    .sub{color:var(--dim);font-size:13.5px;margin-bottom:22px}
    .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 26px}
    .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
    .card .n{font-size:22px;font-weight:700;letter-spacing:.5px}
    .card .l{font-size:12.5px;color:var(--dim);margin-top:3px}
    .k1{color:#2e8b57}.k2{color:#c0392b}.k3{color:#2f6fb5}
    h2{font-size:15.5px;margin:30px 0 4px;padding-left:9px;border-left:3px solid #2f6fb5}
    .note{color:var(--dim);font-size:13px;margin:5px 0 10px}
    .box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px 4px;margin-bottom:6px}
    .chart{display:block;width:100%;height:auto;font-family:inherit}
    .tick{font-size:11px;fill:#7b8794}
    .axis{font-size:11.5px;fill:#5a6572}
    .rlabel{font-size:12.5px;fill:#1f2933}
    .tag{font-size:11.5px;font-weight:600}
    .inbar2{font-size:11.5px;fill:#1f2933;font-weight:600}
    .legend{font-size:12px;color:var(--dim);margin:2px 0 0;padding-left:2px}
    .dot{display:inline-block;width:9px;height:9px;border-radius:50%;vertical-align:middle;margin-right:4px}
    code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12.5px}
    ul{margin:6px 0 0;padding-left:20px}li{margin:3px 0;font-size:14px}
    .verdict{background:#eef6f0;border:1px solid #cfe6d8;border-left:4px solid #2e8b57;
             border-radius:8px;padding:13px 16px;margin-top:24px;font-size:14px}
    .warn{background:#fdf6ec;border:1px solid #f2ddb8;border-left:4px solid #e0a800;
          border-radius:8px;padding:12px 16px;margin-top:14px;font-size:13.5px}
    """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M6 晋升确定性评估</title><style>{css}</style></head><body><div class="wrap">

<h1>M6 晋升确定性能否被「最后一击」机制有效提高？</h1>
<div class="sub">CareerSim-BDCI26 · 可证伪评估 · 全池 974 选项 + 57 局 M6 评审 · 2026-09-26</div>

<div class="cards">
  <div class="card"><div class="n k1">50.9% → 68.4%</div>
    <div class="l">期望晋级率　可见判据能拿回 +17.5pp</div></div>
  <div class="card"><div class="n k3">77.2%</div>
    <div class="l">理论上限　被「游戏不暴露选项数值」封死</div></div>
  <div class="card"><div class="n k2">1 / 3</div>
    <div class="l">不可消除残差　可见判据最高只认对 67%</div></div>
</div>

<h2>一 · 判据排行榜：全池（样本外） vs M5（决策层）</h2>
<div class="note">只有<b>两列一致</b>才算数——在小样本上挑判据，必然挑出"看起来最好"的那条。
  n=57 时 1σ ≈ 6.6pp，所以「位置最后」在 M5 上给出的 +17.5pp 其实全是噪声。</div>
<div class="box">{chart_rules()}
  <div class="legend"><span class="dot" style="background:#2f6fb5"></span>全池 412 节点
    <span class="dot" style="background:#e07b39;margin-left:12px"></span>M5 实测 57 局
    　|　连线颜色 = 判定</div>
</div>

<h2>二 · 唯一可信的判据是「描述长度」，不是关键词</h2>
<div class="note">长度分桶后安全率<b>单调上升</b>（46% → 88%），18 字是拐点 ⇒ 是真机制，不是伪相关。
  短选项＝单边下注（"硬顶"/"摆烂"/"拒收"），长选项＝折中兼顾式表述。</div>
<div class="box">{chart_len()}</div>

<h2>三 · 决策层反事实：到底能拿回多少</h2>
<div class="note">在 57 局真实 M5 节点上做反事实（节点文本 57/57 都能在全池唯一匹配到真值，不是估计）。</div>
<div class="box">{chart_cf()}</div>
<div class="warn">★ 缺口 68.4% → 77.2% 的 <b>8.8pp 不是能力问题</b>：全量日志实测
  <code>status_updates</code> 只出现在<b>体力选项</b>上（39740 = 39740 恰好相等），
  118 个剧情选项 <b>100% 无此字段</b> ⇒ Agent 永远看不到选项真值。</div>

<h2>四 · 为什么 M6 是最脆的窗口：余量随职级放大</h2>
<div class="note">L1 的上限恰好等于门槛 ⇒ <code>output</code>/<code>network</code> 余量为 0。
  同一机制在 M12 之后杀伤力显著下降。</div>
<div class="box">{chart_margin()}</div>

<div class="verdict">
<b>结论</b>：能提高，但<b>不能"有效"提高</b>。
<ul>
  <li><b>解释层</b>：69.6% → <b>98.2%</b>，机制侧已闭合——这是真收益（可预测性）。</li>
  <li><b>操作层</b>：50.9% → <b>68.4%</b>（约提高 1/3），但只有一条判据经得起样本外验证。</li>
  <li><b>结果层</b>：<b>不可能锁定必过</b>，上界 77.2% 由游戏设计给出。</li>
</ul>
⇒ 正确用法：把它当作<b>"降低期望损失"</b>的关卡（可预测、可避坑），而不是"精密控制"的关卡。
M6 也不该为绩效投资（L1 段 <code>perf</code> 恒 3、必然 C 档、不构成门）。
</div>

</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"已写出 {OUT}（{len(html)/1024:.1f} KB）")


if __name__ == "__main__":
    build()
