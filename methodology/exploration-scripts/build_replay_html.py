"""Build a single-file HTML replay browser for all finished CareerSim runs.

Usage:
    python3 analysis/build_replay_html.py [--out PATH] [--max-narrative N]

Reads every run directory under
    .career_sim_runner/career_emu/outputs/九问/<run>/
that contains both a `replay-*.md` and a `score_report.json`, parses the replay
markdown into a structured per-month / per-turn timeline, and emits ONE
self-contained HTML file (inline CSS + JS, zero external dependencies).

Design notes
------------
* The replay markdown is the richest human-readable artefact, but it is not a
  stable API. Parsing is therefore defensive: any block that does not match a
  known shape is preserved as raw text rather than dropped.
* Month headers are standalone H2s (`## 第 N 月 · …`). Turn blocks are H3s
  (`### 回合 N · title`) *inside* a month. Free text between/after turn blocks
  belongs to the month (payroll, HR whispers, half-year talk, promotion notice).
* State lines (`**状态:** level=…, health=…`) give the numeric series used for
  the charts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
DEFAULT_OUT = os.path.join(os.path.dirname(REPO), "analysis", "replay_browser.html")
EMULATOR_LOG_DIR = os.path.join(REPO, ".career_sim_runner", "career_emu", "emulator_logs")

TSV = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore", "results.tsv")
SUMMARY_MD = os.path.join(os.path.dirname(REPO), ".workbuddy", "logs", "explore", "summary8.md")
METRICS_DIR = os.path.join(REPO, "analysis", "ab", "metrics")

MONTH_RE = re.compile(r"^##\s*第\s*(\d+)\s*月\s*·\s*第\s*(\d+)\s*季度\s*·\s*第\s*(\d+)\s*年\s*$")
TURN_RE = re.compile(r"^###\s*回合\s*(\d+)\s*·\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^###\s*(.+?)\s*$")
STATE_RE = re.compile(r"^\*\*状态:\*\*\s*(.+?)\s*$")
CHOICE_RE = re.compile(r"^\*\*选择:\*\*\s*(.+?)\s*$")
REASON_RE = re.compile(r"^\*\*理由:\*\*\s*(.+?)\s*$")
OPT_RE = re.compile(r"^-\s*\[(\d+)\]\s*(.+?)\s*$")
OPT_HDR_RE = re.compile(r"^\*\*可选项:\*\*\s*$")

BONUS_RE = re.compile(r"半年绩效奖金（([SABCD])）：([+-][\d.]+)")
PROMO_RE = re.compile(r"晋升通知：(.+)")
PAY_RE = re.compile(r"本月基本工资到账：([+-][\d.]+)（(L\d)）")
TALK_RE = re.compile(r"【半年谈话】(.+)")
HR_RE = re.compile(r"(笑着|偷偷|皱着眉头|神情复杂|生气)地?(?:跟你说|说)[，,：:]?\s*(.+?)\s*$")
BURST_RE = re.compile(r"打了水漂")

HR_LADDER = {"笑着": "L0", "偷偷": "L1", "皱着眉头": "L2",
             "神情复杂": "L3", "生气": "L4+"}
HR_LABEL = {"L0": "HR 0 安全", "L1": "HR 1 轻微", "L2": "HR 2 累积",
            "L3": "HR 3 危急", "L4+": "HR 4+ 临爆"}

GOOD_KW = ("这半年你扛的事我都记着", "上面问部门骨干名单时，我第一个想到你",
           "你最近的表现符合预期", "该准备的材料提前整理好",
           "下个窗口我会重点推你", "半年后我们再看一档")
AVG_KW = ("没有要批你的意思", "只会忙、不会赢", "用同一套标准再看你", "照本宣科",
          "你这半年不好不坏", "还在观察名单里")
BAD_KW = ("最后一次调整窗口", "我不得不重新评估", "需跟进", "半年内再没改善")


def parse_state(text: str) -> dict:
    out: dict = {}
    for kv in text.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "level":
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def classify_talk(text: str) -> str | None:
    # 引擎 first_match_descending：good → average → bad
    # 注意：「你这半年不好不坏」「还在观察名单里」是 average 档指纹（narratives.json），不是 bad
    for kw in GOOD_KW:
        if kw in text:
            return "good"
    for kw in AVG_KW:
        if kw in text:
            return "average"
    for kw in BAD_KW:
        if kw in text:
            return "bad"
    return None


def parse_replay(path: str, max_narrative: int = 0) -> dict:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    head: dict = {}
    for line in raw.splitlines():
        if line.startswith("- 游戏 Session:"):
            head["session"] = line.split("`")[1] if "`" in line else ""
        elif line.startswith("- 决策步数:"):
            head["steps"] = line.split(":", 1)[1].strip()
        elif line.startswith("- 最后观测:"):
            head["last"] = line.split(":", 1)[1].strip()

    months: list[dict] = []
    cur_month: dict | None = None
    cur_section: dict | None = None
    section_buf: list[str] = []
    month_tail: list[str] = []

    def flush_section() -> None:
        nonlocal cur_section, section_buf
        if cur_section is not None:
            cur_section["body"] = "\n".join(section_buf).strip()
            cur_section = None
        section_buf = []

    def flush_month() -> None:
        nonlocal cur_month, month_tail
        if cur_month is None:
            return
        flush_section()
        text = "\n".join(month_tail).strip()
        cur_month["raw_tail"] = text
        months.append(cur_month)
        cur_month = None
        month_tail = []

    for line in raw.splitlines():
        m = MONTH_RE.match(line)
        if m:
            flush_month()
            cur_month = {"month": int(m.group(1)), "quarter": int(m.group(2)),
                         "year": int(m.group(3)), "turns": [], "notes": []}
            continue
        if cur_month is None:
            continue
        t = TURN_RE.match(line)
        if t:
            flush_section()
            cur_section = {"kind": "turn", "n": int(t.group(1)), "title": t.group(2),
                           "body": "", "options": [], "state": None, "choice": None,
                           "reason": None, "narrative": "", "raw": ""}
            cur_month["turns"].append(cur_section)
            section_buf = []
            continue
        s = SECTION_RE.match(line)
        if s:
            flush_section()
            cur_section = {"kind": "section", "title": s.group(1), "body": ""}
            cur_month["turns"].append(cur_section)
            section_buf = []
            continue
        if cur_section is not None:
            section_buf.append(line)
        else:
            month_tail.append(line)

    flush_month()

    # post-process sections
    for mo in months:
        for sec in mo["turns"]:
            if sec["kind"] != "turn":
                continue
            body = sec["body"] or ""
            sec["raw"] = body
            lines = body.splitlines()
            narr, opts, state, choice, reason = [], [], None, None, None
            in_opts = False
            for ln in lines:
                if OPT_HDR_RE.match(ln):
                    in_opts = True
                    continue
                om = OPT_RE.match(ln)
                if om and in_opts:
                    opts.append({"id": int(om.group(1)), "text": om.group(2)})
                    continue
                sm = STATE_RE.match(ln)
                if sm:
                    state = parse_state(sm.group(1))
                    in_opts = False
                    continue
                cm = CHOICE_RE.match(ln)
                if cm:
                    choice = cm.group(1)
                    in_opts = False
                    continue
                rm = REASON_RE.match(ln)
                if rm:
                    reason = rm.group(1)
                    in_opts = False
                    continue
                if not in_opts:
                    narr.append(ln)
            sec["narrative"] = "\n".join(narr).strip()
            if max_narrative and len(sec["narrative"]) > max_narrative:
                sec["narrative"] = sec["narrative"][:max_narrative].rstrip() + "…"
            sec["options"] = opts
            sec["state"] = state
            sec["choice"] = choice
            sec["reason"] = reason
            del sec["body"]

        # month-level markers from tail + section bodies
        tail = mo.get("raw_tail", "")
        for sec in mo["turns"]:
            if sec["kind"] == "section":
                tail += "\n" + sec.get("body", "")
        mo["pay"] = None
        pm = PAY_RE.search(tail)
        if pm:
            mo["pay"] = [float(pm.group(1)), pm.group(2)]
        bm = BONUS_RE.search(tail)
        mo["bonus"] = [bm.group(1), float(bm.group(2))] if bm else None
        prom = PROMO_RE.search(tail)
        mo["promotion"] = prom.group(1) if prom else None
        tm = TALK_RE.search(tail)
        if tm:
            # the quoted feedback line usually follows the header
            after = tail[tm.end():].strip().splitlines()
            quote = next((x.strip() for x in after if x.strip()), "")
            mo["talk"] = {"who": tm.group(1).strip(), "quote": quote[:400],
                          "tier": classify_talk(tail)}
        else:
            mo["talk"] = None
        hrm = HR_RE.search(tail)
        mo["hr"] = {"code": HR_LADDER.get(hrm.group(1), "L0"),
                    "text": hrm.group(2)} if hrm else None
        mo["burst"] = bool(BURST_RE.search(tail))
        mo["notes"] = [x.strip() for x in tail.splitlines() if x.strip()]
        mo.pop("raw_tail", None)

    return {"head": head, "months": months}


def load_score(run_dir: str) -> dict:
    p = os.path.join(run_dir, "score_report.json")
    if not os.path.exists(p):
        return {}
    r = json.load(open(p, encoding="utf-8"))
    es = r.get("ending_score", {})
    dims = {d["name"]: d for d in es.get("dimensions", [])}
    return {
        "grade": es.get("grade"),
        "grade_meaning": es.get("grade_meaning"),
        "score": es.get("quantitative_score"),
        "months": es.get("survival_months"),
        "outcome": es.get("outcome"),
        "partial": es.get("competition_partial_score"),
        "dims": dims,
        "maintenance": es.get("maintenance", {}),
        "tokens": (r.get("token_usage") or {}).get("total_tokens"),
        "termination": r.get("termination_reason"),
        "session": r.get("session_id"),
        "play_exit": r.get("play_exit_code"),
    }


def load_metrics(run_dir: str) -> dict | None:
    """Load the per-run analysis metrics JSON if it exists (v5 batch only)."""
    p = os.path.join(METRICS_DIR, run_dir + ".json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def parse_energy_rounds(log_path: str) -> dict:
    """Parse authoritative energy rounds from the engine's emulator log.

    replay-*.md can DROP energy rounds (observed: 091245Z M24 lost its 3rd
    round), so the engine log is the preferred source. Returns
    {month: [{"a": name, "cost": n, "rem": k}, ...]}.
    """
    rounds: dict = {}
    if not log_path or not os.path.exists(log_path):
        return rounds
    cur_month = None
    pend = None
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\[fixed_event\] Month (\d+) \| (季度体力行动分配|季度主行动选择)", line)
            if m:
                cur_month = int(m.group(1)) if m.group(2) == "季度体力行动分配" else None
                pend = None
                continue
            if cur_month is None:
                continue
            c = re.match(r"Chose #\d+: (.+?)\s*$", line)
            if c:
                pend = {"a": c.group(1)}
                continue
            e = re.match(r"Energy cost: (\d+)", line)
            if e and pend is not None:
                pend["cost"] = int(e.group(1))
                continue
            rr = re.match(r"Energy remaining: (\d+)", line)
            if rr and pend is not None and "cost" in pend:
                pend["rem"] = int(rr.group(1))
                rounds.setdefault(str(cur_month), []).append(pend)
                pend = None
    return rounds


BATCHES = [
    ("v1", "v1 · 5 铁律", ["20260924T161605Z", "20260924T165627Z",
                      "20260924T173408Z", "20260924T173802Z"]),
    ("v2", "v2 · 6 铁律 +health", ["20260924T190936Z", "20260924T192438Z",
                              "20260924T194245Z", "20260924T204559Z"]),
    ("v3", "v3 · 7 铁律 +体力用尽", ["20260924T232910Z", "20260924T235818Z",
                                "20260925T002312Z", "20260925T004806Z"]),
    ("v5", "v5 · 分阶段感知（诊断对象）", ["20260925T034626Z", "20260925T042320Z",
                                    "20260925T043821Z", "20260925T050758Z"]),
    ("v7", "v7 · M11生死线+暴露窗+爆雷门", ["20260925T061653Z", "20260925T065638Z",
                                    "20260925T074822Z"]),
    ("v8", "v8 · 读数触发风险闸（诊断对象）", ["20260925T091245Z", "20260925T093837Z",
                                       "20260925T101638Z", "20260925T104703Z"]),
    ("v8_1", "v8_1 · 语义否决+爆雷量级闸", ["20260925T111701Z", "20260925T115050Z",
                                        "20260925T122953Z", "20260925T130904Z"]),
    ("v8_2", "v8_2 · 铁律17 任期门+小缺口", ["20260925T134626Z", "20260925T142215Z",
                                        "20260925T145357Z", "20260925T151012Z"]),
    ("v8_3", "v8_3 · skill 跨级囤量（冒烟 A/A 73.7）", ["20260925T161142Z", "20260925T164951Z"]),
    ("v8_4", "v8_4 · 前3窗 skill 顶 CAP（回归，C/C 57.8）", ["20260925T180125Z", "20260925T183858Z"]),
    ("v8_5", "v8_5 · v8_3 策略 + 合规清理", [
        "20260925T192500Z", "20260925T195633Z", "20260925T201004Z", "20260925T205025Z",
        "20260925T222709Z", "20260925T223908Z", "20260925T232221Z"]),
    ("v9", "v9 · 财富守卫（诊断对象：双峰 · 两死两通关）", [
        "20260926T013834Z", "20260926T020204Z", "20260926T022719Z", "20260926T033856Z"]),
    ("v10", "v10 · 目标/红线二分 + 绩效判读", [
        "20260926T040643Z", "20260926T042811Z"]),
    ("v10b", "v10b · 前 3 窗节奏 + 最后一击三步裁决", [
        "20260926T051845Z", "20260926T054006Z", "20260926T064342Z", "20260926T071926Z"]),
    ("v10c", "v10c · 健康线修正（体力窗顶 health≥6）", [
        "20260926T081346Z", "20260926T125121Z", "20260926T131727Z", "20260926T150102Z"]),
    # ⚠️ 20260926T120028Z 曾有 score 74.29 A / L6，但事件流里**没有任何 observe/take_action**
    #   （工具调用只有 bash×108 / file×20 / grep×2）⇒ 不是对局，分数是从库里旧局算出来的。
    #   已把它 replay-*.md 移到 analysis/ab/_excluded_replays/（构建器靠"有没有 replay"收录）⇒ 不入包。
    #   同理，一批 70.51 A 的目录 token=0、events 只有 6KB（旧会话复用的空壳），也没有 replay ⇒ 自动不入包。
    ("v10d", "v10d · 截断转负门禁 + 分层边际值表 + L1 晋升优先", [
        "20260926T204818Z", "20260926T205235Z", "20260926T212040Z", "20260926T215108Z"]),
    # ⚠️ v10e 实际启动 4 局，**只有 2 局跑成**（ab_driver 记 `ARM v10e FINISHED (2/4 ok)`）：
    #   RUN1 `20260927T032531Z` = C / 53.02 / 48月 / completed
    #   RUN2 `20260927T042353Z` = D / 31.56 / 24月 / **`炒鱿鱼end`（死于绩效线）**
    #   ⇒ 这是第三条独立死亡线：L1 段 perf 天花板 3 < 出局线 4，停 L1 到 M18 必被裁；
    #     v10e 的「赌本分层」「长链整链风险预算」都只管健康线与风险线，**均未覆盖绩效线**。
    # 被排除的 4 个半成品目录（**故意不补 replay，构建器会自动跳过**）：
    #   `20260927T030715Z` exit=1 `max_continuations`（observe 59 / take_action 58，未到 48 月）
    #   `20260927T040300Z` 无 score_report.json（observe 100 / take_action 99）
    #   `20260927T044249Z` exit=1 `max_continuations`（observe 63 / take_action 62）
    #   `20260927T063944Z` 无 score_report.json（RUN3/RUN4 三次重试共用此目录，observe 144 / take_action 146）
    #   ⇒ 它们的 `ending_score` 为 None（or 无文件），收了会把"未完赛"混进分数对比。
    ("v10e", "v10e · 赌本分层 + 长链整链风险预算 + 否决后重跑（2/4 完成 · 一死一通关）", [
        "20260927T032531Z", "20260927T042353Z"]),
    # v3_rerun：横向分析后的复测臂 —— 技能 = 09-24 v3 的逐字还原副本（`analysis/_skillhist/v3/`，
    #   与 `analysis/ab/v3_rerun/` md5 一致），用于检验「缺口驱动」在当前引擎上的复现性。
    #   4/4 ok：A 73.12 / A 75.04 / D 30.8(24月 eliminated,信任危机,1爆雷) / A 75.88。
    #   ⚠️ v8_3_rerun 仍在跑（RUN2 起跑于 19:16），跑完后再单独收录其批次。
    ("v3_rerun", "v3_rerun · v3 复测（events 还原技能 · 3 通关 1 早死 · 均值 63.71）", [
        "20260927T085137Z", "20260927T091800Z", "20260927T093827Z", "20260927T095512Z"]),
    # v3_rerun2：09-29 扩样本批次（同一套技能、md5 逐字一致，n=4→8）。
    #   4/4 ok：E 28.88(M13 **`喝西北风end`** — 项目首例财富线死：L1 月薪 +0.3、
    #     半年绩效 C −0.3 ⇒ 净收入≈0，M7 起 wealth≤0 连 3 月) /
    #     C 59.12(M48 完赛 L5, M33 爆雷 output 20→14) /
    #     C 57.62(M45 **`信任危机end`** 二次爆雷) / A 71.53(M48 完赛 L5, 0 爆雷)。
    #   均值 54.29 vs 旧批 63.71（**−9.4**）⇒ 同技能批间漂移：旧批完赛 3 局**全 L6**（74.68）、
    #     新批完赛 3 局**全 L5**（62.76）——又一次印证「L6 是彩票、保底 ≥60 才是实力」。
    #   新批爆雷 2/4（旧批 1/4）⇒ 反向支持 v12 第 9 条长链整链预算（v12 4/4 零爆雷）。
    ("v3_rerun2", "v3_rerun2 · 09-29 扩样本（同技能 · 均值 54.29 · 完赛全 L5 · 爆雷 2/4）", [
        "20260928T223943Z", "20260928T224634Z", "20260928T231132Z", "20260928T233302Z"]),
    # v8_3_rerun：技能 = `analysis/ab/v8_3/`（09-26 快照，与 events 还原副本 md5 逐字一致）。
    #   4/4 ok **全部 48 月通关、零早死**：C 56.92 / C 59.42 / A 72.96 / C 50.28（1 爆雷）。
    #   均值 59.90 但 **sd 仅 9.5 —— 全项目最小方差臂**（对比 v3_rerun sd 22.0 / v10c 18.34 / v10d 23.42 / v10e 31.56）
    #   ⇒ 印证「分数方差几乎全来自是否早死」，v8_3 是"稳"的那一档、v3 是"上限高但有尾巴"的那一档。
    ("v8_3_rerun", "v8_3_rerun · v8_3 复测（4/4 通关 · 零早死 · 均值 59.90 / sd 9.5）", [
        "20260927T101708Z", "20260927T111641Z", "20260927T114829Z", "20260927T122216Z"]),
    # v11：v3 发展轴 + v8_3 风险轴的合成臂（19,520 字符 · 13 条保护性约束）。
    #   4/4 ok：E 22.38(M14 信任危机·二次爆雷) / E 22.18(M24 炒鱿鱼·卡 L1) /
    #           B 62.77(M48 完赛 L5) / E 19.23(M24 炒鱿鱼·卡 L1, network=2)。
    #   均值 31.6 ⇒ 失败确诊：保护性否决把 network 卡 2 → L1 永不毕业，风险轴压过发展轴（重蹈 v10d）。
    ("v11", "v11 · v3 发展轴+v8_3 风险轴合成（13 约束 · 风险轴压过发展轴 · 均值 31.6）", [
        "20260928T100916Z", "20260928T102548Z", "20260928T104248Z", "20260928T111337Z"]),
    # v12：v3_rerun 全文原封不动 + 仅在 risk-guardian 加 1 条「长链整链风险预算」（单点可回滚）。
    #   4/4 ok：E 24.15(M24 炒鱿鱼·卡 L1,N=0) / E 21.52(M3 眼前一黑·开局健康失血) /
    #           A 71.67(M48 完赛 L5) / C 59.17(M48 完赛 L4, 差 0.83 够 60 线)。
    #   **零爆雷 4/4** ⇒ 第 9 条防爆雷在 4 局全样本成立；但 2/4 早死于非爆雷因（L1 卡死/开局血线），
    #   P(max3≥60)=57.8%、E[max3]=61.98 ⇒ 终审判负，定稿 v3_rerun。
    #   若续做 v13：开局血线保护 + L1 卡死监控（均不在爆雷族，与第 9 条正交）。
    ("v12", "v12 · v3_rerun+第9条长链整链预算（零爆雷 4/4 · 2 早死 · P(max3≥60)=57.8%）", [
        "20260928T113941Z", "20260928T115042Z", "20260928T123048Z", "20260928T132134Z"]),
    # v13：破壁臂（09-29）—— SA 逐字未改 / RG +第9条(长链整链预算)+第10条(L1 财富线代理)
    #   / DP +§七 逆风局破壁协议（铁律 1 的 L1 段豁免 + 主行动表 L1 强制「申请关键项目」）。
    #   设计依据 `analysis/promo_barrier_audit.py`：16 局 / 91 窗统计出的晋升屏障
    #     —— L1→L2 仅 41%、L2→L3 71%、L3→L4 64%，失败几乎全卡「差 1–3 点 output」。
    #   首局 20260929T004231Z = A 76.28 / 48 月 / **L6** / 0 爆雷（attempt1 收尾 WS 崩，
    #     经 `salvage_score.py` 抢救）⇒ **刷新全项目单局最高**（超 v3_rerun 75.88）。
    #     ★ 破壁证据：连过 L1→L2、L2→L3（M5 / M11 两个评审窗），对照历史 L1→L2 仅 41%。
    #   ⚠️ 第 2 局收官后补 dir 并重算 P(max3≥60)/E[max3]。
    ("v13", "v13 · 破壁臂（L1 配比豁免+强制申请关键项目+长链预算 · 2/2 跑满 48 月 · L6/L5）", [
        "20260929T004231Z", "20260929T021657Z"]),
    # v14：v13 + 四项修正（全局爆雷三级状态机 / L1 倒计时配额 / 硬裁定爆雷分支 / 引用修正）。
    #   4/4 ok：B 64.38(L5,0爆雷) / D 30.88(**M8 喝西北风end**·财富线——晋升 L2 后仍死，修正 B 副作用：
    #     体力全押 output/network 无财富缓冲) / B 68.97(L6,1爆雷) / B 66.09(L5,0爆雷)。
    #   ⇒ ★ L1 首窗通过 3/4=75%（全局 42%，配额表生效，M5 评审瞬间全部 9/3/3 顶 CAP）；
    #     ★ 零二次爆雷（状态机生效，爆雷 1/4 且无一致死）；但 0 局上 71（唯一 L6 局带 1 爆雷 −5 分）。
    ("v14", "v14 · 爆雷状态机+L1配额（B/D/B/B · L1首窗75% · 零二次爆雷 · 1 财富线早死）", [
        "20260929T051757Z", "20260929T062953Z", "20260929T063708Z", "20260929T070350Z"]),
    # ⚠️ `20260924T153540Z`（E / 20.43 / 6 月 eliminated）**故意不收录**：它与
    #   `20260924T153238Z`（B / 61.36 / 48 月 completed）**共用同一个 `session_id` `20bd449ed2c8…`**
    #   ⇒ 它是该会话 6 月早退时的**中间快照**（15:38 打分，events 仅 288KB），随后被 48 月完赛的正式局
    #   （15:57 打分，events 1812KB）取代。收了会**同一次会话重复计数**（v1 批次均值会被拉低）。
    #   ★ 甄别方法：比对 `score_report.json` 的 `session_id`；同一 session 只保留**月份最长**的那条。
    #     一键检查：`.venv/bin/python3 analysis/scan_real_runs.py`
]
HISTORIC = ["20260924T144338Z", "20260924T153238Z",
            "20260925T015009Z", "20260925T022235Z"]


def build(out_path: str, max_narrative: int) -> int:
    if not os.path.isdir(OUTROOT):
        print(f"outputs dir missing: {OUTROOT}", file=sys.stderr)
        return 1
    runs = []
    for name in sorted(os.listdir(OUTROOT)):
        d = os.path.join(OUTROOT, name)
        if not os.path.isdir(d):
            continue
        reps = [f for f in os.listdir(d) if f.startswith("replay-") and f.endswith(".md")]
        if not reps:
            continue
        sc = load_score(d)
        if not sc or sc.get("score") is None:
            continue
        rep = parse_replay(os.path.join(d, reps[0]), max_narrative)
        m = load_metrics(name)
        elog = os.path.join(EMULATOR_LOG_DIR, f"{(sc.get('session') or '')}.log")
        runs.append({"dir": name, "score": sc, "replay": rep, "metrics": m,
                     "energy": parse_energy_rounds(elog)})

    order = {}
    for tag, label, dirs in BATCHES:
        for i, dn in enumerate(dirs):
            order[dn] = (0, tag, label, i)
    for i, dn in enumerate(HISTORIC):
        order[dn] = (1, "hist", "历史局（探索前）", i)
    runs.sort(key=lambda r: (order.get(r["dir"], (2, "?", "?", 0)), r["dir"]))

    data = {"runs": runs, "batches": [{"tag": t, "label": l, "dirs": d} for t, l, d in BATCHES]}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    html = TEMPLATE.replace("__DATA__", payload)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {out_path}")
    print(f"runs={len(runs)} size={os.path.getsize(out_path)/1024/1024:.2f} MB")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>九问 · CareerSim 对局回放浏览器</title>
<style>
:root{
  --bg:#f5f6f8; --panel:#ffffff; --panel2:#fbfcfd; --line:#e2e6ea;
  --ink:#1f2328; --ink2:#4b5563; --muted:#8b949e;
  --a:#7c3aed; --b:#0ea5e9; --c:#f59e0b; --d:#f97316; --e:#ef4444;
  --health:#ef4444; --dignity:#a855f7; --skill:#2563eb; --network:#16a34a;
  --output:#f59e0b; --wealth:#0d9488; --energy:#94a3b8;
  --promo:#7c3aed; --burst:#ef4444;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);
  font:14px/1.65 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
a{color:var(--skill);text-decoration:none}
h1,h2,h3,h4{margin:0;font-weight:600}
.wrap{display:flex;min-height:100vh;align-items:flex-start}
/* ---------- sidebar ---------- */
.side{width:286px;flex:0 0 286px;background:var(--panel);border-right:1px solid var(--line);
  position:sticky;top:0;height:100vh;overflow-y:auto;padding:14px 12px 40px}
.side h1{font-size:15px;letter-spacing:.3px}
.side .sub{font-size:11.5px;color:var(--muted);margin:2px 0 12px}
.grp{font-size:11px;color:var(--muted);text-transform:none;margin:14px 0 6px;padding-left:4px;
  letter-spacing:.5px}
.item{display:flex;gap:8px;align-items:center;padding:7px 8px;border-radius:7px;cursor:pointer;
  border:1px solid transparent}
.item:hover{background:var(--panel2);border-color:var(--line)}
.item.on{background:#eef4ff;border-color:#c7dbff}
.badge{flex:0 0 20px;height:20px;border-radius:5px;color:#fff;font-size:11px;font-weight:700;
  display:flex;align-items:center;justify-content:center}
.g-A{background:var(--a)}.g-B{background:var(--b)}.g-C{background:var(--c)}
.g-D{background:var(--d)}.g-E{background:var(--e)}
.item .nm{font-size:12.5px;font-family:ui-monospace,Menlo,monospace;color:var(--ink2)}
.item .sc{margin-left:auto;font-size:12px;font-variant-numeric:tabular-nums;color:var(--ink2)}
.tabs{display:flex;gap:6px;margin:10px 0 2px}
.tab{flex:1;text-align:center;padding:6px 0;font-size:12px;border:1px solid var(--line);
  border-radius:7px;background:var(--panel2);cursor:pointer;color:var(--ink2)}
.tab.on{background:var(--ink);color:#fff;border-color:var(--ink)}
/* ---------- main ---------- */
.main{flex:1;min-width:0;padding:18px 22px 80px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
  margin-bottom:14px}
.row{display:flex;gap:14px;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:8px}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kpi .k{font-size:11px;color:var(--muted)}
.kpi .v{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.dims{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px 16px}
.dim{font-size:12px}
.dim .bar{height:6px;border-radius:3px;background:#eceff3;overflow:hidden;margin-top:3px}
.dim .bar i{display:block;height:100%;background:var(--skill)}
.legend{display:flex;gap:10px;flex-wrap:wrap;font-size:11.5px;color:var(--ink2);margin:2px 0 8px}
.legend label{display:flex;gap:4px;align-items:center;cursor:pointer;user-select:none}
.legend label.off{opacity:.35}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend input{margin:0}
svg{display:block;width:100%;height:auto}
/* ---------- timeline ---------- */
.mo{border:1px solid var(--line);border-radius:9px;margin-bottom:8px;background:var(--panel);
  overflow:hidden}
.mo>.hdr{display:flex;gap:8px;align-items:center;padding:8px 12px;cursor:pointer;
  background:var(--panel2)}
.mo>.hdr:hover{background:#f3f6fa}
.mo .mno{font-weight:600;font-size:13px;min-width:76px}
.mo .cn{font-size:11.5px;color:var(--muted);min-width:88px}
.chip{font-size:10.5px;padding:1.5px 6px;border-radius:99px;border:1px solid var(--line);
  background:#fff;color:var(--ink2);white-space:nowrap}
.chip.promo{background:#f3ecff;border-color:#d9c7ff;color:#6d28d9}
.chip.burst{background:#fdecec;border-color:#f8c9c9;color:#b91c1c}
.chip.good{background:#eafaf0;border-color:#bfe8cd;color:#15803d}
.chip.average{background:#fff7e6;border-color:#f6e0a8;color:#a16207}
.chip.bad{background:#fdecec;border-color:#f8c9c9;color:#b91c1c}
.chip.hr0{background:#eafaf0;border-color:#bfe8cd;color:#15803d}
.chip.hr1{background:#f4f8e8;border-color:#dbe8b8;color:#4d7c0f}
.chip.hr2{background:#fff7e6;border-color:#f6e0a8;color:#a16207}
.chip.hr4{background:#fff0e6;border-color:#f8cfae;color:#c2410c}
.chip.hr5{background:#fdecec;border-color:#f8c9c9;color:#b91c1c}
.mo .body{display:none;padding:6px 14px 14px;border-top:1px solid var(--line)}
.mo.open .body{display:block}
.turn{padding:9px 0;border-bottom:1px dashed #eaeef2}
.turn:last-child{border-bottom:none}
.turn .tt{font-size:13px;font-weight:600;margin-bottom:3px}
.turn .tt .n{color:var(--muted);font-weight:400;font-family:ui-monospace,Menlo,monospace;
  font-size:11.5px;margin-right:6px}
.turn .nar{color:var(--ink2);white-space:pre-wrap;font-size:12.5px}
.opts{margin:6px 0 4px;padding:0;list-style:none}
.opts li{font-size:12px;color:var(--ink2);padding:2px 7px;border-radius:5px;margin-bottom:2px}
.opts li.sel{background:#eef4ff;color:#1d4ed8;font-weight:600}
.foot{display:flex;gap:12px;flex-wrap:wrap;font-size:11.5px;color:var(--ink2);margin-top:5px}
.foot .st{font-family:ui-monospace,Menlo,monospace;font-size:11px}
.foot .rs{flex:1 1 100%;color:#6d28d9}
.note{font-size:12px;color:var(--ink2);background:var(--panel2);border-left:3px solid #d7dde4;
  padding:5px 9px;border-radius:0 6px 6px 0;margin:5px 0;white-space:pre-wrap}
.note.w{border-left-color:var(--c)}
.note.d{border-left-color:var(--e)}
.note.p{border-left-color:var(--promo)}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:right;
  font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left;font-family:ui-monospace,Menlo,monospace}
th{color:var(--muted);font-weight:600;background:var(--panel2)}
tr.hl td{background:#f6f0ff}
.hint{font-size:11.5px;color:var(--muted);margin-top:6px}
.hidden{display:none}
.tiny{font-size:11px;color:var(--muted)}
/* ---------- action deltas ---------- */
.up{color:#2563eb;font-weight:700}
.dn{color:#ef4444;font-weight:700}
.dz{display:inline-flex;gap:4px;margin-left:6px;white-space:nowrap}
.dz b{font-size:10.5px;font-weight:700;font-family:ui-monospace,Menlo,monospace}
.qsum{display:flex;gap:14px;flex-wrap:wrap;align-items:baseline;font-size:11.5px;
  padding:6px 10px;background:var(--panel2);border:1px solid var(--line);
  border-radius:7px;margin:2px 0 8px}
.qsum .qm{color:#6d28d9;font-weight:600}
.qsum .qe{color:var(--ink2)}
/* big-action turn highlight */
.turn.hi-main{background:#faf7ff;border-radius:7px;box-shadow:inset 3px 0 0 var(--promo);
  padding-left:10px;padding-right:8px}
.turn.hi-energy{background:#f2f8fd;border-radius:7px;box-shadow:inset 3px 0 0 var(--b);
  padding-left:10px;padding-right:8px}
.chip.act{background:#e8f4fd;border-color:#bde0f7;color:#0369a1}
.chip.en{background:#f2f8fd;border-color:#c8ddf0;color:#475569}
/* energy discipline strip */
.edisc{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 2px}
.edisc .q{font-size:11px;padding:2px 7px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel2);font-family:ui-monospace,Menlo,monospace;cursor:default}
.edisc .q.full{background:#eafaf0;border-color:#bfe8cd;color:#15803d}
.edisc .q.part{background:#fff7e6;border-color:#f6e0a8;color:#a16207}
.edisc .q.zero{background:#fdecec;border-color:#f8c9c9;color:#b91c1c}
.edisc .q.dead{background:#f3f4f6;border-color:#e2e6ea;color:#8b949e}
.chip.eq-full{background:#eafaf0;border-color:#bfe8cd;color:#15803d}
.chip.eq-part{background:#fff7e6;border-color:#f6e0a8;color:#a16207}
.chip.eq-zero{background:#fdecec;border-color:#f8c9c9;color:#b91c1c}
</style>
</head>
<body>
<div class="wrap">
  <aside class="side">
    <h1>九问 · 对局回放</h1>
    <div class="sub" id="sub">CareerSim-BDCI26 探索批次</div>
    <div class="tabs">
      <div class="tab on" data-v="runs">对局</div>
      <div class="tab" data-v="cmp">批次对比</div>
    </div>
    <div id="list"></div>
  </aside>
  <main class="main">
    <div id="view"></div>
  </main>
</div>
<script>
const DATA = __DATA__;
const RUNS = DATA.runs;
const $ = s => document.querySelector(s);
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let cur = 0, mode = 'runs';

const SERIES = [
  {k:'health', c:'var(--health)', l:'health 健康'},
  {k:'dignity', c:'var(--dignity)', l:'dignity 尊严'},
  {k:'skill', c:'var(--skill)', l:'skill 技能'},
  {k:'network', c:'var(--network)', l:'network 人脉'},
  {k:'output', c:'var(--output)', l:'output 成果'},
  {k:'wealth', c:'var(--wealth)', l:'wealth 财富'},
  {k:'energy', c:'var(--energy)', l:'energy 体力'}
];
const off = {energy:true};

/* ---------- 8 大动作 · 参数影响（引擎实测单次效果，未计职级截断） ---------- */
const AK={skill:'S',output:'O',network:'N',dignity:'D',health:'H',hidden_risk:'R',wealth:'W'};
const MAIN_ACTIONS=[
  {n:'申请关键项目',d:{output:2,skill:1,network:1}},
  {n:'申请岗位轮岗',d:{skill:2,network:1}},
  {n:'建立导师关系',d:{skill:1,network:2}},
  {n:'向领导汇报成果',d:{output:1,network:1,dignity:1}},
  {n:'主动争取资源',d:{output:1,network:1}},
  {n:'主动曝光成果',d:{output:1,dignity:1}},
  {n:'修复关键关系',d:{network:1,dignity:1}},
  {n:'低调避险',d:{health:1,hidden_risk:-1}},
  {n:'不行动',d:{}}
];
const ENERGY_ACTIONS=[
  {n:'人脉维护',c:1,d:{network:1,dignity:1}},
  {n:'准备汇报材料',c:1,d:{output:1,dignity:1}},
  {n:'健康恢复',c:1,d:{health:2}},
  {n:'心理修复',c:1,d:{dignity:2}},
  {n:'处理历史埋雷',c:2,d:{hidden_risk:-1}},
  {n:'高强度工作',c:2,d:{output:2,health:-1,dignity:-1,hidden_risk:1}},
  {n:'技能学习',c:2,d:{skill:1,health:-1}},
  {n:'保留体力',c:0,d:{}}
];
const ACTION_DB={};
MAIN_ACTIONS.forEach(a=>ACTION_DB[a.n]=a);
ENERGY_ACTIONS.forEach(a=>ACTION_DB[a.n]=a);
const DZ_KEYS=['skill','output','network','dignity','health','hidden_risk'];
function actionOf(text){
  const nm=String(text).replace(/^\[\d+\]\s*/,'').split(' — ')[0]
    .replace('（不行动）','').trim();
  return {nm, a:ACTION_DB[nm]||null};
}
function dzHtml(d){
  const out=[];
  DZ_KEYS.forEach(k=>{
    const v=d[k]; if(!v) return;
    out.push(`<b class="${v>0?'up':'dn'}">${v>0?'↑':'↓'}${AK[k]}${v>0?'+':'-'}${Math.abs(v)}</b>`);
  });
  return out.length?`<span class="dz">${out.join('')}</span>`:'';
}
function optDz(text){ const x=actionOf(text); return x.a?dzHtml(x.a.d):''; }

/* ---------- 实际状态差分（回合选择 → 下一回合状态变化） ---------- */
const DLT_KEYS=['skill','output','network','dignity','health','wealth'];
function deltaArrows(d){
  const out=[];
  DLT_KEYS.forEach(k=>{
    const v=d[k]; if(!v) return;
    out.push(`<b class="${v>0?'up':'dn'}">${v>0?'↑':'↓'}${AK[k]}${v>0?'+':'-'}${Math.abs(v)}</b>`);
  });
  return out.join('');
}
function attachDeltas(r){
  const flat=[];
  r.replay.months.forEach(mo=>mo.turns.forEach(t=>{
    if(t.kind==='turn'&&t.state) flat.push(t);
  }));
  flat.forEach((t,i)=>{
    t.delta={};
    const nx=flat[i+1];
    if(!nx) return;
    DLT_KEYS.forEach(k=>{
      const a=t.state[k], b=nx.state[k];
      if(typeof a==='number'&&typeof b==='number'&&b!==a) t.delta[k]=b-a;
    });
  });
}

/* ---------- 季度体力纪律（每季 3 点，不跨季累计） ---------- */
let EQ=null, ESRC='';
function energyByQuarter(r){
  const byQ={};
  const add=(month,a,cost)=>{
    const q=Math.floor((month-1)/3)+1;
    const e=byQ[q]||(byQ[q]={q,month,items:[],used:0});
    e.items.push(a); e.used+=cost;
  };
  if(r.energy&&Object.keys(r.energy).length){
    ESRC='引擎日志';
    Object.keys(r.energy).forEach(mo=>r.energy[mo].forEach(x=>add(+mo,x.a,x.cost)));
  } else {
    ESRC='replay（可能缺轮）';
    r.replay.months.forEach(mo=>mo.turns.forEach(t=>{
      if(t.kind!=='turn'||!(t.title||'').includes('体力')||!t.choice) return;
      const x=actionOf(t.choice);
      add(mo.month,x.nm,(x.a&&x.a.c!=null)?x.a.c:0);
    }));
  }
  return byQ;
}
function energyStrip(r){
  EQ=energyByQuarter(r);
  const alive=r.score.months||48;
  let lastQ=0;
  Object.keys(EQ).forEach(k=>{ lastQ=Math.max(lastQ,+k); });
  let used=0,nominal=0,full=0,withData=0,cells='';
  for(let q=1;q<=16;q++){
    const e=EQ[q];
    if(e){
      withData++; used+=e.used; nominal+=3;
      if(e.used>=3) full++;
      const cls=e.used>=3?'full':(e.used>0?'part':'zero');
      cells+=`<span class="q ${cls}" title="M${e.month}：${esc(e.items.join(' + '))}">Q${q} ${e.used}/3 ${esc(e.items.join('+'))}</span>`;
    } else if(q<=lastQ){
      nominal+=3;
      cells+=`<span class="q zero" title="该季体力窗口已过但未执行任何体力行动">Q${q} 0/3 未执行!</span>`;
    } else {
      cells+=`<span class="q dead" title="对局在该季体力窗口前结束">Q${q} —（卒）</span>`;
    }
  }
  const pct=nominal?Math.round(used/nominal*100):0;
  return `<div class="edisc">${cells}</div>
    <div class="hint">体力纪律（每季 3 点、不跨季累计；数据源=${ESRC}）：实际消耗 <b>${used}/${nominal} 点（${pct}%）</b> ·
    完全用满 <b>${full}/${withData}</b> 季 · <span style="color:#15803d">■绿=满 3 点</span>
    <span style="color:#a16207">■黄=有剩余</span> <span style="color:#b91c1c">■红=窗口已过未执行</span>
    <span style="color:#8b949e">■灰=该季前已出局</span>。悬停格子看明细。</div>`;
}

function quarterSummary(mo){
  const turns=mo.turns.filter(t=>t.kind==='turn');
  let main=null; const en=[];
  turns.forEach(t=>{
    if(!t.choice) return;
    if((t.title||'').includes('主行动')){
      const x=actionOf(t.choice); main=x;
    } else if((t.title||'').includes('体力')){
      en.push(actionOf(t.choice));
    }
  });
  if(!main&&!en.length) return '';
  let h='<div class="qsum">';
  if(main) h+=`<span class="qm">主行动：${esc(main.nm)}${main.a?dzHtml(main.a.d):''}</span>`;
  if(en.length){
    const cnt={}; en.forEach(x=>{ const k=x.nm; cnt[k]=cnt[k]||{n:0,a:x.a}; cnt[k].n++; });
    h+='<span class="qe">体力：'+Object.keys(cnt).map(k=>{
      const e=cnt[k];
      return esc(k)+(e.n>1?'×'+e.n:'')+(e.a?dzHtml(e.a.d):'');
    }).join(' · ')+'</span>';
  }
  return h+'</div>';
}

function actionTables(){
  const cols=DZ_KEYS;
  const th=cols.map(k=>`<th title="${k}">${AK[k]}</th>`).join('');
  const rows=lst=>lst.map(a=>{
    const cells=cols.map(k=>{
      const v=a.d[k];
      return `<td>${v?`<span class="${v>0?'up':'dn'}">${v>0?'↑+':'↓-'}${Math.abs(v)}</span>`:'·'}</td>`;
    }).join('');
    return `<tr><td>${esc(a.n)}</td><td>${a.c!=null?a.c:'0'}</td>${cells}</tr>`;
  }).join('');
  return `<div class="card"><h3 style="font-size:14px;margin-bottom:4px">8 大动作 · 参数影响</h3>
    <div class="hint" style="margin-bottom:8px"><span class="up">↑ 蓝色 = 提升</span> ·
      <span class="dn">↓ 红色 = 消耗</span>；S=skill 技能 / O=output 成果 / N=network 人脉 /
      D=dignity 尊严 / H=health 健康 / R=hidden_risk 埋雷。
      数值为引擎单次结算量，<b>未计职级截断</b>（已达上限的维度增益会被引擎丢弃）。</div>
    <div style="display:flex;gap:18px;flex-wrap:wrap">
      <div style="flex:1 1 430px">
        <div class="tiny" style="margin-bottom:3px;font-weight:600">季度主行动（0 体力 · 每季 1 次，共 16 次）</div>
        <table><thead><tr><th>行动</th><th>体力</th>${th}</tr></thead>
        <tbody>${rows(MAIN_ACTIONS)}</tbody></table></div>
      <div style="flex:1 1 430px">
        <div class="tiny" style="margin-bottom:3px;font-weight:600">体力行动（每季 3 点 · 体力不跨季累计）</div>
        <table><thead><tr><th>行动</th><th>体力</th>${th}</tr></thead>
        <tbody>${rows(ENERGY_ACTIONS)}</tbody></table></div>
    </div></div>`;
}

function runSeries(r){
  const xs=[], ys={};
  SERIES.forEach(s=>ys[s.k]=[]);
  const pts=[];
  r.replay.months.forEach(mo=>mo.turns.forEach(t=>{
    if(t.kind!=='turn'||!t.state) return;
    pts.push({month:mo.month, n:t.n, s:t.state});
  }));
  pts.forEach((p,i)=>{ xs.push(p); SERIES.forEach(s=>{
    const v=p.s[s.k]; ys[s.k].push(typeof v==='number'?v:null); }); });
  return {xs, ys};
}

function chart(r){
  const {xs, ys} = runSeries(r);
  const W=980, H=250, PL=38, PR=12, PT=12, PB=24;
  const active = SERIES.filter(s=>!off[s.k]);
  let max=1; active.forEach(s=>ys[s.k].forEach(v=>{ if(v!=null&&v>max) max=v; }));
  max = Math.ceil(max/10)*10 || 10;
  const n=xs.length||1;
  const X=i=>PL+(W-PL-PR)*(n===1?0:i/(n-1));
  const Y=v=>H-PB-(H-PT-PB)*(v/max);
  let g='';
  for(let t=0;t<=4;t++){
    const v=max*t/4, y=Y(v);
    g+=`<line x1="${PL}" y1="${y}" x2="${W-PR}" y2="${y}" stroke="#e8ecf0" stroke-width="1"/>`;
    g+=`<text x="${PL-6}" y="${y+3.5}" text-anchor="end" font-size="9.5" fill="#8b949e">${v}</text>`;
  }
  const promoXs = r.replay.months.filter(m=>m.promotion).map(m=>{
    const idx = xs.findIndex(p=>p.month===m.month); return idx;
  }).filter(i=>i>=0);
  promoXs.forEach(i=>{ g+=`<line x1="${X(i)}" y1="${PT}" x2="${X(i)}" y2="${H-PB}" stroke="#c7b0ff" stroke-width="1" stroke-dasharray="3 3"/>`; });
  const burstXs = r.replay.months.filter(m=>m.burst).map(m=>xs.findIndex(p=>p.month===m.month)).filter(i=>i>=0);
  burstXs.forEach(i=>{ g+=`<line x1="${X(i)}" y1="${PT}" x2="${X(i)}" y2="${H-PB}" stroke="#f3b4b4" stroke-width="1.4"/>`; });
  active.forEach(s=>{
    let d='', open=false;
    ys[s.k].forEach((v,i)=>{ if(v==null) return; d += (open?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' '; open=true; });
    g+=`<path d="${d}" fill="none" stroke="${s.c}" stroke-width="1.7" stroke-linejoin="round"/>`;
  });
  // month ticks every 6 months
  for(let mo=6; mo<=48; mo+=6){
    const i = xs.findIndex(p=>p.month===mo);
    if(i>=0) g+=`<text x="${X(i)}" y="${H-6}" text-anchor="middle" font-size="9.5" fill="#8b949e">M${mo}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}</svg>`;
}

function dims(r){
  const d = r.score.dims||{};
  const order=['level','wealth','resilience','skill','risk_control','network'];
  return order.filter(k=>d[k]).map(k=>{
    const x=d[k];
    return `<div class="dim"><div>${esc(x.label)} <b style="float:right">${x.weighted_score.toFixed(2)}</b>
      <span class="tiny">/${(x.weight*100)|0} 分</span></div>
      <div class="bar"><i style="width:${Math.min(100,x.normalized_score)}%"></i></div>
      <div class="tiny">原始值 ${x.raw_value} → 归一 ${x.normalized_score.toFixed(1)}</div></div>`;
  }).join('');
}

function monthBadges(mo){
  let h='';
  const mt=mo.turns.find(t=>t.kind==='turn'&&(t.title||'').includes('主行动')&&t.choice);
  if(mt) h+=`<span class="chip act">主 ${esc(actionOf(mt.choice).nm)}</span>`;
  if(mo.promotion) h+=`<span class="chip promo">晋升</span>`;
  if(mo.talk) h+=`<span class="chip ${esc(mo.talk.tier||'')}">谈话 ${mo.talk.tier||'?'}</span>`;
  if(mo.bonus) h+=`<span class="chip">奖金 ${mo.bonus[0]} ${mo.bonus[1]>0?'+':''}${mo.bonus[1]}</span>`;
  if(mo.hr) h+=`<span class="chip hr${mo.hr.code.replace('L','')}">${esc(mo.hr.code)}</span>`;
  if(mo.burst) h+=`<span class="chip burst">爆雷</span>`;
  const eq=EQ&&EQ[Math.floor((mo.month-1)/3)+1];
  if(eq&&eq.month===mo.month){
    const cls=eq.used>=3?'eq-full':(eq.used>0?'eq-part':'eq-zero');
    h+=`<span class="chip ${cls}">体力 ${eq.used}/3</span>`;
  }
  return h;
}

function monthBody(mo){
  let h=quarterSummary(mo);
  mo.turns.forEach(t=>{
    if(t.kind==='section'){
      h+=`<div class="note">${esc(t.title)}\n${esc((t.body||'').trim())}</div>`;
      return;
    }
    const isMain=(t.title||'').includes('主行动');
    const isEnergy=!isMain&&(t.title||'').includes('体力');
    const hiCls=isMain?'hi-main':(isEnergy?'hi-energy':'');
    const hiChip=isMain?'<span class="chip act">主行动</span>'
      :(isEnergy?'<span class="chip en">体力分配</span>':'');
    h+=`<div class="turn ${hiCls}"><div class="tt"><span class="n">#${t.n}</span>${esc(t.title)} ${hiChip}</div>`;
    if(t.narrative) h+=`<div class="nar">${esc(t.narrative)}</div>`;
    if(t.options&&t.options.length){
      h+='<ul class="opts">'+t.options.map(o=>{
        const sel = t.choice && t.choice.includes('['+o.id+']');
        return `<li class="${sel?'sel':''}">[${o.id}] ${esc(o.text)}${optDz(o.text)}</li>`;
      }).join('')+'</ul>';
    }
    let f='';
    if(t.state){
      f+=`<span class="st">${esc(['level','health','dignity','skill','network','output','wealth','energy']
        .filter(k=>t.state[k]!=null).map(k=>k+'='+t.state[k]).join(' '))}</span>`;
    }
    if(t.delta&&Object.keys(t.delta).length){
      f+=`<span class="dz">${deltaArrows(t.delta)}</span>`;
    }
    if(t.reason) f+=`<span class="rs">理由：${esc(t.reason)}</span>`;
    if(f) h+=`<div class="foot">${f}</div>`;
    h+='</div>';
  });
  const extra = mo.notes.filter(x=>!/^本月基本工资|^闲聊的时候|^【半年谈话】|^半年绩效奖金|^晋升通知/.test(x));
  if(extra.length) h+=`<div class="note">${esc(extra.join('\n'))}</div>`;
  if(mo.promotion) h+=`<div class="note p">晋升通知：${esc(mo.promotion)}</div>`;
  if(mo.talk) h+=`<div class="note">【半年谈话】${esc(mo.talk.quote)}</div>`;
  if(mo.bonus) h+=`<div class="note w">半年绩效奖金（${mo.bonus[0]}）：${mo.bonus[1]>0?'+':''}${mo.bonus[1]}</div>`;
  return h;
}

function renderRun(){
  const r = RUNS[cur], sc = r.score;
  const months = r.replay.months;
  const alive = months.length;
  attachDeltas(r);
  let h = '';
  h += `<div class="card"><div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
    <span class="badge g-${esc(sc.grade)}" style="width:26px;height:26px;font-size:14px">${esc(sc.grade)}</span>
    <h2 style="font-size:17px">${esc(r.dir)}</h2>
    <span class="tiny">session ${esc((sc.session||'').slice(0,12))}</span>
    <span class="tiny">play_exit=${sc.play_exit} termination=${esc(sc.termination)}</span>
  </div>
  <div class="tiny" style="margin:4px 0 10px">${esc(sc.grade_meaning||'')}</div>
  <div class="kpis">
    <div class="kpi"><div class="k">量化分</div><div class="v">${esc(sc.score)}</div></div>
    <div class="kpi"><div class="k">存活月数</div><div class="v">${esc(sc.months)}</div></div>
    <div class="kpi"><div class="k">大赛分×0.7</div><div class="v">${sc.partial!=null?esc(sc.partial):'—'}</div></div>
    <div class="kpi"><div class="k">终局职级</div><div class="v">${esc((sc.dims.level||{}).raw_value??'—')}</div></div>
    <div class="kpi"><div class="k">爆雷</div><div class="v">${months.filter(m=>m.burst).length}</div></div>
    <div class="kpi"><div class="k">晋升次数</div><div class="v">${months.filter(m=>m.promotion).length}</div></div>
  </div>
  <div class="dims" style="margin-top:12px">${dims(r)}</div></div>`;

  h += metricsCard(r);
  h += `<div class="card"><h3 style="font-size:14px;margin-bottom:6px">状态曲线</h3>
    <div class="legend">${SERIES.map(s=>`<label class="${off[s.k]?'off':''}" data-k="${s.k}">
      <input type="checkbox" data-k="${s.k}" ${off[s.k]?'':'checked'}>
      <span class="dot" style="background:${s.c}"></span>${s.l}</label>`).join('')}
      <span class="tiny">虚线=晋升月 &nbsp; 红竖线=爆雷月</span></div>
    <div id="chart">${chart(r)}</div>
    <div class="hint">横轴按决策回合顺序（非线性月份刻度），纵轴按当前可见曲线的最大值自适应。</div></div>`;

  h += actionTables();

  h += `<div class="card"><div style="display:flex;gap:10px;align-items:center;margin-bottom:8px">
    <h3 style="font-size:14px">逐月过程（共 ${alive} 月）</h3>
    <button id="expall" style="font-size:11.5px;padding:3px 9px;border:1px solid var(--line);
      background:var(--panel2);border-radius:6px;cursor:pointer">全部展开</button>
    <button id="colall" style="font-size:11.5px;padding:3px 9px;border:1px solid var(--line);
      background:var(--panel2);border-radius:6px;cursor:pointer">全部收起</button>
    <span class="tiny">点击月份行展开回合明细 · <b>紫边=季度主行动</b> · <b>蓝边=体力分配</b> · 状态行后的 ↑/↓ 箭头为该回合选择导致的实际状态变化（与下一回合状态的差分，含剧情事件效果；W=财富）</span></div>
    ${energyStrip(r)}
    <div id="months">${months.map((mo,i)=>`
      <div class="mo" data-i="${i}">
        <div class="hdr"><span class="mno">第 ${mo.month} 月</span>
          <span class="cn">Q${mo.quarter} · Y${mo.year}</span>
          ${monthBadges(mo)}
          <span class="tiny" style="margin-left:auto">${mo.turns.filter(t=>t.kind==='turn').length} 回合</span>
        </div>
        <div class="body">${monthBody(mo)}</div>
      </div>`).join('')}</div></div>`;

  $('#view').innerHTML = h;
  bindRun();
}

function metricsCard(r){
  const m = r.metrics;
  if(!m) return '';
  let h = '<div class="card"><h3 style="font-size:14px;margin-bottom:6px">分析指标（metrics）</h3>';
  if(m.arm){
    h += `<div class="tiny" style="margin-bottom:8px">技能版本：<b>${esc(m.arm)}</b>`;
    if(m.arm_md5){
      const ks = Object.keys(m.arm_md5);
      h += ' · ' + ks.map(k=>`${esc(k)} ${esc((m.arm_md5[k]||'').slice(0,8))}`).join(' / ');
    }
    h += '</div>';
  }
  h += `<div class="kpis">
    <div class="kpi"><div class="k">引擎爆雷</div><div class="v">${m.bursts!=null?esc(m.bursts):'—'}</div></div>
    <div class="kpi"><div class="k">观测点</div><div class="v">${m.observe_n!=null?esc(m.observe_n):'—'}</div></div>
    <div class="kpi"><div class="k">终局职级</div><div class="v">${m.raw_level!=null?esc(m.raw_level):'—'}</div></div>
  </div>`;
  const lvl = (m.level_timeline||[]).map(x=>`M${x[0]}:${x[1]}`).join(' → ');
  if(lvl) h += `<div class="note">晋升时间线：${esc(lvl)}</div>`;
  const hr = m.hr_ladder||{};
  const hrOrder = [["L0_safe","HR0安全"],["L1_mild","HR1轻微"],["L2_accum","HR2累积"],["L3_critical","HR3危急"],["L4plus_imminent","HR4+临爆"]];
  const hrParts = hrOrder.filter(([k])=>hr[k]!=null).map(([k,l])=>`${l} ${hr[k]}`);
  if(hrParts.length) h += `<div class="note">HR 阶梯分布（月）：${esc(hrParts.join(' · '))}</div>`;
  const co = m.clamp_occupancy||{};
  const lvls = Object.keys(co);
  if(lvls.length){
    h += '<table><thead><tr><th>职级段</th><th>月数</th><th>任一截断率</th><th>主要截断对</th></tr></thead><tbody>';
    lvls.forEach(L=>{
      const o = co[L];
      const pairs = o.capped_pairs||{};
      const pk = Object.keys(pairs);
      const pairTxt = pk.length? pk.map(k=>`${k}×${pairs[k]}`).join(', ') : '—';
      h += `<tr><td>${esc(L)}</td><td>${o.n}</td><td>${(o.capped_any_ratio*100).toFixed(0)}%</td><td class="tiny">${esc(pairTxt)}</td></tr>`;
    });
    h += '</tbody></table>';
    h += '<div class="hint">截断率 = 该职级段内状态被职级上限吸收的月数占比；截断对 = 被同时钉在门槛的字段组合（反映瓶颈）。</div>';
  }
  h += '</div>';
  return h;
}

function bindRun(){
  document.querySelectorAll('.legend input').forEach(inp=>{
    inp.addEventListener('change', ()=>{
      const k = inp.dataset.k;
      if(inp.checked) delete off[k]; else off[k]=true;
      inp.parentElement.classList.toggle('off', !inp.checked);
      $('#chart').innerHTML = chart(RUNS[cur]);
    });
  });
  document.querySelectorAll('.mo .hdr').forEach(el=>{
    el.addEventListener('click', ()=> el.parentElement.classList.toggle('open'));
  });
  const ex = $('#expall'), co = $('#colall');
  if(ex) ex.addEventListener('click', ()=>document.querySelectorAll('.mo').forEach(m=>m.classList.add('open')));
  if(co) co.addEventListener('click', ()=>document.querySelectorAll('.mo').forEach(m=>m.classList.remove('open')));
}

function renderCmp(){
  const byDir = {}; RUNS.forEach(r=>byDir[r.dir]=r);
  let rows='';
  (DATA.batches||[]).forEach(b=>{
    const rs = b.dirs.map(d=>byDir[d]).filter(Boolean);
    const sc = rs.map(r=>r.score);
    const mean = sc.length? sc.reduce((a,x)=>a+x.score,0)/sc.length : 0;
    const early = rs.filter(r=>r.score.months<48).length;
    const am = sc.length? sc.reduce((a,x)=>a+x.months,0)/sc.length : 0;
    const lv = sc.length? sc.reduce((a,x)=>a+(x.dims.level?.raw_value||0),0)/sc.length : 0;
    const wl = sc.length? sc.reduce((a,x)=>a+(x.dims.wealth?.raw_value||0),0)/sc.length : 0;
    const hasM = rs.some(x=>x.metrics);
    const bursts = hasM ? rs.reduce((a,x)=>a+(x.metrics?.bursts||0),0) : '—';
    rows+=`<tr><td>${esc(b.tag)} · ${esc(b.label)}</td><td>${rs.length}</td>
      <td><b>${mean.toFixed(2)}</b></td><td>${early}</td><td>${am.toFixed(1)}</td>
      <td>${lv.toFixed(2)}</td><td>${wl.toFixed(1)}</td><td>${bursts}</td></tr>`;
  });
  let detail='';
  RUNS.forEach(r=>{
    const s=r.score;
    detail+=`<tr><td>${esc(r.dir)}</td>
      <td><span class="badge g-${esc(s.grade)}" style="display:inline-flex">${esc(s.grade)}</span></td>
      <td>${esc(s.score)}</td><td>${esc(s.months)}</td><td>${esc(s.dims.level?.raw_value??'')}</td>
      <td>${esc(s.dims.wealth?.raw_value??'')}</td><td>${esc(s.dims.skill?.raw_value??'')}</td>
      <td>${esc(s.dims.network?.raw_value??'')}</td>
      <td>${esc(s.dims.resilience?.raw_value??'')}</td>
      <td>${r.replay.months.filter(m=>m.burst).length}</td>
      <td class="tiny">${((s.tokens||0)/1e6).toFixed(1)}M</td></tr>`;
  });
  $('#view').innerHTML = `<div class="card"><h2 style="font-size:16px">技能版本分批对比</h2>
    <div class="hint" style="margin-bottom:8px">每局开跑前会重置技能工作区，故同批次的 4 局共享同一版技能，可直接对比。</div>
    <table><thead><tr><th>批次</th><th>局数</th><th>均值</th><th>早死(&lt;48月)</th>
      <th>平均月数</th><th>平均职级</th><th>平均财富</th><th>引擎爆雷</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="card"><h3 style="font-size:14px;margin-bottom:8px">全部对局明细（${RUNS.length} 局）</h3>
    <table><thead><tr><th>run_dir</th><th>级</th><th>分</th><th>月</th><th>职级</th><th>财富</th>
      <th>skill</th><th>network</th><th>身心</th><th>爆雷</th><th>token</th></tr></thead>
      <tbody>${detail}</tbody></table>
    <div class="hint">得分构成：职级 30% + 财富 20% + 身心 15% + 技能 15% + 风险 10% + 人脉 10%。</div></div>`;
}

function renderList(){
  const byDir={}; RUNS.forEach((r,i)=>byDir[r.dir]={r,i});
  let h='';
  if(mode==='runs'){
    (DATA.batches||[]).forEach(b=>{
      h+=`<div class="grp">${esc(b.tag)} · ${esc(b.label)}</div>`;
      b.dirs.forEach(d=>{ const e=byDir[d]; if(!e) return;
        h+=item(e.r,e.i); });
    });
    const rest = RUNS.filter(r=>!(DATA.batches||[]).some(b=>b.dirs.includes(r.dir)));
    if(rest.length){ h+=`<div class="grp">其他（历史局）</div>`;
      rest.forEach(r=>h+=item(r,RUNS.indexOf(r))); }
  } else {
    h = `<div class="grp">批次汇总</div>`;
  }
  $('#list').innerHTML = h;
  document.querySelectorAll('.item').forEach(el=>{
    el.addEventListener('click', ()=>{
      cur = +el.dataset.i;
      document.querySelectorAll('.item').forEach(x=>x.classList.remove('on'));
      el.classList.add('on');
      renderRun();
      $('.main').scrollTop = 0;
      window.scrollTo(0,0);
    });
  });
}
function item(r,i){
  const s=r.score;
  return `<div class="item ${i===cur?'on':''}" data-i="${i}">
    <span class="badge g-${esc(s.grade)}">${esc(s.grade)}</span>
    <span class="nm">${esc(r.dir.slice(9,15))}</span>
    <span class="sc">${esc(s.score)}</span></div>`;
}

document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  t.classList.add('on'); mode = t.dataset.v;
  renderList();
  if(mode==='cmp') renderCmp(); else renderRun();
}));

renderList();
renderRun();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-narrative", type=int, default=1200,
                    help="truncate each turn narrative to N chars (0 = keep all)")
    a = ap.parse_args()
    sys.exit(build(a.out, a.max_narrative))
