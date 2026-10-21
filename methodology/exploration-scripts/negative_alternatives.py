"""负收益项的「替代方案」分析（同事件反事实）。

问题：**报告里那些净收益为负的选项，是我们选错了，还是这个事件本来就没有好选择？**

做法（同事件内对比，把事件上下文固定住，比跨事件比较干净得多）：
  1. 只取**单动作回合**（一轮 observe + 1 个 take_action）——体力位的 3 连选无法分离单项效果，排除；
  2. 按「事件 × 选项」聚合：净化后（剔除 埋雷/爆雷 回合）真均值的
     净收益 = Δ产出 + Δ人脉 + Δ技能，以及每个选项的样本数 n；
  3. 对每个**净收益 < 0 且 n ≥ MIN_N** 的选项，看同一事件里**其它选项**的表现：
       · 有其它选项 净收益 ≥ 0                 → 可避免（换选项即可转正）
       · 其它选项也都 < 0，但比它高             → 可减轻（仍要亏，选亏得最少的）
       · 它是该事件里最高的（其余更差）         → 不得不选（已是该事件最优解）
       · 其它选项样本都 < MIN_ALT_N             → 样本不足，暂不判
  4. 「每次可挽回」= 最佳替代 − 本选项；「累计可挽回」= 每次可挽回 × 我们实际选它的次数。

产物：
  analysis/event_census/负收益替代分析.tsv
  analysis/event_census/alternatives.html
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "event_census"

MIN_N = 5          # 判为「负收益选项」的最小样本
MIN_ALT_N = 3      # 替代选项能被采信的最小样本
NET_DIMS = ("output", "network", "skill")
RED_DIMS = ("health", "dignity")   # 红线维不计入净收益，但要展示——负收益可能是拿它们换的
MARGIN = 0.30      # 差异小于此值视为「无实质差别」
NET_EPS = 0.05     # |净收益| < 此值视为「约等于 0」，不进分析
POS_EPS = 0.10     # 替代选项净收益 ≥ 此值才算「转正」，否则只算「少亏」
RX_MIN_N = 5       # 反应信号（事件播报情绪词）被采信的最小样本
RX_FLAG = 0.50     # 替代选项的反应比本选项差 ≥ 此值 ⇒ 疑似「以三维换反应/降险」

DIRTY = {"埋雷", "爆雷"}


def clean(x):
    return x.get("has_post") and not (set(x.get("marks") or []) & DIRTY)


def net_of(x):
    d = x.get("delta") or {}
    return sum(d.get(k, 0) for k in NET_DIMS)


def load():
    recs = []
    with (OUT / "records.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            recs.append(json.loads(line))
    return recs


def build(recs):
    # (event, choice) -> 样本
    stat = defaultdict(lambda: {"n": 0, "net": 0.0, "dims": defaultdict(float),
                                "text": "", "phase": "", "runs": set(),
                                "rx_sum": 0, "rx_n": 0, "rx_bad": 0, "nch": 0})
    for x in recs:
        if not clean(x):
            continue
        picks = x.get("picks") or []
        if len(picks) != 1:            # 只取单动作回合（体力 3 连选无法分离）
            continue
        if x.get("phase") not in ("drama", "main"):
            continue
        # ★ 长链事件的**每一步是不同决策点**，但 title 相同（如 CI 事件两步都有 #1/#2）
        #   ⇒ 必须把「描述」纳入键，否则两步的选项会被混在一起（会得出错误的替代建议）。
        node = (x["event"], (x.get("event_desc") or "")[:120])
        key = (node, picks[0])
        s = stat[key]
        s["n"] += 1
        s["net"] += net_of(x)
        d = x.get("delta") or {}
        for k in NET_DIMS + RED_DIMS:
            s["dims"][k] += d.get(k, 0)
        s["phase"] = x["phase"]
        s["node"] = node
        s["nch"] = max(s["nch"], int(x.get("n_choices") or 0))
        s["runs"].add(x["run"])
        # ★ 反应信号：事件播报里的情绪词（笑0/偷偷1/皱眉2/复杂3/生气4），越小越好。
        #   hidden_risk 不可观察，这是唯一能事后看到的「对方反应」代理 ⇒ 用它识别「以三维换降险」。
        if x.get("risk") is not None:
            s["rx_sum"] += x["risk"]
            s["rx_n"] += 1
            if x["risk"] >= 2:
                s["rx_bad"] += 1
        if not s["text"]:
            for n, t in (x.get("choice_texts") or []):
                if n == picks[0]:
                    s["text"] = t
                    break
    for s in stat.values():
        s["net"] = s["net"] / s["n"]
        s["dims"] = {k: v / s["n"] for k, v in s["dims"].items()}
        s["rx"] = (round(s["rx_sum"] / s["rx_n"], 2) if s["rx_n"] >= RX_MIN_N else None)
        s["rx_bad_rate"] = (round(s["rx_bad"] / s["rx_n"], 2) if s["rx_n"] >= RX_MIN_N else None)
    return stat


def analyze(stat):
    by_event = defaultdict(list)
    for (node, ch), s in stat.items():
        by_event[node].append((ch, s))

    rows = []
    # ★ node = (事件标题, 描述前缀)；必须同时拿到两者，否则长链各步会被当成同一个决策点
    for node, items in by_event.items():
        items.sort(key=lambda kv: kv[0] if isinstance(kv[0], int) else 0)
        for ch, s in items:
            if s["n"] < MIN_N or s["net"] >= -NET_EPS:
                continue
            others = [(c2, s2) for c2, s2 in items if c2 != ch]
            reliable = [(c2, s2) for c2, s2 in others if s2["n"] >= MIN_ALT_N]
            # ★ 先看它是不是该事件里的最优解：是 ⇒ 换任何选项都更差 ⇒ 不得不选
            alln = [s2["net"] for _, s2 in items]
            is_best = s["net"] >= max(alln) - 1e-9
            if reliable:
                bc, bs = max(reliable, key=lambda kv: kv[1]["net"])
                diff = bs["net"] - s["net"]
                if is_best and len(others) > 0:
                    cat = "不得不选（已是该事件最优）"
                    best = (bc, bs, diff)          # 仍展示"次优"作对照（差值必为负）
                elif bs["net"] >= POS_EPS and diff >= MARGIN:
                    cat = "可避免（换选项即转正）"
                    best = (bc, bs, diff)
                elif diff >= MARGIN:
                    cat = "可减轻（换选项少亏）"
                    best = (bc, bs, diff)
                else:
                    cat = "无实质差别"
                    best = (bc, bs, diff)
            elif others:
                best = None
                cat = "样本不足（替代选项次数太少）"
            else:
                best = None
                cat = "独选项"
            # ★ 反应差：替代选项的「对方反应」明显更差 ⇒ 这个负收益可能是**买来的**，别急着换
            flag = ""
            if best:
                a, b, _ = best
                if s["rx"] is not None and b["rx"] is not None and (b["rx"] - s["rx"]) >= RX_FLAG:
                    flag = "疑似以三维换反应/降险"
            # ★ 性质判读：负收益是「买健康」「买安全」还是「纯失误」？三者处置完全不同
            kind = ""
            if cat.startswith(("可避免", "可减轻")) and best:
                dh = s["dims"].get("health", 0) - best[1]["dims"].get("health", 0)
                if dh >= 0.5:
                    kind = "健康账更优（别急改）"
                elif flag:
                    kind = "买安全/立场（分窗口付）"
                else:
                    kind = "纯失误（手法不当）"
            rows.append({
                "event": node[0], "phase": s["phase"], "choice": ch, "text": s["text"],
                "step": (node[1] or "")[:60],
                "net": round(s["net"], 2), "n": s["n"], "runs": len(s["runs"]),
                "dims": {k: round(v, 2) for k, v in s["dims"].items() if k in NET_DIMS},
                "red": {k: round(s["dims"].get(k, 0), 2) for k in RED_DIMS},
                "alt_red": ({k: round(best[1]["dims"].get(k, 0), 2) for k in RED_DIMS}
                            if best else None),
                "cat": cat,
                "alt": (best[0] if best else None),
                "alt_text": (stat[(node, best[0])]["text"] if best else ""),
                "alt_net": (round(best[1]["net"], 2) if best else None),
                "alt_n": (best[1]["n"] if best else None),
                "gain": (round(best[2], 2) if best else None),
                "total": (round(best[2] * s["n"], 1) if best else None),
                "rx": s["rx"], "rx_n": s["rx_n"], "rx_bad": s["rx_bad_rate"],
                "alt_rx": (best[1]["rx"] if best else None),
                "alt_rx_n": (best[1]["rx_n"] if best else None),
                "flag": flag, "kind": kind,
                "nch": s["nch"], "nopt": len(items),
                "untried": max(0, s["nch"] - len(items)),
                "alt_n_all": sum(s2["n"] for _, s2 in others),
            })
    rows.sort(key=lambda r: -(r["total"] or 0))
    return rows, by_event


def write_tsv(rows):
    cols = ["分类", "事件", "决策点(描述前缀)", "阶段", "选项", "选项文本", "净收益", "次数", "涉及局数",
            "反应均值", "反应样本", "负面反应率",
            "最佳替代", "替代文本", "替代净收益", "替代次数", "替代反应均值", "替代反应样本",
            "每次可挽回", "累计可挽回", "警示", "性质", "本选项红线", "可选数", "从未尝试数", "替代选项总次数"]
    with (OUT / "负收益替代分析.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(x if x is not None else "") for x in [
                r["cat"], r["event"], r["step"], r["phase"], r["choice"], r["text"], r["net"], r["n"],
                r["runs"], r["rx"], r["rx_n"], r["rx_bad"],
                r["alt"], r["alt_text"], r["alt_net"], r["alt_n"], r["alt_rx"], r["alt_rx_n"],
                r["gain"], r["total"], r["flag"], r["kind"],
                f'健康{r["red"].get("health",0):+.2f}/尊严{r["red"].get("dignity",0):+.2f}',
                r["nch"], r["untried"], r["alt_n_all"]]) + "\n")


TPL = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>九问 · 负收益项：有没有更好的选择</title><style>
:root{--bg:#f7f8fa;--panel:#fff;--tx:#1a1d21;--tx2:#5b6470;--line:#e3e6ea;--chip:#eef1f5;
--gain:#1d6fd8;--loss:#c0392b;--zero:#98a2ad;
--posbg:#e1f5ee;--posfg:#0f6e56;--posline:#1d9e75;--negbg:#fcebeb;--negfg:#a32d2d;--negline:#e24b4a;
--warnbg:#fff4e5;--warnfg:#8a5a00;--warnline:#e0a030;}
@media (prefers-color-scheme:dark){:root{--bg:#15181c;--panel:#1c2026;--tx:#e6e9ee;--tx2:#9aa4b0;
--line:#2c3239;--chip:#232a32;--gain:#6fb0ff;--loss:#ff8b7a;--zero:#6b7580;
--posbg:#12352c;--posfg:#7fd8bb;--posline:#1d9e75;--negbg:#3a1d1d;--negfg:#ff9d94;--negline:#e24b4a;
--warnbg:#3a2a12;--warnfg:#f0c070;--warnline:#e0a030;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:19px;margin:0 0 4px}.sub{color:var(--tx2);font-size:12.5px;margin-bottom:16px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:20px;padding:3px 11px;font-size:12px;color:var(--tx2)}
.chip b{color:var(--tx)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 4px}
.note{color:var(--tx2);font-size:12.5px;line-height:1.8}
.note code,.card code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:11.5px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--chip);color:var(--tx2);font-weight:600;position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ev{max-width:260px}.txt{max-width:430px;color:var(--tx2);font-size:12px}
.stp{color:var(--tx2);font-size:11px;margin-top:2px;opacity:.85}
.flg{display:inline-block;margin-top:3px;padding:1px 7px;border-radius:5px;font-size:11px;
background:var(--warnbg);color:var(--warnfg);border:1px solid var(--warnline)}
.net{display:inline-block;min-width:52px;padding:1px 7px;border-radius:5px;font-size:12px;text-align:center;
font-variant-numeric:tabular-nums;border:1px solid var(--line)}
.net.p{background:var(--posbg);color:var(--posfg);border-color:var(--posline)}
.net.n{background:var(--negbg);color:var(--negfg);border-color:var(--negline)}
.net.z{background:var(--chip);color:var(--tx2)}
.tag{display:inline-block;padding:1px 8px;border-radius:5px;font-size:11.5px;white-space:nowrap;border:1px solid var(--line)}
.tag.a{background:var(--posbg);color:var(--posfg);border-color:var(--posline)}
.tag.b{background:var(--warnbg);color:var(--warnfg);border-color:var(--warnline)}
.tag.c{background:var(--negbg);color:var(--negfg);border-color:var(--negline)}
.tag.d{background:var(--chip);color:var(--tx2)}
tr>td:first-child{border-left:3px solid transparent}
tr.ra>td:first-child{border-left-color:var(--posline)}
tr.rb>td:first-child{border-left-color:var(--warnline)}
tr.rc>td:first-child{border-left-color:var(--negline)}
tr.ra{background:rgba(29,158,117,.05)}tr.rc{background:rgba(226,75,74,.05)}
.posbar{display:flex;height:24px;border-radius:5px;overflow:hidden;border:1px solid var(--line);margin:6px 0 8px}
.posbar i{display:block;height:100%}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--tx2);font-size:12px}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0 4px}
.kpi{background:var(--chip);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kpi span{display:block;color:var(--tx2);font-size:11.5px}
.kpi b{font-size:17px;font-variant-numeric:tabular-nums}
</style></head><body><div class="wrap">
<h1>负收益项：有没有更好的选择？</h1>
<div class="sub">__SUB__</div>
__BODY__
</div></body></html>"""


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def netcell(v, cls_extra=""):
    if v is None:
        return '<td class="num"><span class="net z">–</span></td>'
    c = "p" if v > 0 else ("n" if v < 0 else "z")
    s = ("+" if v > 0 else "") + (f"{v:.2f}")
    return f'<td class="num"><span class="net {c}">{s}</span></td>'


