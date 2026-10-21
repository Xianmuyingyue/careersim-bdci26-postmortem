#!/usr/bin/env python3
"""全量「事件 × 选择 × 影响」普查（按 48 个月分段统计）。

统计单位 = **observe 回合**（不是 take_action 动作）
----------------------------------------------------
引擎的交互形状（2026-09-26 实测，61 局）：
    observe(tool_result，带 current_state/current_event/choices/events)
      → take_action(tool_call，只回 {"success":true,"error":null})
      → take_action … （**同一回合可连提 2~3 个动作，中间不再给 observe**）
      → observe（下一次，才给出新状态）
⇒ 因此「一次 observe + 其后连续提交的全部动作」= **一个回合**：
   * **事件** = 该 observe 的 `current_event.title`（引擎不给 id，标题即身份）
   * **我们的选择** = 该回合提交的**动作序列**（体力阶段通常是 3 连选，notes 里自带 `Qk体力i/3`）
   * **影响** = 「该回合的 observe」与「下一回合的 observe」的状态差（**合并**影响）
⚠️ 体力阶段的第 2/3 个动作**没有独立前状态** ⇒ 它们的单项影响在数据上不可分离，
   只能按回合给出合并影响。本脚本所有「单项影响」列都标注了这一限制。

输出（`analysis/event_census/`）
-------------------------------
  event_by_month.tsv   月 × 事件：回合数 / 选点分布 / 平均影响 / 连带播报
  event_summary.tsv    事件级汇总（跨全部局）
  pick_impact.tsv      事件 × 选点序列：**「选择之后的影响」主表**
  pick_marginal.tsv    事件 × 单个选项：被选次数 + 所在回合的合并平均影响（标注）
  month_summary.tsv    月级汇总
  records.jsonl        全部回合明细（可审计）
  report.html          单文件可视化报告（无外部依赖）

★ 三条解析纪律（踩过的坑，勿改）
  1. `tool_call` 与 `tool_result` 共享 `tool_call_id`，**必须分两张去重表**。
  2. `payload.delta.result` 是**嵌套 Python repr**，须 `ast.literal_eval` → 内层再 `json.loads`。
  3. 影响里会混入**月末结算**（工资/奖金/晋升/谈话），那是可观察的连带后果，用 `marks` 标出。

★★ 影响列的两条口径（2026-09-26 修正，勿改回）
  A. **Δ 是"净化后真均值"**：分母 = 有后状态且**无** `爆雷/埋雷/晋升/工资/奖金/谈话` 标记的回合数，
     未变动的维度记 0；同时输出「净化回合」列供校验。
     旧口径有双重伪影：①分母只数"发生变动的回合"⇒ 19 次里 1 次 −5 被报成 −5.0；
     ②不剔污染 ⇒ `爆雷` 的**输出六个月回滚**（实测 d={output:−7}）与
       **随机落在一个回合上的月末结算**（实测 d={network:−5}）都会冒充"选项效果"。
  B. 想看**含结算的真实收支**就用 `month_summary.tsv` 的标记列，别用 Δ 列去推。
  C. **「净收益」列 = `Δoutput + Δnetwork + Δskill`（净化后真均值）**，用于一眼分出正/负项。
     只取这三个维度：它们是唯一被职级截断、且构成晋升三维合取门的维度，也是 `perf` 档位的主导项；
     `health / wealth / dignity` 是**红线**（有下限、不封顶收益），计入会把"拿健康换产出"算成正收益 ⇒ 不计入。
     净化回合为 0 时该列留空（不可用）。
  D. **在跑局必须排除**：批次正在写某局（无 `score_report.json` 且 events 文件刚被写过）时，
     该局是**半截数据** ⇒ 混进聚合值后快照不可复现（再跑一次数字就变）。
     打开 `CENSUS_SKIP_INFLIGHT=1` 跳过它（判据 600s 内被写过）；**无批次在跑时该开关无副作用**。
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUTROOT = REPO / ".career_sim_runner" / "career_emu" / "outputs" / "九问"
METRICS = HERE / "ab" / "metrics"
OUT = HERE / "event_census"
if not OUT.exists():          # ⚠️ 本沙箱里 mkdir(exist_ok=True) 会误报 EEXIST，勿改回
    OUT.mkdir(parents=True)

DIMS = ("output", "network", "skill", "dignity", "health", "wealth", "level", "energy")

# ★ 「在跑局」排除开关（CENSUS_SKIP_INFLIGHT=1）
#   动机：批次还在写某局时做普查，会把这局的**半截数据**混进聚合值，快照既不干净也不可复现
#         （再跑一次数字就变了）。判据 = **无 score_report.json 且 events 文件在 600s 内被写过**。
#   性质：**空跑无害** —— 没有批次在跑时，所有局 mtime 都是旧的 ⇒ 一个都不跳 ⇒ 结果与关掉时完全一致。
#   所以它可以直接常开；被跳过的局会记进 meta.tsv 的「在跑局(跳过)」供留痕。
SKIP_INFLIGHT = os.environ.get("CENSUS_SKIP_INFLIGHT") == "1"
INFLIGHT_AGE = 600

TITLE_ENERGY = "季度体力行动分配"
TITLE_MAIN = "季度主行动选择"
TITLE_HANDBOOK = "新员工手册"
PHASE_CN = {"init": "初始化", "energy": "体力", "main": "主行动",
            "drama": "剧情", "over": "结束", "unknown": "未识别"}

MARKERS = [("晋升", r"晋升"), ("工资", r"本月基本工资到账"), ("奖金", r"半年绩效奖金"),
           # ⚠️ 「警告」在 61 局 × 9496 回合里**一次都没命中**：引擎不把告警当下发字段，
           #    逐条扫过 9570 个 observe 的 payload 也没有任何 [warning] 类机器可读文本，
           #    "警告"只作剧情措辞出现在 description 里。列保留是为了留痕，恒 0 是事实。
           ("警告", r"\[warning\]|警告|警示|黄牌"), ("爆雷", r"爆雷|信任危机"),
           ("谈话", r"谈话"), ("埋雷", r"埋雷|隐患")]
RISK_WORD = [("笑", 0), ("偷偷", 1), ("皱眉", 2), ("复杂", 3), ("生气", 4)]


# --------------------------------------------------------------------- 解析
def unwrap(result):
    if not isinstance(result, str):
        return None
    inner = None
    try:
        d = ast.literal_eval(result)
        if isinstance(d, dict):
            inner = d.get("result")
    except Exception:
        pass
    if inner is None:
        m = re.search(r'\{\s*"(?:current_state|error|result)"', result)
        if not m:
            return None
        inner = result[m.start():]
    if not isinstance(inner, str):
        return None
    s = inner.strip()
    if not s.startswith("{"):
        return None
    try:
        return json.loads(s)
    except Exception:
        try:
            return json.JSONDecoder().raw_decode(s)[0]
        except Exception:
            return None


def read_events(path: Path):
    """两张去重表，返回时间有序的 [(seq, kind, obj)]。"""
    seen_call, seen_res = set(), set()
    out = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            pl = (d.get("payload") or {}).get("delta") or d.get("payload") or {}
            tc = pl.get("tool_call")
            if tc:
                tid = tc.get("tool_call_id")
                if tid in seen_call:
                    continue
                seen_call.add(tid)
                out.append((d.get("seq"), "call",
                            {"name": tc.get("name"), "args": tc.get("arguments")}))
            elif pl.get("tool_name"):
                tid = pl.get("tool_call_id")
                if tid in seen_res:
                    continue
                seen_res.add(tid)
                out.append((d.get("seq"), "result",
                            {"name": pl.get("tool_name"), "result": pl.get("result")}))
    return out


def phase_of(payload, state):
    if state.get("error"):
        return "over"
    title = ((payload.get("current_event") or {}).get("title") or "").strip()
    if title == TITLE_HANDBOOK:
        return "init"
    if title == TITLE_ENERGY:
        return "energy"
    if title == TITLE_MAIN:
        return "main"
    if payload.get("choices"):
        return "drama"
    return "unknown"


def snap(payload, seq):
    st = payload["current_state"]
    s = st.get("status") or {}
    tm = st.get("time") or {}
    ce = payload.get("current_event") or {}
    fl = st.get("simulation_flags") or {}
    return {
        "seq": seq, "month": tm.get("current_month"), "phase": phase_of(payload, st),
        "title": (ce.get("title") or "").strip(),
        "desc": (ce.get("description") or "").replace("\n", " "),
        "choices": [(c.get("choice"), (c.get("action") or "").replace("\n", " ").strip())
                    for c in (payload.get("choices") or [])],
        "events": payload.get("events") or "",
        "alive": fl.get("alive"), "failed": fl.get("failed"),
        **{k: s.get(k) for k in DIMS},
    }


def parse_run(ev_file: Path):
    """→ (rounds, orphan_actions)。rounds = 一个 observe + 其后连续动作。"""
    rounds, orphan = [], 0
    cur = None
    for seq, kind, obj in read_events(ev_file):
        nm = obj["name"] or ""
        if kind == "result" and nm.endswith("_observe"):
            payload = unwrap(obj.get("result"))
            if not payload or "current_state" not in payload:
                if cur is not None:
                    rounds.append(cur)
                    cur = None
                continue
            s = snap(payload, seq)
            if cur is not None:              # 上一回合结算
                cur["post"] = s
                rounds.append(cur)
            cur = {"pre": s, "picks": [], "seq": seq, "post": None}
        elif kind == "call" and nm.endswith("_take_action"):
            try:
                args = json.loads(obj.get("args") or "{}")
            except Exception:
                args = {}
            if cur is None:
                orphan += 1
                continue
            cur["picks"].append({
                "seq": seq, "choice": args.get("choice"),
                "notes": (args.get("notes") or "").replace("\t", " ")
                          .replace("\n", " ")[:600],
            })
    if cur is not None:
        rounds.append(cur)
    return rounds, orphan


def delta_of(pre, post):
    if post is None:
        return {}
    d = {}
    for k in DIMS:
        a, b = pre.get(k), post.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            dv = b - a
            if dv:
                d[k] = round(dv, 4)
    return d


def marks_of(post):
    if post is None:
        return [], None
    txt = post.get("events") or ""
    mk = [n for n, p in MARKERS if re.search(p, txt)]
    risk = None
    for w, v in RISK_WORD:
        if w in txt:
            risk = v
    return mk, risk


# --------------------------------------------------------------------- 主流程
def main():
    runs = sorted(p for p in OUTROOT.iterdir() if p.is_dir())
    recs = []
    st = Counter()

    for rd in runs:
        evs = sorted(rd.glob("events-*.jsonl"))
        if not evs:
            continue
        # ★ 正在被写的局：无 score_report 且 events 刚被写过 ⇒ 半截数据，跳过（见 SKIP_INFLIGHT 注释）
        if SKIP_INFLIGHT and not (rd / "score_report.json").exists():
            try:
                if time.time() - evs[0].stat().st_mtime < INFLIGHT_AGE:
                    st["在跑局(跳过)"] += 1
                    print(f"  [skip] {rd.name}: 正在写入（在跑局，已跳过）", file=sys.stderr)
                    continue
            except OSError:
                pass
        try:
            rounds, orphan = parse_run(evs[0])
        except Exception as e:
            st["解析失败局"] += 1
            print(f"  [warn] {rd.name}: {e}", file=sys.stderr)
            continue
        # ★★ 「有 score_report.json」≠ 真对局（见 docstring 口径 D）：
        #    空壳局（旧会话复用，token=0 / events 6KB）与张冠李戴局（只有 bash/file 调用）
        #    **一次 take_action 都没有** ⇒ 整局跳过，否则它们会带着上一局的分数混进聚合值。
        if not any(r["picks"] for r in rounds):
            st["非对局局(跳过)"] += 1
            print(f"  [skip] {rd.name}: 无 take_action（非对局，已跳过）", file=sys.stderr)
            continue
        st["局"] += 1
        st["孤立动作"] += orphan

        # ★ 无 score_report = 被中断的半局（进程被杀/超时）；必须在计数前判定
        complete = (rd / "score_report.json").exists()
        st["完整局" if complete else "中断局"] += 1

        arm = outcome = score = None
        mf = METRICS / f"{rd.name}.json"
        if mf.exists():
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                arm, score = m.get("arm"), m.get("score")
                outcome = m.get("ending")
            except Exception:
                pass
        sr = rd / "score_report.json"
        if sr.exists():
            try:
                es = json.loads(sr.read_text(encoding="utf-8")).get("ending_score") or {}
                outcome = es.get("outcome") or outcome
                score = es.get("quantitative_score", score)
            except Exception:
                pass

        for r in rounds:
            pre, post = r["pre"], r["post"]
            picks = r["picks"]
            if not picks:
                # 纯观测回合：agent 只 observe 未行动（含 GAME OVER 后的收尾观测）⇒ 不是「事件」
                st["回合无动作"] += 1
                continue
            if pre["phase"] in ("over", "unknown"):
                st["非事件回合"] += 1
                continue
            d = delta_of(pre, post)
            mk, risk = marks_of(post)
            if post is None:
                st["回合无后状态"] += 1
            ch_seq = "→".join("?" if p["choice"] is None else str(p["choice"])
                              for p in picks) or "(无)"
            ch_txt = " ｜ ".join(
                t for p in picks
                for n, t in pre["choices"] if n == p["choice"]) or "(无)"
            recs.append({
                "run": rd.name, "arm": arm or "?", "outcome": outcome or "?",
                "complete": complete, "score": score,
                "seq": r["seq"], "month": pre["month"],
                "quarter": (pre["month"] - 1) // 3 + 1 if pre["month"] else None,
                "phase": pre["phase"], "event": pre["title"] or "(无标题)",
                "event_desc": pre["desc"],
                "n_choices": len(pre["choices"]),
                "picks": [p["choice"] for p in picks],
                "pick_seq": ch_seq, "pick_text": ch_txt,
                "pick_n": len(picks),
                "notes": " ｜ ".join(p["notes"] for p in picks)[:900],
                "choice_texts": pre["choices"],
                "delta": d, "marks": mk, "risk": risk,
                "has_post": post is not None,
                "pre": {k: pre.get(k) for k in DIMS},
                "post": {k: (post or {}).get(k) for k in DIMS},
                "post_title": (post or {}).get("title"),
                "post_events": (post or {}).get("events", "")[:400],
            })

    print(f"局 {st['局']}（完整 {st['完整局']}／中断 {st['中断局']}）｜回合 {len(recs)}"
          f"｜无后状态 {st['回合无后状态']}"
          f"｜无动作 {st['回合无动作']}｜孤立动作 {st['孤立动作']}"
          f"｜解析失败局 {st['解析失败局']}"
          + (f"｜在跑局跳过 {st['在跑局(跳过)']}" if SKIP_INFLIGHT else ""))

    # ------------------------------------------------------------- 聚合工具
    # ★★ 两处口径修正（2026-09-26，物证见 analysis/event_census/report.html 口径 ⑧）
    #   ① 分母：旧版 `[x["delta"][k] for x in rs if k in x["delta"]]` **只数"发生变动的回合"**
    #      ⇒ 19 次里仅 1 次 −5 会被算成「均值 −5.0」。现改为**全部净化回合**做分母，未变动记 0。
    #   ② 污染：`爆雷/埋雷` 回合里含**输出六个月回滚**（如 d={output:−7}），会冒充"选项效果"。
    #      ⚠️ 只剔这两类。**不能**把 `工资/奖金/晋升/谈话` 也算脏：
    #      月末结算总是落在当月的**最后一个回合**（= 主行动回合）⇒ 一剔就把整个主行动相位清空。
    #      它们对 Δ 的影响是"加一个近似常量"（工资 ≈ +0.7 wealth），用标记列与口径 ⑧ 说明即可。
    DIRTY_MARKS = {"埋雷", "爆雷"}

    def clean_of(x):
        return x["has_post"] and not (set(x["marks"]) & DIRTY_MARKS)

    def mean_delta(rs):
        """→ (真均值 dict, 净化回合数)。"""
        pool = [x for x in rs if clean_of(x)]
        if not pool:
            return {k: "" for k in DIMS}, 0
        return ({k: round(sum(x["delta"].get(k, 0) for x in pool) / len(pool), 2) for k in DIMS},
                len(pool))

    # ★ 总体收益（净收益）= 三个**硬指标**之和（净化后真均值）
    #   为什么是 output / network / skill 三项：
    #     ① 它们是**唯一被职级截断**、且直接进入晋升三维合取门（`skill≥8 ∧ output≥3 ∧ network≥3`）的维度；
    #     ② `perf` 档位也是由 output 主导 ⇒ 它们同时是分数与晋升的驱动项；
    #     ③ `health / wealth / dignity` 是**红线**（有下限约束、不封顶收益），把它们加进来会让
    #        "拿健康换产出"显得是正收益，与策略结论相反 ⇒ **不计入**。
    NET_DIMS = ("output", "network", "skill")

    def net_of(md, ncl):
        if ncl <= 0 or any(md.get(k) in ("", None) for k in NET_DIMS):
            return ""
        return round(sum(md[k] for k in NET_DIMS), 2)

    def pick_dist(rs):
        c = Counter()
        for x in rs:
            for p in x["picks"]:
                c[p if p is not None else "?"] += 1
        return "／".join(f"{k}:{v}" for k, v in sorted(c.items(), key=lambda kv: str(kv[0])))

    def seq_dist(rs):
        return "／".join(f"{k}:{v}" for k, v in Counter(x["pick_seq"] for x in rs).most_common())

    def mark_str(rs):
        return "／".join(f"{k}:{v}" for k, v in
                         Counter(t for x in rs for t in x["marks"]).most_common())

    # 月 × 事件
    key = lambda x: (x["month"] if x["month"] is not None else -1, x["event"])
    by_me = defaultdict(list)
    for x in recs:
        by_me[key(x)].append(x)
    with (OUT / "event_by_month.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(["月", "季", "阶段", "事件", "选项数", "回合数", "选点分布",
                            "选点序列分布", "选点文本", *[f"Δ{k}" for k in DIMS],
                            "净收益", "净化回合", "连带播报", "例局"]) + "\n")
        for (m, ev), rs in sorted(by_me.items()):
            md, ncl = mean_delta(rs)
            ex = max(rs, key=lambda x: len(x["notes"]))
            fh.write("\t".join(map(str, [
                f"M{m}", rs[0]["quarter"], PHASE_CN.get(rs[0]["phase"], rs[0]["phase"]),
                ev, rs[0]["n_choices"], len(rs), pick_dist(rs), seq_dist(rs),
                ex["pick_text"][:120], *[md[k] for k in DIMS],
                net_of(md, ncl), ncl, mark_str(rs), ex["run"],
            ])) + "\n")

    # 事件级
    by_ev = defaultdict(list)
    for x in recs:
        by_ev[x["event"]].append(x)
    with (OUT / "event_summary.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(["事件", "阶段", "回合数", "涉及局数", "覆盖月", "选项数",
                            "每回合选点数", "选点分布", "选点序列分布Top",
                            *[f"Δ{k}" for k in DIMS], "净收益", "净化回合", "连带播报", "例局"]) + "\n")
        for ev, rs in sorted(by_ev.items(), key=lambda x: -len(x[1])):
            md, ncl = mean_delta(rs)
            mons = sorted({x["month"] for x in rs if x["month"] is not None})
            fh.write("\t".join(map(str, [
                ev, PHASE_CN.get(rs[0]["phase"], rs[0]["phase"]), len(rs),
                len({x["run"] for x in rs}),
                f"M{mons[0]}–M{mons[-1]}" if mons else "", rs[0]["n_choices"],
                round(sum(x["pick_n"] for x in rs) / len(rs), 2),
                pick_dist(rs), seq_dist(rs)[:200],
                *[md[k] for k in DIMS], net_of(md, ncl), ncl, mark_str(rs), rs[0]["run"],
            ])) + "\n")

    # 事件 × 选点序列（影响主表）
    by_ec = defaultdict(list)
    for x in recs:
        by_ec[(x["event"], x["pick_seq"])].append(x)
    with (OUT / "pick_impact.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(["事件", "选点序列", "选点文本", "回合数", "含此序列的局数",
                            *[f"Δ{k}" for k in DIMS], "净收益", "净化回合", "连带播报", "例局"]) + "\n")
        for (ev, sq), rs in sorted(by_ec.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
            md, ncl = mean_delta(rs)
            fh.write("\t".join(map(str, [
                ev, sq, rs[0]["pick_text"][:200], len(rs),
                len({x["run"] for x in rs}),
                *[md[k] for k in DIMS], net_of(md, ncl), ncl, mark_str(rs), rs[0]["run"],
            ])) + "\n")

    # 事件 × 单个选项（边缘分布；影响为合并值）
    by_ech = defaultdict(list)
    for x in recs:
        for p in set(x["picks"]):
            by_ech[(x["event"], p)].append(x)
    with (OUT / "pick_marginal.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(["事件", "选项", "选项文本", "被选次数", "含该项的回合数",
                            *[f"Δ{k}" for k in DIMS], "净收益", "净化回合", "备注"]) + "\n")
        for (ev, p), rs in sorted(by_ech.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
            md, ncl = mean_delta(rs)
            txt = next((t for x in rs for n, t in x["choice_texts"] if n == p), "")
            note = "影响为该选项所在回合的合并值" if rs[0]["pick_n"] > 1 else "单选项回合，影响即该项效果"
            fh.write("\t".join(map(str, [
                ev, p if p is not None else "?", txt[:200], len(rs), len(rs),
                *[md[k] for k in DIMS], net_of(md, ncl), ncl, note,
            ])) + "\n")

    # 月级
    by_m = defaultdict(list)
    for x in recs:
        by_m[x["month"]].append(x)
    with (OUT / "month_summary.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(["月", "回合数", "选点总数", "不同事件数", "剧情/体力/主行动",
                            *[f"Δ{k}" for k in DIMS], "净收益", "净化回合",
                            "晋升", "警告", "爆雷", "谈话", "埋雷", "工资", "奖金"]) + "\n")
        for m in sorted(k for k in by_m if k is not None):
            rs = by_m[m]
            md, ncl = mean_delta(rs)
            ph = Counter(PHASE_CN.get(x["phase"], x["phase"]) for x in rs)
            mk = Counter(t for x in rs for t in x["marks"])
            fh.write("\t".join(map(str, [
                f"M{m}", len(rs), sum(x["pick_n"] for x in rs),
                len({x["event"] for x in rs}),
                "／".join(f"{k}:{v}" for k, v in ph.most_common()),
                *[md[k] for k in DIMS], net_of(md, ncl), ncl,
                *[mk.get(t, 0) for t in ("晋升", "警告", "爆雷", "谈话", "埋雷", "工资", "奖金")],
            ])) + "\n")

    with (OUT / "records.jsonl").open("w", encoding="utf-8") as fh:
        for x in recs:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")

    # 元信息（供 build_event_report.py 读，避免把局数硬编码在报告里）
    with (OUT / "meta.tsv").open("w", encoding="utf-8") as fh:
        fh.write("键\t值\n")
        for k, v in (("局", st["局"]), ("完整局", st["完整局"]), ("中断局", st["中断局"]),
                     ("在跑局(跳过)", st["在跑局(跳过)"]), ("非对局局(跳过)", st["非对局局(跳过)"]),
                     ("回合", len(recs)), ("无后状态回合", st["回合无后状态"]),
                     ("无动作回合", st["回合无动作"]), ("孤立动作", st["孤立动作"]),
                     ("解析失败局", st["解析失败局"])):
            fh.write(f"{k}\t{v}\n")

    print(f"→ {OUT} ：event_by_month.tsv · event_summary.tsv · pick_impact.tsv "
          f"· pick_marginal.tsv · month_summary.tsv · records.jsonl · meta.tsv")
    return recs


if __name__ == "__main__":
    main()
