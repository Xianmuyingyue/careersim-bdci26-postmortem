#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 M6 晋级归因的配套可视化（单文件 HTML，内联 CSS + SVG）。
数据全部硬编码自 analysis/m6_final_numbers.py 的权威输出（同批次口径）。

用法：.venv/bin/python3 analysis/build_m6_viz.py
产出：analysis/m6_attrib_viz.html
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "analysis" / "m6_attrib_viz.html"

# ---- 权威数据 ----
N = 56
M6 = dict(promoted=30, notpromoted=26)
MATRIX = {
    "M5": dict(tp=25, fn=12, fp=5, tn=14, acc=69.6),
    "SN": dict(tp=29, fn=0, fp=1, tn=26, acc=98.2),
}
CAP = dict(skill=(9, 8), output=(3, 3), network=(3, 3))   # (CAP, TH)
GAPS = [("只缺 network", 12), ("只缺 output", 7), ("缺 output+network", 6), ("缺 skill+network", 1)]
M5DIST = [("(9,3,3)", 34), ("(9,3,2)", 6), ("(9,3,1)", 4), ("(8,3,3)", 3), ("其它", 9)]

LASTHIT = [
    ("153540Z", "主动承认饭局说过模糊方向", 0, 0, -2, "诚实担责"),
    ("161605Z", "次日再回并说明作息边界", 0, 0, -1, "守健康与边界"),
    ("204559Z", "接下跨组评审邀请，深度准备意见", 0, -2, 0, "换跨组影响力"),
    ("022235Z", "按事实给好友打 B 并写清改进点", 0, 0, -2, "职业诚信"),
    ("074822Z", "投入 2 周完整搭建 CI 自动化体系", 0, -2, -1, "补N补Output"),
    ("145357Z", "用提问引导他自己意识到问题", 0, -1, 0, "折中补N降风险"),
    ("201004Z", "拒绝接收涉密资料，建议合规交接", 0, 0, -1, "零风险且合规"),
    ("212921Z", "写正式 OA 表扬信，抄送对方 Leader", 0, -1, 0, "补N且降风险"),
    ("222709Z", "按事实打 B，评语写清改进点", 0, 0, -2, "补N低风险 ΔN≥0"),
    ("013834Z", "按原计划陪家人放松", -1, -1, -1, "回补非截断维"),
    ("030800Z", "改为灵犀支付申报、自己担任主笔", 0, 0, -1, "补N/O 合规无风险"),
    ("040643Z", "拒绝接收涉密资料，建议合规交接", 0, 0, -1, "合规且最保关系"),
]
SHOCK = [("首次晋级", 0, 49), ("间隔 6 月", 58, 58), ("间隔 12 月", 0, 43),
         ("间隔 18 月", 0, 34), ("间隔 24 月", 0, 2)]


def bar_matrix():
    """两口径四格矩阵"""
    rows = []
    y = 26
    for key, label, col in (("M5", "M5 月末快照口径", "#8a94a1"), ("SN", "评审快照口径", "#2f6fb5")):
        m = MATRIX[key]
        tot = m["tp"] + m["fn"] + m["fp"] + m["tn"]
        rows.append(f'<text class="axis" x="4" y="{y-8}">{label}　准确率 {m["acc"]}%</text>')
        x = 4
        for v, c, lab in ((m["tp"], "#2e8b57", "达标→晋级"), (m["fn"], "#c0392b", "达标→落榜"),
                          (m["fp"], "#e0a800", "不达标→晋级"), (m["tn"], "#5a6572", "不达标→落榜")):
            w = v / tot * 600
            if v:
                rows.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="30" fill="{c}" rx="3"/>')
                if w > 34:
                    rows.append(f'<text class="inbar" x="{x+w/2:.1f}" y="{y+20}">{v}</text>')
            x += w
        y += 62
    return f'<svg class="chart" viewBox="0 0 660 150" role="img">{"".join(rows)}</svg>'