def tag_of(cat):
    if cat.startswith("可避免"):
        return ('<span class="tag a">可避免</span>', "ra")
    if cat.startswith("可减轻"):
        return ('<span class="tag b">可减轻</span>', "rb")
    if cat.startswith("不得不选"):
        return ('<span class="tag c">不得不选</span>', "rc")
    return ('<span class="tag d">' + cat.split("（")[0] + '</span>', "")


def rxcell(v, n=None):
    if v is None:
        return '<td class="num"><span class="net z">–</span></td>'
    c = "p" if v <= 1 else ("n" if v >= 2 else "z")
    return (f'<td class="num"><span class="net {c}">{v:.2f}</span>'
            f'<div class="stp">n={n}</div></td>')


def redcell(v):
    if v is None:
        return '<td class="num">—</td>'
    h, d = v.get("health", 0), v.get("dignity", 0)
    def sp(x):
        c = "p" if x > 0.05 else ("n" if x < -0.05 else "z")
        s = ("+" if x > 0 else "") + f"{x:.1f}"
        return f'<span class="net {c}">{s}</span>'
    return f'<td class="num">{sp(h)}<div class="stp">{sp(d)}</div></td>'


def table(rows, show_alt=True):
    head = ["分类", "事件", "选项", "选项文本", "净收益", "红线 健康/尊严", "反应", "次数", "局数"]
    if show_alt:
        head.insert(1, "性质")
        head += ["最佳替代", "替代净收益", "替代红线", "替代反应", "每次可挽回", "累计可挽回"]
    th = "".join(f"<th>{h}</th>" for h in head)
    body = []
    for r in rows:
        tg, cls = tag_of(r["cat"])
        ev_html = esc(r["event"]) + (f'<div class="stp">{esc(r["step"])}…</div>' if r["step"] else "")
        kind = r.get("kind", "")
        kcls = ("b" if kind.startswith(("健康账", "买安全")) else
                ("c" if kind.startswith("纯失误") else "d"))
        ktd = f'<td><span class="tag {kcls}">{esc(kind.split("（")[0]) if kind else "—"}</span></td>'
        tds = [f'<td>{tg}</td>'] + ([ktd] if show_alt else []) + \
              [f'<td class="ev">{ev_html}</td>', f'<td class="num">{r["choice"]}</td>',
               f'<td class="txt">{esc(r["text"])}</td>',
               netcell(r["net"]), redcell(r["red"]), rxcell(r["rx"], r["rx_n"]),
               f'<td class="num">{r["n"]}</td>',
               f'<td class="num">{r["runs"]}</td>']
        if show_alt:
            if r["alt"] is not None:
                fl = (f'<div class="flg">⚠ {esc(r["flag"])}</div>' if r["flag"] else "")
                tds += [f'<td class="txt">#{r["alt"]} {esc(r["alt_text"])}{fl}</td>',
                        netcell(r["alt_net"]), redcell(r["alt_red"]),
                        rxcell(r["alt_rx"], r["alt_rx_n"]),
                        netcell(r["gain"]), f'<td class="num"><b>{r["total"]}</b></td>']
            else:
                tds += ['<td class="txt">—</td>'] + ['<td class="num">—</td>'] * 5
        body.append(f'<tr class="{cls}">' + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def table_blind(rows):
    head = ["分类", "事件", "选项", "选项文本", "净收益", "红线 健康/尊严", "反应", "次数", "局数",
            "可选数", "从未尝试", "替代选项总次数"]
    th = "".join(f"<th>{h}</th>" for h in head)
    body = []
    for r in rows:
        tg, cls = tag_of(r["cat"])
        ev_html = esc(r["event"]) + (f'<div class="stp">{esc(r["step"])}…</div>' if r["step"] else "")
        un = r["untried"]
        uncell = (f'<td class="num"><b style="color:var(--negfg)">{un}</b></td>' if un
                  else '<td class="num">0</td>')
        tds = [f'<td>{tg}</td>', f'<td class="ev">{ev_html}</td>', f'<td class="num">{r["choice"]}</td>',
               f'<td class="txt">{esc(r["text"])}</td>', netcell(r["net"]), redcell(r["red"]),
               rxcell(r["rx"], r["rx_n"]),
               f'<td class="num">{r["n"]}</td>', f'<td class="num">{r["runs"]}</td>',
               f'<td class="num">{r["nch"]}</td>', uncell, f'<td class="num">{r["alt_n_all"]}</td>']
        body.append(f'<tr class="{cls}">' + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_html(rows, meta):
    cats = defaultdict(list)
    for r in rows:
        cats[r["cat"].split("（")[0]].append(r)
    avoid = cats.get("可避免", [])
    ease = cats.get("可减轻", [])
    forced = cats.get("不得不选", [])
    unsure = cats.get("样本不足", []) + cats.get("无实质差别", []) + cats.get("独选项", [])
    tot_avoid = sum(r["total"] or 0 for r in avoid)
    tot_ease = sum(r["total"] or 0 for r in ease)
    n_all = len(avoid) + len(ease) + len(forced) + len(unsure)
    n_loss_forced = sum(r["n"] for r in forced)
    flagged = [r for r in avoid + ease if r["flag"]]
    try:
        nrun = int(meta.get("局", "0") or 0)
    except ValueError:
        nrun = 0
    per_run = (tot_avoid + tot_ease) / nrun if nrun else 0

    kpis = [("负收益项", n_all), ("可避免", len(avoid)), ("可减轻", len(ease)),
            ("不得不选", len(forced)), ("样本不足/无差别", len(unsure)),
            ("可避免的累计可挽回", f"{tot_avoid:.0f}"),
            ("可减轻的累计可挽回", f"{tot_ease:.0f}"),
            ("摊到每局", f"{per_run:.1f} 点/局"),
            ("不得不选的实际次数", n_loss_forced),
            ("⚠ 疑似降险代价", len(flagged))]
    grid = "".join(f'<div class="kpi"><span>{k}</span><b>{v}</b></div>' for k, v in kpis)

    bar = "".join(f'<i style="width:{w/max(1,n_all)*100:.1f}%;background:{c}"></i>'
                  for w, c in [(len(cats.get("可避免", [])), "var(--posline)"),
                               (len(cats.get("可减轻", [])), "var(--warnline)"),
                               (len(cats.get("不得不选", [])), "var(--negline)"),
                               (len(unsure), "var(--zero)")])

    b = []
    b.append('<div class="card"><h2>总览</h2>' + grid +
             '<div class="posbar">' + bar + '</div>' +
             '<div class="legend">'
             '<span><i class="sw" style="background:var(--posline)"></i>可避免：同一事件里有净收益 ≥ 0 的选项</span>'
             '<span><i class="sw" style="background:var(--warnline)"></i>可减轻：别的选项也亏，但亏得更少</span>'
             '<span><i class="sw" style="background:var(--negline)"></i>不得不选：这已是该事件最优解</span>'
             '<span><i class="sw" style="background:var(--zero)"></i>证据不够（样本不足／独选项／无差别）</span></div>'
             f'<div class="note" style="margin-top:10px">口径：只取<b>单动作回合</b>（一轮 observe + 1 个动作；'
             f'体力位的 3 连选无法分离单项效果，已排除）；净收益 = Δ产出＋Δ人脉＋Δ技能，'
             f'分母为<b>净化回合</b>（剔除带 <code>埋雷/爆雷</code> 的回合）。'
             f'判为负收益项需 ≥ {MIN_N} 次，替代选项被采信需 ≥ {MIN_ALT_N} 次，'
             f'差异 &lt; {MARGIN} 视为无实质差别，|净收益| &lt; {NET_EPS} 视为约等于 0（不入表）。'
             f'「反应」= 事件播报里的情绪词（笑 0／偷偷 1／皱眉 2／复杂 3／生气 4），<b>越小越好</b>，'
             f'是 <code>hidden_risk</code> 不可观察时唯一能事后看到的对方反应代理；样本 ≥ {RX_MIN_N} 才显示。</div></div>')

    b.append('<div class="card"><h2>① 可避免 —— 换一个选项就能转正（' + str(len(avoid)) + ' 项）</h2>' +
             '<div class="note" style="margin-bottom:8px">这一类是<b>纯决策失误</b>：同一事件里明明存在净收益为正的选项，'
             '我们却选了负的。「累计可挽回」= 每次差额 × 我们实际选它的次数，是这类失误的总账。'
             f'⚠ 但"负"不等于"错"，本表按<b>性质</b>再分三类，处置方式完全不同：</div>'
             '<div class="note" style="margin-bottom:8px">'
             '<b>健康账更优</b>（黄）：净收益为负，但相对替代项<b>省下 ≥ 0.5 点健康</b>——'
             '在 <code>health &lt; 6</code> 时这是<b>正确决策</b>，不该禁；'
             '正确写法是「只在健康已达标时才换成替代项」。<br>'
             '<b>买安全/立场</b>（黄）：反应信号显示替代项会让对方反应明显变差——'
             '这些是<b>降险支付</b>（<code>hidden_risk</code> 不可观察，普查看不到收益侧），按<b>窗口</b>付：'
             '非评审月照付，评审前一月才切。<br>'
             '<b>纯失误</b>（红）：既没买到健康也没买到反应——<b>同一目标换个手法就行</b>'
             '（例：当场澄清 → 会后书面澄清；严格阈值 → 放宽渐进；先改协议 → 先做 MVP）。'
             '<b>这一类才是真正该立刻改的</b>。</div>' +
             table(avoid) + '</div>')

    b.append('<div class="card"><h2>② 可减轻 —— 别的选项也亏，但能少亏（' + str(len(ease)) + ' 项）</h2>' +
             '<div class="note" style="margin-bottom:8px">事件本身是"坏事件"（所有选项都扣三维），但选项之间有量级差。'
             '目标是**选亏得最少的那个**，不是"不做选择"。</div>' + table(ease) + '</div>')

    b.append('<div class="card"><h2>③ 不得不选 —— 已是该事件最优解（' + str(len(forced)) + ' 项）</h2>' +
             f'<div class="note" style="margin-bottom:8px">这些负收益是<b>事件结构造成的，换选项也躲不掉</b>'
             f'（我们选的已经是该事件里净收益最高的）。它们一共被选了 <b>{n_loss_forced}</b> 次，'
             'TSV 里的「每次可挽回」对这类是<b>负数</b>，含义是"换到次优会再亏多少"。'
             '⇒ 这类<b>不该写进策略</b>（没有可执行空间），能做的只有：'
             '①在它出现前把该维顶到上限（截断后扣不动）；②把它留给红线维（健康/尊严）去付账。</div>' +
             table(forced, show_alt=False) + '</div>')

    if flagged:
        b.append('<div class="card"><h2>④ ⚠ 疑似「以三维换反应/降险」（' + str(len(flagged)) + ' 项）——换之前先想清楚</h2>' +
                 '<div class="note" style="margin-bottom:8px">这些项按净收益看是"亏"的，'
                 f'但替代选项的<b>对方反应明显更差</b>（反应均值高 ≥ {RX_FLAG}）。'
                 '由于 <code>hidden_risk</code> <b>不在可观察状态里</b>（<code>status</code> 只暴露 9 个键），'
                 '「处理历史埋雷」类动作在普查里 Δ 恒为 0——<b>不是无效，是作用对象看不见</b>。'
                 '⇒ 任何"只按 Δ 打分"的策略都会<b>系统性放弃降险</b>。'
                 '这些项的正确处置是：①不写进"禁用清单"；②在<b>非评审月</b>可以照付；'
                 '③在评审前一月（M5/M11/M17/M23）才切到替代选项。</div>' +
                 table(flagged) + '</div>')

    if unsure:
        blind = [r for r in unsure if r["untried"] > 0]
        blind.sort(key=lambda r: (-r["untried"], -(r["n"])))
        n_unt = sum(r["untried"] for r in blind)
        b.append('<div class="card"><h2>⑤ 探索盲区 —— 有别的选项，但我们从没试过（'
                 + str(len(unsure)) + ' 项，其中 ' + str(len(blind)) + ' 项存在未尝试选项）</h2>' +
                 '<div class="note" style="margin-bottom:8px">这些负收益项<b>不能断定是"选错"也不能断定是"不得不选"</b>：'
                 '替代选项要么一次都没被我们选中过（<b>从未尝试</b> &gt; 0），要么次数 &lt; '
                 f'{MIN_ALT_N}（证据不够）。合计有 <b>{n_unt}</b> 个「从未走过的分支」。'
                 '⇒ 这是<b>下一批实验最值钱的探索目标</b>：在 v10d 里对「次数多、净收益负、从未尝试 &gt; 0」'
                 '的决策点做<b>定向换选项试跑</b>，几次就能把「不知道」变成「可避免」或「不得不选」。</div>' +
                 table_blind(blind + [r for r in unsure if r["untried"] == 0]) + '</div>')

    b.append('<div class="card"><h2>⑥ 怎么读这张表（重要提醒）</h2><div class="note">'
             '<p><b>A. 同事件内比较 ≠ 因果。</b>同一个事件在不同职级/月份出现，选不同选项的人当时状态也不同；'
             '这里给出的是<b>条件均值</b>，不是"换选项必然得到这个差值"。当成排序线索用，别当精确预测。</p>'
             '<p><b>B. 净收益只算三维，红线维单列。</b>产出/人脉/技能是晋升合取门与绩效的主导项；'
             '健康/尊严是红线维（有下限、无上限），不计入净收益，单独成列（上行健康、下行尊严）。'
             '⇒ <b>"三维亏、健康赚"的项很可能是划算的</b>（尤其 <code>health &lt; 6</code> 时），'
             '不要只看净收益就禁掉；反过来"三维赚、尊严亏"的项也不能无脑选——'
             '实测牺牲尊严 91.5% 换不到正向收益。</p>'
             '<p><b>C. 负收益 ≠ 错。</b>③类（不得不选）说明有些损失是结构性的；'
             '真正要改的是①类——那是纯决策失误。</p>'
             '<p><b>D. 与暴露窗叠加看。</b>同样的负收益，发生在评审前一月（M5/M11/M17/M23 的前一月）'
             '代价会被放大：零余量时一次 −1 就判负。</p>'
             '<p><b>E. 「反应」只是代理，不是风险值。</b>它取自事件播报里的情绪词，'
             '只覆盖<b>当场能看到的反应</b>；埋下的雷要几个月后才爆，那时这条记录里看不到。'
             '所以它只能用来<b>怀疑</b>某个负收益是买来的，不能用来证明。</p>'
             '<p><b>F. 长链事件按「步」拆。</b>同一个标题的每一步是不同决策点，本表按'
             '（标题 + 描述前缀）分组；不拆会把第 1 步的选项推荐给第 2 步。</p></div></div>')

    sub = (f"数据源：{meta.get('局','?')} 局（完整 {meta.get('完整局','?')}／中断 {meta.get('中断局','?')}）"
           f"／{meta.get('回合','?')} 回合｜负收益项 {n_all} 项｜生成于 {meta['_gen']}").replace("｜", " ｜ ")
    html = TPL.replace("__BODY__", "".join(b)).replace("__SUB__", sub)
    (OUT / "alternatives.html").write_text(html, encoding="utf-8")
    print(f"→ {OUT/'alternatives.html'}  负收益项 {n_all}｜可避免 {len(avoid)}｜"
          f"可减轻 {len(ease)}｜不得不选 {len(forced)}｜其它 {len(unsure)}")


def main():
    import datetime
    recs = load()
    stat = build(recs)
    rows, by_event = analyze(stat)
    write_tsv(rows)
    meta = {}
    for line in (OUT / "meta.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        k, v = line.split("\t")
        meta[k] = v
    meta["_gen"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    write_html(rows, meta)
    print(f"→ {OUT/'负收益替代分析.tsv'}  {len(rows)} 行")


if __name__ == "__main__":
    sys.exit(main())
