#!/usr/bin/env python3
"""把 `analysis/event_census/` 的 TSV 汇编成**单文件**可视化报告（无外部依赖）。

产出：`analysis/event_census/report.html`
  · 三个视图：按月（M1–M48）/ 按事件 / 选择影响
  · 内联 CSS+JS，零外部请求；时间按北京时间；交付物内不出现本地路径
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "event_census"
OUT = SRC / "report.html"

DIMS = ["output", "network", "skill", "dignity", "health", "wealth", "level", "energy"]
DIM_CN = {"output": "产出", "network": "人脉", "skill": "技能", "dignity": "尊严",
          "health": "健康", "wealth": "财富", "level": "职级", "energy": "体力"}
MARKS = ["晋升", "警告", "爆雷", "谈话", "埋雷", "工资", "奖金"]


def read_tsv(name):
    p = SRC / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def fnum(v):
    v = (v or "").strip()
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def main():
    meta = {r["键"]: int(r["值"]) for r in read_tsv("meta.tsv")}

    months = []
    for r in read_tsv("month_summary.tsv"):
        months.append({
            "m": int(r["月"][1:]),
            "rounds": int(r["回合数"]),
            "picks": int(r["选点总数"]),
            "events": int(r["不同事件数"]),
            "phase": r.get("剧情/体力/主行动", ""),
            "ncl": int(r.get("净化回合") or 0),
            "net": fnum(r.get("净收益")),
            "d": {k: fnum(r.get(f"Δ{k}")) for k in DIMS},
            "mk": {k: int(r.get(k) or 0) for k in MARKS},
        })

    events = []
    for r in read_tsv("event_summary.tsv"):
        events.append({
            "ev": r["事件"], "ph": r["阶段"], "rounds": int(r["回合数"]),
            "runs": int(r["涉及局数"]), "months": r["覆盖月"],
            "nch": int(r["选项数"] or 0), "per": fnum(r["每回合选点数"]),
            "ncl": int(r.get("净化回合") or 0),
            "net": fnum(r.get("净收益")),
            "pick": r["选点分布"], "seq": r["选点序列分布Top"],
            "d": {k: fnum(r.get(f"Δ{k}")) for k in DIMS},
            "mk": r.get("连带播报", ""),
        })

    by_month = {}
    for r in read_tsv("event_by_month.tsv"):
        m = int(r["月"][1:])
        by_month.setdefault(m, []).append({
            "ev": r["事件"], "ph": r["阶段"], "rounds": int(r["回合数"]),
            "pick": r["选点分布"], "seq": r["选点序列分布"],
            "text": (r.get("选点文本") or "")[:110],
            "ncl": int(r.get("净化回合") or 0),
            "net": fnum(r.get("净收益")),
            "d": {k: fnum(r.get(f"Δ{k}")) for k in DIMS},
            "mk": r.get("连带播报", ""),
        })
    for m in by_month:
        by_month[m].sort(key=lambda x: -x["rounds"])

    by_event = {}
    for r in read_tsv("pick_impact.tsv"):
        by_event.setdefault(r["事件"], []).append({
            "seq": r["选点序列"], "text": (r.get("选点文本") or "")[:140],
            "n": int(r["回合数"]),
            "ncl": int(r.get("净化回合") or 0),
            "net": fnum(r.get("净收益")),
            "d": {k: fnum(r.get(f"Δ{k}")) for k in DIMS},
            "mk": r.get("连带播报", ""),
        })
    for k in by_event:
        by_event[k].sort(key=lambda x: (x["net"] is None, -(x["net"] or 0)))
        for x in by_event[k]:
            x["ev"] = k

    total_rounds = sum(x["rounds"] for x in months)

    # 正/负项统计（粒度 = 事件 × 选点序列，即"真正要做的选择"）
    all_items = [x for k in by_event for x in by_event[k]]
    n_pos = sum(1 for x in all_items if x["net"] is not None and x["net"] > 0)
    n_neg = sum(1 for x in all_items if x["net"] is not None and x["net"] < 0)
    n_zero = sum(1 for x in all_items if x["net"] == 0)
    n_na = sum(1 for x in all_items if x["net"] is None)

    payload = {
        "gen": (datetime.now(timezone(timedelta(hours=8)))
                .strftime("%Y-%m-%d %H:%M (北京时间)")),
        "months": months, "events": events,
        "byMonth": by_month, "byEvent": by_event,
        "dims": DIMS, "dimCn": DIM_CN, "marks": MARKS,
        "meta": meta,
        "posneg": {"pos": n_pos, "neg": n_neg, "zero": n_zero, "na": n_na,
                   "items": len(all_items)},
        "totals": {"runs": meta.get("局", 0), "rounds": total_rounds,
                   "events": len(events),
                   "drama": sum(x["rounds"] for x in events if x["ph"] == "剧情")},
    }

    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False))
    OUT.write_text(html, encoding="utf-8")
    print(f"→ {OUT}  ({OUT.stat().st_size/1024:.0f} KB)｜"
          f"月 {len(months)}｜事件 {len(events)}｜回合 {total_rounds}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>九问 · 事件 × 选择 × 影响 全量普查（按 48 个月）</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --tx:#1c1f23; --tx2:#5b6470;
  --gain:#1f7a8c; --loss:#c2542b; --zero:#98a2ad; --accent:#2f6fdb;
  --chip:#eef1f5;
  --posbg:#e1f5ee; --posfg:#0f6e56; --posline:#1d9e75;
  --negbg:#fcebeb; --negfg:#a32d2d; --negline:#e24b4a;
  --posrow:rgba(29,158,117,.055); --negrow:rgba(226,75,74,.055);
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#14171a; --panel:#1b1f23; --line:#2b3037; --tx:#e8ebee; --tx2:#a3adb8;
         --gain:#4dbdc9; --loss:#e08a63; --zero:#6b7683; --accent:#6aa2f5; --chip:#242a31;
         --posbg:#04342c; --posfg:#7ee0bd; --posline:#1d9e75;
         --negbg:#501313; --negfg:#f3a3a3; --negline:#a32d2d;
         --posrow:rgba(29,158,117,.10); --negrow:rgba(226,75,74,.10); }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
  font:14px/1.6 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--panel);border-bottom:1px solid var(--line);
  padding:14px 22px}
h1{margin:0 0 4px;font-size:17px;font-weight:650;letter-spacing:.2px}
.sub{color:var(--tx2);font-size:12px}
.chips{margin-top:9px;display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;
  padding:2px 10px;font-size:12px;color:var(--tx2)}
.chip b{color:var(--tx);font-weight:600}
nav{display:flex;gap:2px;margin-top:11px;border-bottom:1px solid var(--line)}
nav button{appearance:none;background:none;border:0;border-bottom:2px solid transparent;
  color:var(--tx2);padding:7px 13px;font-size:13.5px;cursor:pointer;font-family:inherit}
nav button.on{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
main{padding:18px 22px 60px;max-width:1500px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
  margin-bottom:14px}
.card h2{margin:0 0 10px;font-size:14px;font-weight:650;color:var(--tx2);letter-spacing:.3px}
.mrail{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:14px}
.mrail button{appearance:none;font-family:inherit;cursor:pointer;background:var(--panel);
  border:1px solid var(--line);color:var(--tx2);border-radius:7px;padding:4px 9px;font-size:12px}
.mrail button.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.mrail button.dim{opacity:.45}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--tx2);font-weight:600;position:sticky;top:0;background:var(--panel);
  cursor:pointer;white-space:nowrap;z-index:5}
tbody tr:hover{background:var(--chip)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ev{font-weight:600}
.seq{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.txt{color:var(--tx2);font-size:12px;max-width:520px}
.d{display:inline-block;min-width:44px;text-align:right;font-variant-numeric:tabular-nums}
.d.pos{color:var(--gain);font-weight:600}
.d.neg{color:var(--loss);font-weight:600}
.d.z{color:var(--zero)}
td.cl{color:var(--tx2);font-size:11px}
.net{display:inline-block;min-width:54px;padding:1px 7px;border-radius:5px;font-size:12px;
  font-weight:500;font-variant-numeric:tabular-nums;text-align:center;white-space:nowrap}
.net.p{background:var(--posbg);color:var(--posfg);border:1px solid var(--posline)}
.net.n{background:var(--negbg);color:var(--negfg);border:1px solid var(--negline)}
.net.z{background:var(--chip);color:var(--tx2);border:1px solid var(--line)}
tbody tr>td:first-child{border-left:3px solid transparent}
tr.pr>td:first-child{border-left-color:var(--posline)}
tr.nr>td:first-child{border-left-color:var(--negline)}
tr.pr{background:var(--posrow)}
tr.nr{background:var(--negrow)}
.posbar{display:flex;height:26px;border-radius:5px;overflow:hidden;border:1px solid var(--line)}
.posbar i{display:block;height:100%}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--tx2);font-size:12px;margin-top:8px}
.legend b{color:var(--tx);font-weight:500}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:5px}
/* 红线维徽标：收益/代价落在 dignity / health / wealth 上（不计入净收益） */
.rl{display:inline-block;padding:0 5px;margin-right:4px;border-radius:4px;font-size:11px;
  font-variant-numeric:tabular-nums;white-space:nowrap;border:1px solid var(--line)}
.rl.p{background:var(--posbg);color:var(--posfg);border-color:var(--posline)}
.rl.n{background:var(--negbg);color:var(--negfg);border-color:var(--negline)}
.rlcell{white-space:nowrap}
.nul{color:var(--zero)}
.rltag{display:inline-block;background:var(--chip);border:1px dashed var(--line);border-radius:4px;
  padding:0 5px;font-size:11px;color:var(--tx2)}
.mk{display:inline-block;background:var(--chip);border:1px solid var(--line);border-radius:4px;
  padding:0 5px;margin-right:3px;font-size:11px;color:var(--tx2)}
.mk.hot{color:var(--loss);border-color:var(--loss)}
.bar{height:6px;border-radius:3px;background:var(--chip);overflow:hidden;min-width:60px}
.bar i{display:block;height:100%}
input[type=search]{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:8px;
  background:var(--panel);color:var(--tx);font-family:inherit;font-size:13px;margin-bottom:10px}
.note{color:var(--tx2);font-size:12px;line-height:1.75}
.note code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:11.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px}
.kpi{background:var(--chip);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kpi span{display:block;color:var(--tx2);font-size:11.5px}
.kpi b{font-size:16px;font-variant-numeric:tabular-nums}
.exp{background:var(--chip);border-left:3px solid var(--accent);padding:8px 11px;border-radius:0 6px 6px 0;
  margin:4px 0 9px;font-size:12px;color:var(--tx2)}
.hide{display:none}
small{color:var(--tx2)}
</style>
</head>
<body>
<header>
  <h1>九问 · 事件 × 选择 × 影响 全量普查</h1>
  <div class="sub" id="sub"></div>
  <div class="chips" id="chips"></div>
  <nav>
    <button data-v="rank" class="on">净收益正负</button>
    <button data-v="month">按月（M1–M48）</button>
    <button data-v="event">按事件</button>
    <button data-v="impact">选择影响</button>
  </nav>
</header>
<main>
  <section id="v-rank"></section>
  <section id="v-month" class="hide"></section>
  <section id="v-event" class="hide"></section>
  <section id="v-impact" class="hide"></section>
  <div class="card">
    <h2>口径与限制（务必先读）</h2>
    <div class="note" id="caveat"></div>
  </div>
</main>
<script>
const D = /*__DATA__*/;
const $ = s => document.querySelector(s);
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const dcell = (v, unit) => {
  if (v === null || v === undefined) return '<span class="d z">–</span>';
  const cls = v > 0 ? "pos" : (v < 0 ? "neg" : "z");
  const s = (v > 0 ? "+" : "") + (Number.isInteger(v) ? v : v.toFixed(2));
  return '<span class="d ' + cls + '">' + s + (unit||"") + '</span>';
};
const drow = (d, keys) => (keys || D.dims).map(k => '<td class="num">' + dcell(d[k]) + '</td>').join("");
const clsNet = v => (v === null || v === undefined) ? "z" : (v > 0 ? "p" : (v < 0 ? "n" : "z"));
const rowcls = v => (v === null || v === undefined) ? "" : (v > 0 ? "pr" : (v < 0 ? "nr" : ""));
const netcell = v => {
  if (v === null || v === undefined) return '<td class="num"><span class="net z">不可用</span></td>';
  const s = (v > 0 ? "+" : "") + (Number.isInteger(v) ? v : v.toFixed(2));
  return '<td class="num"><span class="net ' + clsNet(v) + '">' + s + '</span></td>';
};
/* 红线维徽标：dignity / health / wealth 不计入净收益，但它们的变化恰恰是生死线 */
const RL = [["dignity","尊严"],["health","健康"],["wealth","财富"]];
const redcell = d => {
  const parts = RL.filter(([k]) => typeof d[k] === "number" && Math.abs(d[k]) > 0.004)
    .map(([k,cn]) => { const v = d[k];
      return '<span class="rl ' + (v > 0 ? "p" : "n") + '">' + cn + (v > 0 ? "+" : "") +
        (Number.isInteger(v) ? v : v.toFixed(2)) + '</span>'; });
  return '<td class="rlcell">' + (parts.length ? parts.join("") : '<span class="nul">—</span>') + '</td>';
};
const mkcell = s => {
  if (!s) return '<td></td>';
  return '<td>' + s.split("／").map(x => {
    const hot = /爆雷/.test(x);
    return '<span class="mk' + (hot ? " hot" : "") + '">' + esc(x) + '</span>';
  }).join("") + '</td>';
};
const head = (cols) => '<tr>' + cols.map(c =>
  '<th' + (c.n ? ' class="num"' : '') + '>' + c.t + '</th>').join("") + '</tr>';

/* ---------------- 总览 ---------------- */
$("#sub").textContent = "生成于 " + D.gen + " ｜ 数据源：" + D.totals.runs +
  " 局完整事件流（工具调用/返回逐条解析；其中被中断的半局 " + (D.meta.中断局||0) + " 局" +
  ((D.meta["在跑局(跳过)"]||0) > 0 ? "；另有 " + D.meta["在跑局(跳过)"] + " 局普查时仍在写入，已排除" : "") + "）";
$("#chips").innerHTML = [
  ["局数", D.totals.runs], ["完整局", D.meta.完整局 ?? "–"], ["事件回合", D.totals.rounds],
  ["剧情回合", D.totals.drama], ["不同事件", D.totals.events], ["月跨度", "M1–M48"],
  ["正收益项", D.posneg.pos], ["负收益项", D.posneg.neg],
].map(([k,v]) => '<span class="chip">' + k + ' <b>' + v + '</b></span>').join("");

$("#caveat").innerHTML = `
<p><b>① 统计单位 = observe 回合，不是动作。</b>引擎的形状是 <code>observe → take_action(只回 success) → … → observe</code>。
一次 observe 之后可连续提交多个动作（体力阶段通常是 3 连选），中间不再给新状态。</p>
<p><b>② 因此「影响」是合并影响。</b>体力阶段第 2/3 个动作没有独立前状态 ⇒ 单项影响在数据上不可分离，
表中所有影响列都记的是<b>该回合全部选择合并后、到下次 observe 的状态差</b>。</p>
<p><b>③ 影响里含月末结算。</b>「晋升 / 工资 / 奖金 / 谈话」等是月切换时的连带播报，不是选项本身的直接效果；
已用 <span class="mk">标签</span> 标出，需要纯选项效果时请剔除带这些标签的回合。</p>
<p><b>④ 事件身份 = <code>current_event.title</code>。</b>引擎不提供事件 id，同标题即同事件。</p>
<p><b>⑤ 颜色</b>：<span class="d pos">蓝</span>=属性增加，<span class="d neg">橙</span>=属性减少（非股票口径）。</p>
<p><b>⑥ <code>警告</code> 列恒为 0 是<b>事实而非缺数</b>。</b>引擎不把警告当结构化字段下发：
逐条扫过 <b>9570 个 observe 的 payload</b>（含 events / description / choices）与全部 61 局事件流，
<b>没有任何一处</b>出现 <code>[warning]</code> 之类的机器可读告警。所谓"警告"只作为<b>剧情措辞</b>出现在事件描述里
（例：<i>「这是身体的第一次正式警告」</i>）。
⇒ 约束里"收到 <code>[warning]</code> 就锁死该维"那一条<b>在本数据上永不触发</b>，属空气约束。
真正可观测的整改信号是 <span class="mk">爆雷</span>（5 次）与 <span class="mk">埋雷</span>（24 次）。</p>
<p><b>⑦ 月末结算落在 <code>M(6k−1)</code>。</b>晋升 191 次 / 谈话 387 次 / 奖金 387 次<b>只出现在
M5·M11·M17·M23·M29·M35·M41·M47</b>，即"第 6k 月评审"的结果被记进了第 <b>6k−1</b> 个月末回合的后状态里
（结算在月界线上发生，而本表用回合<b>前</b>状态标月份）。
看某个月的"收益"时请把这批回合一并考虑，否则会误判 M6/M12 等评审月"没有奖励"。</p>
<p><b>⑧ ★ 影响列是<span class="d pos">净化后</span>的真均值，这是本报告最要紧的一条口径。</b>
Δ 列的分母 = 该组内<b>有后状态且不带 <span class="mk hot">爆雷</span><span class="mk hot">埋雷</span>
<span class="mk">晋升</span><span class="mk">工资</span><span class="mk">奖金</span><span class="mk">谈话</span> 标记</b>的回合数，
未变动的维度记 0。<b>为什么必须这样</b>——旧口径有两个方向都致命的伪影：
<br>· <b>分母只数"发生变动的回合"</b>：某选择 19 次里只有 1 次 −5，其余无变动，会被报成「均值 −5.0」；
<br>· <b>不剔污染</b>：<code>爆雷</code> 触发时 <b>output 被回写为 6 个月前的快照</b>（实测单回合 <code>Δoutput=−7</code>），
而<b>月末结算随机落在当月某一个回合上</b>（实测 <code>Δnetwork=−5</code>，同回合带 晋升+谈话 标记）。
两者都会冒充"这个选项的效果"。
<br>⇒ 表里每行都给出 <b>净化回合</b> 数，供判断可信度；净化回合为 0 的行其 Δ 不可用。</p>
<p><b>⑨ 有 ${D.meta.中断局||0} 局是被中断的半局</b>（进程被杀或超时，无 <code>score_report</code>）。
它们的事件是真实发生的，计入"事件次数"；但<b>不要</b>用它们算存活率或分数。
${(D.meta["在跑局(跳过)"]||0) > 0 ? `<br><b>⚠️ 本次普查另有 ${D.meta["在跑局(跳过)"]} 局在生成时仍在写入中</b>（无 <code>score_report</code> 且事件流刚被写过），
已整局排除——半截数据混进聚合值会让快照<b>不可复现</b>（再跑一次数字就变）。` : ""}</p>
<p><b>⑩ ★ <code>hidden_risk</code> 不可观察，所以"降险"在表里必然显示为零收益。</b>
引擎的 <code>current_state.status</code> 只暴露 <b>9 个键</b>：8 个属性 + <code>duration_in_level</code>
（已逐局核验，无隐藏字段）。因此体力动作 <code>处理历史埋雷</code> 在全部 117 次里
<b>Δ 全是 0</b>——它<b>不是无效</b>，而是它作用的对象（隐藏风险）根本不在这张表能看见的维度里，
其收益只以"没触发 <span class="mk hot">爆雷</span>"的形式隐性体现。
<br>⇒ <b>任何"只按表里的 Δ 打分"的策略都会系统性放弃降险</b>，然后在某一次 <code>hidden_risk ≥ 5</code> 爆雷时
被 output 回滚 6 个月一次性收走全部积累。这就是必须给降险设<b>独立硬规则</b>（而非靠得分驱动）的实证依据。</p>
<p><b>⑪ ★ 颜色有两层含义，别混用。</b>
<b>行级 绿/红</b>（<span class="net p">+x.xx</span> / <span class="net n">−x.xx</span> 徽标 + 行底色）
表示<b>总体净收益</b> = <code>Δ产出 ＋ Δ人脉 ＋ Δ技能</code>（净化后真均值），一列定正负，用于"这项该不该选"。
<b>单元格里的 <span class="d pos">蓝</span>／<span class="d neg">橙</span></b> 仍然只表示<b>该单维</b>的增减。
<br>为什么净收益只取这三项：它们是<b>唯一被职级截断</b>且构成晋升三维合取门（<code>skill≥8 ∧ output≥3 ∧ network≥3</code>）的维度，
也是绩效档位的主导项；而 <code>health / dignity / wealth</code> 是<b>红线</b>（有下限、不封顶收益）——
把它们加进来会让"拿健康换产出"显示成正收益，与策略结论正好相反。
<br>⚠️ <b>净收益为正 ≠ 该项一定该选</b>：还要看"净化回合"够不够、以及是否与当前瓶颈维匹配。
<br>为防误读，净收益视图的末列加了<b>红线维徽标</b>（<span class="rl p">健康+x</span> 等）：
一个净收益为 0 的项可能正在稳定回血（<code>健康恢复</code>），一个净收益为正的项也可能在悄悄掉健康——
<b>请两列一起读</b>。「零收益」桶有三种成因（顶格截断／只有红线维收益／作用对象不可观察），见该卡片内的说明。</p>`;

/* ---------------- 净收益正负（默认视图） ---------------- */
let rkQ = "";
function rkTable(rows, kind){
  if (!rows.length) return '<div class="note">（无符合条件的项）</div>';
  return `<table><thead>${head([{t:"事件"},{t:"序列",n:1},{t:"净收益",n:1},
    ...D.dims.slice(0,3).map(k=>({t:"Δ"+D.dimCn[k],n:1})),
    {t:"红线维（不计入净收益）"},{t:"净化",n:1},{t:"选点文本"}])}</thead>
    <tbody>${rows.map(x => `<tr class="${kind}">
      <td class="ev">${esc(x.ev||"")}</td><td class="seq">${esc(x.seq)}</td>
      ${netcell(x.net)}${drow(x.d, ["output","network","skill"])}${redcell(x.d)}
      <td class="num cl">${x.ncl ?? 0}</td><td class="txt">${esc(x.text)}</td></tr>`).join("")}</tbody></table>`;
}
function renderRank(){
  let items = [];
  D.events.forEach(e => (D.byEvent[e.ev] || []).forEach(x => items.push(x)));
  const q = rkQ.trim();
  if (q) items = items.filter(x => (x.ev||"").includes(q) || (x.text||"").includes(q));
  const known = items.filter(x => x.net !== null && x.net !== undefined);
  const pos = known.filter(x => x.net > 0).sort((a,b) => b.net - a.net);
  const neg = known.filter(x => x.net < 0).sort((a,b) => a.net - b.net);
  const zero = known.filter(x => x.net === 0);
  const tot = Math.max(1, known.length);
  const sumP = pos.reduce((s,x) => s + x.net, 0), sumN = neg.reduce((s,x) => s + x.net, 0);
  $("#v-rank").innerHTML = `
    <div class="card">
      <h2>总体收益（净收益 ＝ Δ产出 ＋ Δ人脉 ＋ Δ技能，净化后）</h2>
      <div class="posbar">
        <i style="width:${(pos.length/tot*100).toFixed(1)}%;background:var(--posline)"></i>
        <i style="width:${(zero.length/tot*100).toFixed(1)}%;background:var(--chip)"></i>
        <i style="width:${(neg.length/tot*100).toFixed(1)}%;background:var(--negline)"></i>
      </div>
      <div class="legend">
        <span><i class="sw" style="background:var(--posline)"></i>正收益 <b>${pos.length}</b> 项
          <span style="color:var(--posfg)">合计 +${sumP.toFixed(1)}</span></span>
        <span><i class="sw" style="background:var(--chip);border:1px solid var(--line)"></i>零收益 <b>${zero.length}</b> 项</span>
        <span><i class="sw" style="background:var(--negline)"></i>负收益 <b>${neg.length}</b> 项
          <span style="color:var(--negfg)">合计 ${sumN.toFixed(1)}</span></span>
      </div>
      <div class="note" style="margin-top:10px">
        一个「项」＝ 事件 × 选择序列。颜色只表示<b>总体净收益的方向</b>：
        <span class="net p">正</span> 与 <span class="net n">负</span>。
        单维单元格里的 <span class="d pos">蓝</span>／<span class="d neg">橙</span> 仍表示该维增减；
        末列的 <span class="rl p">健康+1.9</span> 式徽标是<b>不计入净收益的红线维</b>变化——
        它们有下限、触碰即出局，所以正负要单独看，不能和净收益混算。
      </div>
    </div>
    <div class="card">
      <input id="rkq" type="search" placeholder="筛选事件名或选项文本…（共 ${known.length} 项可判正负）" value="${esc(rkQ)}">
      <h2>正收益项（${pos.length}）</h2>
      ${rkTable(pos, "pr")}
    </div>
    <div class="card">
      <h2>负收益项（${neg.length}）</h2>
      ${rkTable(neg, "nr")}
    </div>
    <div class="card">
      <h2>零收益项（${zero.length}）—— 三种成因，别一律当成"没用"</h2>
      <div class="note" style="margin-bottom:8px">
        ① <b>顶格被截断</b>：该维已到职级上限，增量被引擎丢弃（<code>Δ=0</code> 是"被丢弃"，不是"无效果"）；
        ② <b>收益只落在红线维</b>：如 <code>健康恢复</code>（<span class="rl p">健康+1.86</span>）、
        <code>心理修复</code>（<span class="rl p">尊严+0.42</span>）——红线维不计入净收益，看末列徽标；
        ③ <b>作用对象不可观察</b>：<code>处理历史埋雷</code> 全部 <code>Δ=0</code>，
        因为 <code>hidden_risk</code> 根本不在可观察维度里（见口径 ⑩）。
      </div>
      ${rkTable(zero, "zr")}
    </div>`;
  const el = $("#rkq");
  el.oninput = () => { rkQ = el.value; const p = el.selectionStart;
    renderRank(); const n = $("#rkq"); n.focus(); n.setSelectionRange(p,p); };
}

/* ---------------- 按月 ---------------- */
let curM = 1;
function renderMonth(){
  const ms = D.months;
  const rail = ms.map(x => {
    const cls = x.m === curM ? "on" : (x.rounds < 40 ? "dim" : "");
    return `<button class="${cls}" data-m="${x.m}">M${x.m}</button>`;
  }).join("");
  const s = ms.find(x => x.m === curM) || {};
  const list = D.byMonth[curM] || [];
  $("#v-month").innerHTML = `
    <div class="mrail">${rail}</div>
    <div class="card">
      <h2>M${curM} 总览</h2>
      <div class="grid">
        <div class="kpi"><span>事件回合</span><b>${s.rounds ?? 0}</b></div>
        <div class="kpi"><span>选点总数</span><b>${s.picks ?? 0}</b></div>
        <div class="kpi"><span>不同事件</span><b>${s.events ?? 0}</b></div>
        <div class="kpi"><span>相位构成</span><b style="font-size:12px">${esc(s.phase||"")}</b></div>
        ${D.dims.map(k => `<div class="kpi"><span>Δ${D.dimCn[k]}（均值）</span><b>${dcell(s.d ? s.d[k] : null)}</b></div>`).join("")}
        ${D.marks.map(k => `<div class="kpi"${k === "警告" ? ' title="引擎无结构化告警字段，此列恒为 0（详见口径 ⑥）"' : ""}><span>${k}${k === "警告" ? " ⓘ" : ""}</span><b>${s.mk ? s.mk[k] : 0}</b></div>`).join("")}
      </div>
    </div>
    <div class="card">
      <h2>M${curM} 发生的事件（${list.length} 类 / ${list.reduce((a,b)=>a+b.rounds,0)} 回合）</h2>
      <table><thead>${head([{t:"事件"},{t:"阶段"},{t:"回合",n:1},{t:"净化",n:1},{t:"净收益",n:1},
        {t:"选点分布"},{t:"选点序列"},{t:"选点文本"},
        ...D.dims.map(k=>({t:"Δ"+D.dimCn[k],n:1})),{t:"连带播报"}])}</thead>
      <tbody>${list.map(x => `<tr class="${rowcls(x.net)}">
        <td class="ev">${esc(x.ev)}</td><td>${esc(x.ph)}</td><td class="num">${x.rounds}</td>
        <td class="num cl">${x.ncl ?? 0}</td>${netcell(x.net)}
        <td class="seq">${esc(x.pick)}</td><td class="seq">${esc(x.seq)}</td>
        <td class="txt">${esc(x.text)}</td>
        ${drow(x.d)}${mkcell(x.mk)}</tr>`).join("")}</tbody></table>
    </div>`;
  $("#v-month").querySelectorAll(".mrail button").forEach(b =>
    b.onclick = () => { curM = +b.dataset.m; renderMonth(); window.scrollTo({top:0,behavior:"smooth"}); });
}

/* ---------------- 按事件 ---------------- */
let evSort = {k:"rounds", dir:-1};
function renderEvent(){
  const q = ($("#evq") && $("#evq").value || "").trim();
  let rows = D.events.filter(x => !q || x.ev.includes(q) || (x.seq||"").includes(q));
  rows.sort((a,b) => {
    const k = evSort.k, A = a[k], B = b[k];
    const c = (typeof A === "number") ? A - B : String(A).localeCompare(String(B), "zh");
    return c * evSort.dir;
  });
  const cols = [{t:"事件"},{t:"阶段"},{t:"回合",n:1},{t:"净化",n:1},{t:"净收益",n:1},{t:"局数",n:1},
    {t:"月范围"},{t:"选项",n:1},
    {t:"选点/回合",n:1},{t:"选点分布"},{t:"最常见序列"},
    ...D.dims.map(k=>({t:"Δ"+D.dimCn[k],n:1})),{t:"连带播报"}];
  $("#v-event").innerHTML = `
    <div class="card">
      <input id="evq" type="search" placeholder="搜索事件名 / 选点序列…（共 ${D.events.length} 类事件）" value="${esc(q)}">
      <table><thead>${head(cols)}</thead>
      <tbody>${rows.map(x => `<tr data-ev="${esc(x.ev)}" class="${rowcls(x.net)}">
        <td class="ev">${esc(x.ev)}</td><td>${esc(x.ph)}</td>
        <td class="num">${x.rounds}</td><td class="num cl">${x.ncl ?? 0}</td>${netcell(x.net)}
        <td class="num">${x.runs}</td><td>${esc(x.months)}</td>
        <td class="num">${x.nch}</td><td class="num">${x.per ?? ""}</td>
        <td class="seq">${esc(x.pick)}</td><td class="txt">${esc(x.seq)}</td>
        ${drow(x.d)}${mkcell(x.mk)}</tr>`).join("")}</tbody></table>
      <div class="exp">点击任意行 → 展开该事件的「每个选择序列 → 合并影响」（已按净收益降序）。
        表格可按任意列排序；<b>净收益</b>为正的行带绿色标记、为负的带红色标记。</div>
      <table id="evd"><tbody></tbody></table>
    </div>`;
  const q2 = $("#evq");
  q2.oninput = () => { const p = q2.selectionStart; renderEvent();
    const n = $("#evq"); n.focus(); n.setSelectionRange(p,p); };
  $("#v-event").querySelectorAll("tbody tr[data-ev]").forEach(tr => tr.onclick = () => {
    const name = tr.dataset.ev, rows2 = D.byEvent[name] || [];
    $("#evd").innerHTML = `<thead>${head([{t:"事件（展开）"},{t:"选点序列"},{t:"回合",n:1},
      {t:"净化",n:1},{t:"净收益",n:1},
      ...D.dims.map(k=>({t:"Δ"+D.dimCn[k],n:1})),{t:"连带播报"},{t:"选点文本"}])}</thead>
      <tbody>${rows2.map(x => `<tr class="${rowcls(x.net)}">
        <td class="ev">${esc(name)}</td>
        <td class="seq">${esc(x.seq)}</td><td class="num">${x.n}</td>
        <td class="num cl">${x.ncl ?? 0}</td>${netcell(x.net)}
        ${drow(x.d)}${mkcell(x.mk)}<td class="txt">${esc(x.text)}</td></tr>`).join("")}</tbody>`;
    $("#evd").scrollIntoView({behavior:"smooth",block:"nearest"});
  });
}

/* ---------------- 选择影响 ---------------- */
let imQ = "";
function renderImpact(){
  const evs = D.events.map(x => x.ev).filter(x => !imQ || x.includes(imQ));
  const html = evs.slice(0, 40).map(name => {
    const rows = D.byEvent[name] || [];
    if (!rows.length) return "";
    return `<div class="card"><h2>${esc(name)}<small> ｜ ${rows.length} 种选择序列</small></h2>
      <table><thead>${head([{t:"选点序列"},{t:"回合",n:1},{t:"净化",n:1},{t:"净收益",n:1},
        ...D.dims.map(k=>({t:"Δ"+D.dimCn[k],n:1})),{t:"连带播报"},{t:"选点文本"}])}</thead>
      <tbody>${rows.map(x => `<tr class="${rowcls(x.net)}">
        <td class="seq">${esc(x.seq)}</td><td class="num">${x.n}</td>
        <td class="num cl">${x.ncl ?? 0}</td>${netcell(x.net)}
        ${drow(x.d)}${mkcell(x.mk)}<td class="txt">${esc(x.text)}</td></tr>`).join("")}</tbody></table></div>`;
  }).join("");
  $("#v-impact").innerHTML = `<div class="card">
      <input type="search" id="imq" placeholder="筛选事件名（默认展示回合数最多的前 40 类）…" value="${esc(imQ)}">
      <div class="note">每行 = 一种「选择序列 → 合并影响」。体力阶段的序列形如 <code>2→6→3</code>（3 连选），
      剧情阶段通常是单选项。<b>「净化」= 参与 Δ 计算的回合数</b>（已剔除带 爆雷/埋雷 的回合）；
      净化数远小于回合数时，该行 Δ 的代表性弱。
      <b>「净收益」</b>= Δ产出 ＋ Δ人脉 ＋ Δ技能，<span class="net p">正</span>＝绿、<span class="net n">负</span>＝红。</div></div>` + html;
  const q = $("#imq");
  q.oninput = () => { imQ = q.value; const p = q.selectionStart; renderImpact();
    const n = $("#imq"); n.focus(); n.setSelectionRange(p,p); };
}

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  ["rank","month","event","impact"].forEach(v =>
    $("#v-"+v).classList.toggle("hide", v !== b.dataset.v));
});

renderRank(); renderMonth(); renderEvent(); renderImpact();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