def bar_cap():
    """L1 的 CAP vs 门槛"""
    rows, x0 = [], 92
    for i, (k, (cap, th)) in enumerate(CAP.items()):
        y = 26 + i * 44
        rows.append(f'<text class="lvlabel" x="6" y="{y+19}">{k}</text>')
        wcap = cap / 10 * 470
        wth = th / 10 * 470
        rows.append(f'<rect x="{x0}" y="{y+4}" width="{wcap:.0f}" height="22" fill="#c9d6e4" rx="3"/>')
        rows.append(f'<rect x="{x0}" y="{y+4}" width="{wth:.0f}" height="22" fill="#2f6fb5" rx="3"/>')
        rows.append(f'<text class="inbar hi2" x="{x0+wcap+8:.0f}" y="{y+20}" '
                    f'style="text-anchor:start;fill:var(--ink)">CAP {cap} ／ 门槛 {th}　余量 {cap-th:+d}</text>')
    return f'<svg class="chart" viewBox="0 0 660 160" role="img">{"".join(rows)}</svg>'


def bar_lasthit():
    """12 局最后一击 Δ"""
    rows, y = [], 18
    for tag, desc, ds, do, dn, claim in LASTHIT:
        rows.append(f'<text class="axis2" x="4" y="{y+13}" style="font-family:ui-monospace,monospace">'
                    f'{tag}</text>')
        rows.append(f'<text class="axis" x="86" y="{y+13}">{desc[:20]}</text>')
        # Δ 条：x 起 300，每 1 点 = 26px，向右为正
        bx = 520
        for v, c in ((ds, "#7a5cbf"), (do, "#c0392b"), (dn, "#e08a00")):
            if v == 0:
                continue
            w = abs(v) * 26
            rows.append(f'<rect x="{bx - w:.0f}" y="{y+2}" width="{w:.0f}" height="17" fill="{c}" rx="2"/>')
            rows.append(f'<text class="inbar" x="{bx-w/2:.0f}" y="{y+15}">{v}</text>')
            bx -= w + 3
        rows.append(f'<text class="flag warn" x="600" y="{y+15}">自评「{claim}」</text>')
        y += 25
    return f'<svg class="chart" viewBox="0 0 760 {y+6}" role="img">{"".join(rows)}</svg>'


def bar_shock():
    rows, x0, base = [], 120, 250
    for i, (lab, hit, tot) in enumerate(SHOCK):
        y = 22 + i * 40
        pct = hit / tot * 100 if tot else 0
        rows.append(f'<text class="lvlabel" x="6" y="{y+19}">{lab}</text>')
        rows.append(f'<rect x="{x0}" y="{y+4}" width="{base}" height="22" fill="#eef1f5" rx="3"/>')
        if pct:
            rows.append(f'<rect x="{x0}" y="{y+4}" width="{base*pct/100:.0f}" height="22" fill="#c0392b" rx="3"/>')
        rows.append(f'<text class="axis" x="{x0+base+10}" y="{y+20}" style="fill:var(--ink);font-weight:600">'
                    f'{hit}/{tot} = {pct:.0f}%</text>')
    return f'<svg class="chart" viewBox="0 0 660 {22+len(SHOCK)*40}" role="img">{"".join(rows)}</svg>'


HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M6 晋级归因 · 「最后一击」与零余量结构</title>
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
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 15px}}
.kpi-t{{font-size:12px;color:var(--muted);letter-spacing:.4px}}
.kpi-v{{font-size:20px;font-weight:700;margin:5px 0 3px;color:var(--hi)}}
.kpi-s{{font-size:11.5px;color:var(--muted);line-height:1.45}}
.chart{{width:100%;height:auto;display:block;overflow:visible}}
.axis{{fill:var(--muted);font-size:11px}}
.axis2{{fill:var(--muted);font-size:10.5px}}
.inbar{{fill:#fff;font-size:11px;font-weight:600;text-anchor:middle}}
.lvlabel{{fill:var(--ink);font-size:12px;font-weight:700}}
.flag{{fill:var(--muted);font-size:11px;font-weight:600}}
.flag.warn{{fill:var(--hi);font-size:10.5px}}
.hi2{{fill:var(--hi)}}
.note{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--hi);
border-radius:10px;padding:13px 16px;margin:14px 0;font-size:13.5px}}
ul{{margin:8px 0 8px 20px;padding:0}} li{{margin:5px 0}}
code{{background:rgba(127,127,127,.13);padding:1px 5px;border-radius:4px;font-size:12.5px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th,td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12px}}
.red{{color:var(--hi);font-weight:700}}
.foot{{color:var(--muted);font-size:12px;margin-top:34px;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body><div class="wrap">

<h1>M6 晋级归因：为什么有的能晋级、有的不能</h1>
<div class="sub">56 局 · 186 次晋级事件 · 数据源 <code>outputs/九问/*/events-*.jsonl</code> · 2026-09-26</div>

<h2>一、一句话结论</h2>
<div class="note">
M6 的判定门槛是死的（<b>skill ≥ 8 ∧ output ≥ 3 ∧ network ≥ 3</b>），
真正让它"看起来随机"的是：<b class="red">评审读到的状态 ≠ M5 月末状态</b>——
当月<b>最后一个动作与「月推进」同帧结算</b>，其隐藏效果首次可见就在评审快照里。
而 <b>L1 的 output / network 余量恒为 0</b>（<code>CAP = floor(门槛×1.2) = 门槛</code>），
所以这"最后一击"只要扣 1 点，就直接落榜。
</div>

<div class="kpis">
<div class="kpi"><div class="kpi-t">M6 评审快照</div><div class="kpi-v">56 局</div>
<div class="kpi-s">晋级 30 ／ 落榜 26</div></div>
<div class="kpi"><div class="kpi-t">门槛合取的解释力</div><div class="kpi-v">98.2%</div>
<div class="kpi-s">29/29 达标者全晋级；26/26 缺一维者全落榜</div></div>
<div class="kpi"><div class="kpi-t">用月末状态预测</div><div class="kpi-v">69.6%</div>
<div class="kpi-s">12 局被"最后一击"打到不达标，另有 5 局反向</div></div>
<div class="kpi"><div class="kpi-t">零余量维</div><div class="kpi-v">O / N</div>
<div class="kpi-s">L1 三维修量 = +1 / +0 / +0 ⇒ 一次 −1 即落榜</div></div>
<div class="kpi"><div class="kpi-t">12/12</div><div class="kpi-v">自评正向</div>
<div class="kpi-s">"最后一击"全部是 Agent 自认为"补 N / 合规最优"的选项</div></div>
</div>

<h2>二、判定的完全分离：两种口径对比</h2>
<h3>四格矩阵（达标 = 三维全过门槛）</h3>
<div class="card">{bar_matrix()}
<div class="axis" style="margin-top:10px">
■ <span style="color:#2e8b57">达标→晋级</span>　■ <span style="color:#c0392b">达标→落榜</span>　
■ <span style="color:#e0a800">不达标→晋级</span>　■ <span style="color:#5a6572">不达标→落榜</span>
</div></div>
<div class="note">
评审口径下唯一的例外（<code>20260926T022719Z</code>）也<b>不是门槛问题</b>：
M5 末 <code>S9 O3 N3</code> 达标 ⇒ 成功晋升 L1→L2，但<b>同帧遭爆雷</b>
（"之前的隐患好巧不巧一起炸了，最近半年的工作都打了水漂"）⇒ <code>output</code> 回滚到 <b>0</b>。
</div>

<h3>落榜局的缺口分解（n = 26）</h3>
<div class="card"><table>
<tr><th>缺口</th><th>局数</th><th>说明</th></tr>
{''.join(f'<tr><td>{a}</td><td class="red">{b}</td><td>{"全部是 1–2 点极窄缺口，无一局是大缺口" if i==0 else ""}</td></tr>' for i,(a,b) in enumerate(GAPS))}
</table></div>
<div class="note">⇒ 分配算法已把三维推到「<b>恰好踩线</b>」。<b>缺的不是量，是余量。</b></div>

<h2>三、根因：L1 是唯一"零缓冲"职级</h2>
<div class="card">{bar_cap()}
<div class="axis" style="margin-top:10px">■ <span style="color:#c9d6e4">CAP（截断上限）</span>　■ <span style="color:#2f6fb5">门槛</span></div>
</div>
<div class="card"><h3 style="margin-top:0">M5 月末 (skill, output, network) 分布</h3>
<svg class="chart" viewBox="0 0 660 40" role="img">
{''.join(f'<rect x="{4+i*132}" y="6" width="120" height="26" fill="#2f6fb5" opacity="{0.35+0.13*i}" rx="4"/><text class="inbar" x="{64+i*132}" y="24">{lab} ×{v}</text>' for i,(lab,v) in enumerate(M5DIST))}
</svg>
<div class="axis">34/56 局顶在 (9,3,3)——即三维全部触顶，余量为零。</div>
</div>

<h2>四、「最后一击」：12 局的完整对照</h2>
<div class="card">{bar_lasthit()}
<div class="axis" style="margin-top:10px">
■ <span style="color:#7a5cbf">Δskill</span>　■ <span style="color:#c0392b">Δoutput</span>　
■ <span style="color:#e08a00">Δnetwork</span>　（向左 = 扣减；全部为 M5 末顶格 <code>S9 O3 N3</code> 的局）
</div></div>
<div class="note">
<b class="red">12/12 零例外</b>：Agent 笔记里写着「补 N / ΔN≥0 / 合规无风险」的选项，
实际全部扣了 <code>network</code> 或 <code>output</code>。两类可用的负向语义族：
<ul>
<li><b>原则族</b>（承认 / 如实 / 按事实 / 拒绝 / 异议 / 守边界 / 要求合规交接）⇒ 实测 <b>扣 network</b>（6 例）</li>
<li><b>投入族</b>（接下 / 深入准备 / 投入 N 周 / 牵头搭建 / 写正式信 / 当天补救）⇒ 实测 <b>扣 output</b>（5 例）</li>
</ul>
⇒ 剧情选项<b>没有"纯增益项"</b>，是权衡型；而<b>触顶时增益被截断丢弃、扣减全额生效</b>
⇒ 该维上任何选项的期望值 ≤ 0 ⇒ <b>应按"哪项扣得少"排序，而非"哪项补得多"</b>。
</div>

<h2>五、晋级自带的「升迁震荡」</h2>
<div class="card">{bar_shock()}
<div class="axis" style="margin-top:10px">评审文案出现「升迁节奏过快…协作摩擦上升，办公室侧目增多」⇒ 晋升后追加 <code>Network −3 / Dignity −1</code></div>
</div>
<div class="note">
<b>触发条件是确定性的</b>：与上次晋级间隔 <b>&lt; 12 个月</b> ⇒ <b class="red">58/58 = 100%</b>；
<b>≥ 12 个月</b> ⇒ <b>0/79 = 0%</b>；<b>首次晋级永不触发</b>（49 次 0 例）。
<ul>
<li><code>L1→L2</code>（M6 / M12 的首次晋级）<b>永远干净</b>，不扣 network。</li>
<li><code>L2→L3</code> 起，只要上一窗也晋级过就必吃 —— 而 L3 门槛 network = 6，<b>一次震荡吃掉一半门槛</b>。</li>
<li>⇒ 不能为躲它放慢晋升，但<b>必须把它当已定价成本写进 network 预算</b>（目标 +3）。</li>
</ul>
</div>

<h2>六、现实验证：v10 批次首局</h2>
<div class="note">
v10 批次首局正是上表第 12 号：<code>20260926T040643Z</code>　grade <b class="red">E</b>　score <b>17.73</b>　
months <b>24</b>　level <b>L1</b>　network <b>2.0</b><br>
因果链：M5 末 <code>S9 O3 N3</code>（达标）→ 最后一个动作选「拒绝接收涉密资料，建议合规交接」
（<b>合规上最优</b>）⇒ <code>N −1</code> → 评审点 <code>N = 2 &lt; 3</code> ⇒ M6 落榜 →
无 L2 ⇒ perf 天花板锁死 3 ⇒ 24 个月绩效连击 ⇒ 被裁。
</div>

<div class="foot">
配套报告：<code>analysis/m6_promotion_attrib_report.md</code>　·　
复算脚本：<code>m6_final_numbers.py</code> / <code>lastaction_census.py</code> / <code>promo_shock_census.py</code>　·　
技能落点：<code>analysis/ab/v10b/</code>
</div>

</div></body></html>
"""

OUT.write_text(HTML, encoding="utf-8")
print(f"已生成 {OUT}  ({len(HTML.encode('utf-8'))} 字节)")
