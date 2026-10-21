"""CareerSim 实时监控控制台（本地单端口，纯标准库，零外部依赖）。

用法:
    ./.venv/bin/python3 analysis/monitor.py            # 默认 127.0.0.1:8899
    ./.venv/bin/python3 analysis/monitor.py --port 8899
    ./.venv/bin/python3 analysis/monitor.py --run 20260925T004806Z   # 固定看某一局

浏览器打开 http://127.0.0.1:8899 即可看到实时进展、达标线缺口、相位提示、
谈话档位序列与历史批次成绩，无需盯终端。

数据源（全部只读，绝不写入任何游戏文件）:
    ../.workbuddy/logs/explore/driver.log       批次进度 / 起止时间（老 explore 驱动）
    analysis/ab/driver.log                      A/B 跑批驱动（★ 两本都要读，见 _driver_lines）
    ../.workbuddy/logs/explore/*_play.log       正在跑那一局的实时战报；
                                                两种命名：run<i>_play.log 与 <arm>_run<i>_play.log
    ../.workbuddy/logs/explore/results.tsv      历史批次成绩
    analysis/ab/results_<arm>.tsv               A/B 各臂成绩
    .career_sim_runner/career_emu/outputs/九问/<run>/score_report.json  完局的六维分

设计要点:
  * 战报是「终端渲染副本」，**不含技能文本**，故关键词匹配安全；但仍按
    「月段 → 月间播报盒 → 回合」分层解析，避免把 Agent 自己的 理由 文本当引擎事件。
  * 状态行格式:  ` L1     5     5     1     1     0     1     3`
    （level, health, dignity, skill, network, output, wealth, energy）
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.dirname(REPO)
LOGDIR = os.path.join(ROOT, ".workbuddy", "logs", "explore")
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
ABDIR = os.path.join(REPO, "analysis", "ab")
# 引擎原始日志（每局 <session>.log）——体力回合的**权威来源**，见 parse_engine_energy
EMULATOR_LOGDIR = os.path.join(REPO, ".career_sim_runner", "career_emu", "emulator_logs")

# --------------------------------------------------------------------------
# 机制常量（与 solution/skills 保持一致）
# --------------------------------------------------------------------------
# 升到下一级所需门槛 (skill, output, network, dignity)，键 = 当前职级数字
TH = {
    1: (8, 3, 3, 2),
    2: (18, 5, 6, 3),
    3: (35, 14, 18, 3),
    4: (90, 22, 30, 4),
    5: (130, 32, 45, 4),
    6: (170, 45, 60, 5),
    7: (210, 60, 80, 5),
}
# 当前职级上的截断上限 (skill, output, network) = 下一级门槛 x 1.2 向下取整
CAP = {
    1: (9, 3, 3), 2: (21, 6, 7), 3: (42, 16, 21), 4: (108, 26, 36),
    5: (156, 38, 54), 6: (204, 54, 72), 7: (252, 72, 96),
}
# 结局分上限
OUTCOME_CAP = {"skill": 120, "network": 60, "health_dignity": 20}

TALK_GOOD = ("扛的事我都记着", "第一个想到你", "下个窗口我会重点推你",
             "该准备的材料提前整理好", "你最近的表现符合预期", "半年后我们再看一档")
TALK_AVG = ("照本宣科", "你这半年不好不坏", "还在观察名单里",
            "没有要批你的意思", "只会忙、不会赢", "用同一套标准再看你")
TALK_BAD = ("最后一次调整窗口", "我不得不重新评估", "标记为「需跟进」", "半年内再没改善")

# 体力行动 → 消耗点数。★ 必须按「点数」而非「选择次数」统计：
# 「处理历史埋雷」一次就吃掉 2 点，按次数算会把「1×埋雷 + 1×准备汇报材料」的满额季度误判成 2/3。
ENERGY_COST = {
    "人脉维护": 1, "准备汇报材料": 1, "健康恢复": 1, "心理修复": 1,
    "处理历史埋雷": 2, "高强度工作": 2, "技能学习": 2,
    "保留体力（不行动）": 0, "保留体力": 0,
}

RISK_LADDER = [("生气", 5, "爆雷"), ("神情复杂", 4, "红灯"),
               ("皱着眉头", 3, "橙灯"), ("偷偷", 1, "黄灯"), ("笑着", 0, "绿灯")]

PHASE = {
    0: ("AUDIT", "评审月", "行动预算投 skill（体力效率 2:1，必须提前布局）"),
    1: ("BUILD", "发展期", "无行动预算，正常发展"),
    2: ("BUILD", "发展期", "无行动预算，正常发展"),
    3: ("SPRINT", "冲刺月", "补到 min(门槛+2, 截断上限) —— 本窗口最后一次能改变判定"),
    4: ("GUARD", "守护期", "无行动预算，一票否决任何扣减达标线的选项"),
    5: ("GUARD", "守护期", "无行动预算，一票否决任何扣减达标线的选项"),
}

# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
RE_MONTH = re.compile(r"第\s*(\d+)\s*月\s*·\s*第\s*(\d+)\s*季度\s*·\s*第\s*(\d+)\s*年")
RE_TURN = re.compile(r"回合\s*(\d+)\s*·\s*([^─\n]+)")
RE_STATUS = re.compile(
    r"^\s*(L\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(\d+)\s*$",
    re.M)
RE_CHOICE = re.compile(r"选择:\s*\[(\d+)\]\s*([^\n]*)")
RE_REASON = re.compile(r"理由:\s*([^\n]*)")
RE_PROMO = re.compile(r"已从\s*L(\d+)\s*晋升至\s*L(\d+)")
RE_SALARY = re.compile(r"基本工资到账：\+?([\d.]+)（L(\d+)）")
RE_BONUS = re.compile(r"半年绩效奖金（([SABCD])）：([+-]?[\d.]+)")
RE_RAPID = re.compile(r"升迁节奏过快")
# 引擎原始日志（emulator_logs/<session>.log）——体力回合的权威行
RE_ENG_TURN = re.compile(r"\[fixed_event\] Month (\d+) \| (季度体力行动分配|季度主行动选择)")
RE_ENG_CHOSE = re.compile(r"Chose #\d+: (.+?)\s*$")
RE_ENG_COST = re.compile(r"Energy cost: (\d+)")
RE_ENG_REM = re.compile(r"Energy remaining: (\d+)")


def _read(path: str, limit: int | None = None) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if limit:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - limit))
                return fh.read()
            return fh.read()
    except OSError:
        return ""


def parse_play_log(text: str) -> dict:
    """把一局战报切成 月段 → 回合，抽出状态/事件/选择。"""
    if not text:
        # 必须返回**完整键集**：调用方直接取 parsed["last"]/["current_month"] 等，
        # 少一个键就会 KeyError（战报缺失/被覆盖时正是这条路径）。
        return {"months": [], "months_seen": [], "current_month": 0, "snapshots": [],
                "month_events": [], "turns": [], "last": None, "ok": False}

    # ---- 月段切分（战报实时追加，最后一段可能未收尾） ----
    # ★ 关键：live 战报会**在每个回合块里重印一次月份表头**（12 个月出现 ~61 次）。
    #   因此必须按月份**聚合**所有片段，否则每个月份只会剩最后一个回合块，
    #   位于该月开头的「月间播报」盒（谈话 / 风险 / 工资 / 奖金 / 晋升）会被丢掉。
    marks = [(m.start(), int(m.group(1))) for m in RE_MONTH.finditer(text)]
    buckets: dict[int, list[str]] = {}
    for i, (pos, mo) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        buckets.setdefault(mo, []).append(text[pos:end])
    months = {mo: "\n".join(seg) for mo, seg in buckets.items()}
    ordered = sorted(months)

    # ---- 状态快照（全局顺序，用于最后状态 + 职级时间轴） ----
    snapshots = []
    for m in RE_STATUS.finditer(text):
        snapshots.append({
            "level": int(m.group(1)[1:]),
            "health": int(m.group(2)), "dignity": int(m.group(3)),
            "skill": int(m.group(4)), "network": int(m.group(5)),
            "output": int(m.group(6)), "wealth": float(m.group(7)),
            "energy": int(m.group(8)), "pos": m.start(),
        })
    # 给每个快照标注所属月份
    month_starts = [p for p, _ in marks]
    for s in snapshots:
        lo, hi = 0, len(month_starts) - 1
        idx = 0
        while lo <= hi:                      # 二分找最后一个 <= pos 的月段起点
            mid = (lo + hi) // 2
            if month_starts[mid] <= s["pos"]:
                idx = mid
                lo = mid + 1
            else:
                hi = mid - 1
        s["month"] = int(RE_MONTH.search(text[month_starts[idx]:]).group(1))

    last = snapshots[-1] if snapshots else None

    # ---- 逐月事件 ----
    month_events = []
    for mo in ordered:
        body = months[mo]
        ev: dict = {"month": mo, "talks": [], "risk": None, "promo": [], "salary": None,
                    "bonus": None, "rapid": False, "choices": []}
        ev["choices"] = [g2.strip() for _g1, g2 in RE_CHOICE.findall(body)]
        m = RE_PROMO.search(body)
        if m:
            ev["promo"].append([int(m.group(1)), int(m.group(2))])
        s = RE_SALARY.search(body)
        if s:
            ev["salary"] = float(s.group(1))
        b = RE_BONUS.search(body)
        if b:
            ev["bonus"] = [b.group(1), float(b.group(2))]
        ev["rapid"] = bool(RE_RAPID.search(body))
        # 谈话档位：只在一个 月间播报 盒内匹配，且按优先级 good→avg→bad 取一次
        for box in re.findall(r"【半年谈话】[\s\S]{0,900}", body):
            tier = None
            if any(k in box for k in TALK_GOOD):
                tier = "good"
            elif any(k in box for k in TALK_AVG):
                tier = "average"
            elif any(k in box for k in TALK_BAD):
                tier = "bad"
            if tier:
                ev["talks"].append(tier)
                break
        for word, lvl, label in RISK_LADDER:
            if word in body:
                ev["risk"] = {"word": word, "level": lvl, "label": label}
                break
        month_events.append(ev)

    # ---- 回合流（标题 + 选择 + 理由） ----
    turns = []
    tmarks = [(m.start(), int(m.group(1)), m.group(2).strip()) for m in RE_TURN.finditer(text)]
    for i, (pos, n, title) in enumerate(tmarks):
        end = tmarks[i + 1][0] if i + 1 < len(tmarks) else len(text)
        seg = text[pos:end]
        ch = RE_CHOICE.search(seg)
        rs = RE_REASON.search(seg)
        turns.append({
            "turn": n, "title": title,
            "choice": (ch.group(1) + " " + ch.group(2).strip()) if ch else None,
            "reason": (rs.group(1).strip() if rs else None),
        })

    return {
        "ok": bool(snapshots or turns),
        "months_seen": ordered,
        "current_month": ordered[-1] if ordered else 0,
        "snapshots": snapshots, "month_events": month_events,
        "turns": turns, "last": last,
    }


def _driver_lines() -> list[str]:
    """合并所有驱动日志，按时间戳升序。

    ★ 为什么必须合并：本仓库有**两套驱动**且各写各的日志——
      * `.workbuddy/logs/explore/driver.log`  —— 老 explore 驱动
      * `analysis/ab/driver.log`              —— A/B 跑批驱动（`analysis/ab_driver.py`）
    只看第一本会得出「当前没有批次在跑」的**错误结论**（实测踩过：A/B 批次跑到 M41，
    控制台却显示空闲）。两本都是带 `[YYYY-MM-DD HH:MM:SS]` 前缀的行式日志，
    按时间戳归并即可得到真实的事件顺序。
    ★ 第三套（2026-09-26 补）：`analysis/ab/driver_<arg>.out` —— `launch_ab.py`
      分臂/分次启动产生的**独立日志**（如 `driver_v10b_2.out`、`driver_v10c_5.out`）。
      只合并前两本的话，新批次的进度全都看不见 ⇒ 面板心跳停在最后一次
      `driver.log` 写入，看起来像「批次停了」（实测踩过：v10c 正跑到 M2x，
      8899 却显示空闲）。
    """
    merged: list[tuple[str, int, int, str]] = []
    paths = [os.path.join(LOGDIR, "driver.log"),
             os.path.join(ABDIR, "driver.log")]
    paths += sorted(glob.glob(os.path.join(ABDIR, "driver_*.out")))
    for fi, path in enumerate(paths):
        if not os.path.isfile(path):
            continue
        tag = os.path.basename(path)
        for ln, line in enumerate(_read(path).splitlines()):
            m = re.match(r"^\[([\d\-: ]{19})\]", line)
            # ★ 行尾追加来源标记：合并 5+ 本日志后同一事件会与其它批次的行
            #   按时间交错显示（如 TIMEOUT×2、attempt×3），不加标记无法分辨
            #   哪行来自哪个批次（实测被当成「数据乱」）。标记放行尾，
            #   不破坏 `^\[时间戳\]` 前缀与 `RUN i DONE dir=` 等下游正则。
            merged.append((m.group(1) if m else "0000-00-00 00:00:00",
                           fi, ln, f"{line}  ⟨{tag}⟩"))
    merged.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in merged]


def _arm_before(lines: list[str], ln: int) -> str | None:
    """从第 `ln` 行向前回溯，取最近的 ARM 头；遇到**真**会话开场行即停。

    ★ 必须「向前回溯」而不是「从文件头正扫」：`RUN 1/4 START` 这样的行号
    在一天里会出现很多次（每批都从 RUN 1 开始），从文件头正扫会命中最古老的
    那一次，返回一个**与当前批次无关**的臂名（实测踩过：正扫到 00:15 的
    `RUN 1/8`，拿回 None，于是整个 A/B 批次识别失败）。
    另外必须用「会话开场行」截断，否则会把上一批的臂名带进来。

    ★★ 但**不是所有** `AB SESSION START` 都该当截断点（2026-09-26 修）：
    存在「**流产会话**」——它记了开场行，却**从没走到 ARM 头**就开始等待。
    典型来源：把 `--help` 之类的非臂名参数传给 `ab_driver.py`，`main()` 先打印
    开场行、再 `wait_until_idle()` 空等（实测发生过一次，且它的开场行**插在本批次
    的 `ARM` 头与 `RUN 4/4 START` 之间**）。
    若把它当截断点，本批次的臂名会被一起丢掉 ⇒ `arm=None` ⇒ 回退去读**不带臂前缀**的
    旧 `runNN_play.log`（9/25 的遗留文件）⇒ **面板整局纹丝不动**（实测：显示
    `month 49/48`、`eta −19`、`arm: null`，而真局正跑到第 23 月）。

    ⇒ 判据：开场行的**下一行**若是「another game in flight … waiting」，
      说明该会话还没 stage 就进入等待（流产）⇒ **跳过它继续往前找**，不要截断。
      真会话的下一行必然是 `########## ARM <名> — N run(s) ##########` 或 staged 行。
    """
    for i in range(min(ln, len(lines) - 1), -1, -1):
        line = lines[i]
        if "AB SESSION START" in line:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if "another game in flight" in nxt:
                continue          # 流产会话（未 stage），不是批次边界
            return None
        m = re.search(r"#{5,}\s*ARM\s+([A-Za-z0-9_.\-]+)", line)
        if m:
            return m.group(1)
    return None


def log_for_run_dir(dirname: str) -> str | None:
    """由 run 输出目录名反查对应的战报文件。

    ★ 必须反查，不能硬编码 run01_play.log：每批都用 run01/run02/… 命名，
    直接把所有 `--run` 都指向 run01_play.log 会**静默返回另一局的数据**
    （实测：两个不同的 run 目录给出完全相同的逐季体力，就是这么来的）。
    映射关系只存在于 driver.log 的 `RUN i DONE dir=...` 行里。

    ★ 候选名有两种：老驱动的 `run<i>_play.log`，A/B 驱动的 `<arm>_run<i>_play.log`。
    臂名从该 DONE 行向前回溯得到。
    """
    lines = _driver_lines()
    for ln in range(len(lines) - 1, -1, -1):
        m = re.search(r"RUN\s+(\d+)\s+DONE\s+dir=(\S+)", lines[ln])
        if not (m and os.path.basename(m.group(2)) == dirname):
            continue
        i = int(m.group(1))
        arm = _arm_before(lines, ln)
        cands = [os.path.join(LOGDIR, f"run{i:02d}_play.log")]
        if arm:
            cands.insert(0, os.path.join(LOGDIR, f"{arm}_run{i:02d}_play.log"))
        for cand in cands:
            if os.path.isfile(cand):
                return cand
    return None


def run_session(dirname: str | None) -> str | None:
    """由某局输出目录名取该局的**引擎 session id**（= `emulator_logs/<session>.log` 的主名）。

    ⚠️ 不能用 `events-*.jsonl` 的**文件名**当 session：那是**运行目录名**（如
       20260926T205235Z），不是引擎 session。真正的 32 位 id 有两处来源：
         · `score_report.json` 的 `session` 字段 —— 但**只有完赛后才写**，运行中读不到；
         · `events-*.jsonl` 内 take_action 的 `arguments.session_id` —— **运行中就有**。
       故优先读事件流（抓第一个 session_id，扫头部 400KB 足够）。
    """
    if not dirname:
        return None
    d = os.path.join(OUTROOT, dirname)
    if not os.path.isdir(d):
        return None
    try:
        names = os.listdir(d)
    except OSError:
        return None
    # ① 事件流（运行中可用）
    for fn in names:
        if fn.startswith("events-") and fn.endswith(".jsonl"):
            txt = _read(os.path.join(d, fn), limit=400_000)
            m = re.search(r'session_id\\*"\s*:\s*\\*"([0-9a-fA-F]{16,})', txt)
            if m:
                return m.group(1)
    # ② 战报（完赛后的兜底）
    txt = _read(os.path.join(d, "score_report.json"))
    m = re.search(r'"session"\s*:\s*"([0-9a-fA-F]{16,})"', txt)
    return m.group(1) if m else None


def parse_engine_energy(session: str | None) -> dict[int, list[tuple[str, int]]]:
    """从**引擎**日志读权威体力回合，返回 `{月: [(行动名, 耗点), ...]}`。

    ★★ 为什么必须补这条路（2026-09-27）：战报（play log）是**按 LLM 回合渲染**的，
      一个回合只落一条 `选择:` 行；而引擎 prompt 原文写明「可以组合多个行动」
      ⇒ Agent 把 3 个体力行动并进**一个回合**提交时，战报只留 1 条选择行，
      **会丢掉其余体力选择**（实测 v10d_run02 的 Q5–Q9；同类现象在
      `build_replay_html.py` 的 `parse_energy_rounds` 里也记过
      「091245Z M24 lost its 3rd round」——同一坑，两处独立踩到）。
    引擎日志逐条记 `Chose #N` + `Energy cost` + `Energy remaining`，是唯一完整来源。
    """
    out: dict[int, list[tuple[str, int]]] = {}
    if not session:
        return out
    path = os.path.join(EMULATOR_LOGDIR, f"{session}.log")
    if not os.path.isfile(path):
        return out
    month: int | None = None
    name: str | None = None
    cost: int | None = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = RE_ENG_TURN.match(line)
                if m:
                    # 只在「体力行动分配」段内计数；进入主行动段即关闭
                    month = int(m.group(1)) if m.group(2) == "季度体力行动分配" else None
                    name = cost = None
                    continue
                if month is None:
                    continue
                c = RE_ENG_CHOSE.match(line)
                if c:
                    name, cost = c.group(1), None
                    continue
                e = RE_ENG_COST.match(line)
                if e and name is not None:
                    cost = int(e.group(1))
                    continue
                if RE_ENG_REM.match(line) and name is not None and cost is not None:
                    out.setdefault(month, []).append((name, cost))
                    name = cost = None
    except OSError:
        return out
    return out


def candidate_sessions(dirname: str | None, max_month: int | None = None) -> list[str]:
    """给出**可能**属于当前这一局的引擎 session 候选，按可信度排序。

    * 首选：由运行目录反查（完赛局一定有；运行中局靠 events 里的 session_id）。
    * 兜底：**运行中的局**驱动还没写 `RUN i DONE dir=` ⇒ `info["dir"]` 为 None，
      此时按 mtime 取最新若干本引擎日志（本项目**同一时刻只跑一局**，驱动会
      `another game in flight — waiting` 串行化 ⇒ 最新那本必是当前局）。
      候选是否采纳，由 `build_state` 里的「耗点合计 == 能量轨迹」+「月份量级」双闸决定，
      错配一律退回战报口径，**绝不张冠李戴**。
    """
    out: list[str] = []
    s = run_session(dirname)
    if s:
        out.append(s)
    if max_month:                      # 仅运行中（拿不到 dir）才需要兜底
        try:
            logs = sorted(glob.glob(os.path.join(EMULATOR_LOGDIR, "*.log")),
                          key=os.path.getmtime, reverse=True)[:6]
        except OSError:
            logs = []
        for p in logs:
            nm = os.path.basename(p)[:-4]
            if nm not in out:
                out.append(nm)
    return out


def find_active_run(fixed: str | None = None) -> dict:
    """定位「正在跑或最近跑完」的那一局。"""
    info = {"index": None, "total": None, "started_at": None, "finished": None,
            "log": None, "dir": None, "score": None, "arm": None}
    lines = _driver_lines()

    # ★ `=*` 而非 `=+`：老 explore 驱动写 `[...] ===== RUN 1/1 START`，
    #   A/B 驱动（analysis/ab_driver.py）写 `[...]   RUN 1/4 START`，**没有等号**。
    #   写成 `=+` 会静默漏掉整个 A/B 批次，控制台显示「空闲」。
    start_re = re.compile(r"^\[([\d\-: ]{19})\]\s*=*\s*(?:RESUME\s+)?RUN\s+(\d+)/(\d+)\s+START")
    done_re = re.compile(r"^\[([\d\-: ]{19})\]\s*RUN\s+(\d+)\s+(DONE|FAILED|TIMEOUT)")
    done_detail = re.compile(r"RUN\s+(\d+)\s+DONE\s+dir=(\S+)")

    # ★ driver.log 是**跨批次追加**的，历史批次的同名 "RUN 1 DONE" 行会被误当成本次结果。
    #   正解：先定位最后一次 START 的**行号**，只在它之后寻找 DONE。
    start = None
    for ln, line in enumerate(lines):
        m = start_re.search(line)
        if m:
            start = (ln, int(m.group(2)), int(m.group(3)), m.group(1))
    if start:
        info["start_ln"], info["index"], info["total"], info["started_at"] = start
        for ln in range(start[0] + 1, len(lines)):
            m = done_re.search(lines[ln])
            if m and int(m.group(2)) == info["index"]:
                info["finished"] = (m.group(1), m.group(3))
                d = done_detail.search(lines[ln])
                if d:
                    info["done_dir"] = d.group(2)
                break

    if fixed:
        info["dir"] = os.path.join(OUTROOT, fixed)
        info["log"] = log_for_run_dir(fixed)
        info["log_stale"] = info["log"] is None
    elif info["index"]:
        # ★ A/B 驱动的战报名是 <arm>_run<i>_play.log，必须先解析臂名再拼名。
        #   臂名从**本次 START 行**向前回溯取，不能用「第 index 次 RUN」从文件头正扫。
        info["arm"] = _arm_before(lines, info["start_ln"])
        if info["arm"]:
            # 已经知道是 A/B 批次：只认带臂前缀的名字。
            # ⛔ 不能回退到 run<i>_play.log —— 那是**别的驱动**留下的同名文件，
            #    会「拿 A 批的轨迹配 B 批的进度」（实测踩过两次）。
            info["log"] = os.path.join(
                LOGDIR, f"{info['arm']}_run{info['index']:02d}_play.log")
            if not os.path.isfile(info["log"]):
                info["log"] = None
        else:
            info["log"] = os.path.join(LOGDIR, f"run{info['index']:02d}_play.log")
    # 回退到「最新战报」仅在不指定 run **且不知道臂名**时允许——指定了 run 就必须是它自己的日志，
    # 否则宁可报空也不显示别人的数据。
    # ★ A/B 批次里，驱动是「先写 RUN i START、后创建战报文件」，中间有个窗口；
    #   此时若回退到「最新战报」，显示的就是**上一局**的轨迹（张冠李戴）。故 arm 已知时不回退。
    if fixed is None and not info.get("arm") \
            and (not info["log"] or not os.path.isfile(info["log"])):
        cands = glob.glob(os.path.join(LOGDIR, "*_play.log"))
        cands = [c for c in cands if os.path.getsize(c) > 20000]
        if cands:
            info["log"] = max(cands, key=os.path.getmtime)

    # 输出目录：优先用 DONE 行里记下的目录名；其次仅在**本局已结束**时取最新时间戳目录。
    # ★ 运行中绝不能回退到最新目录——那是上一局的，会把旧结局分显示成本局结果。
    if info["dir"] is None and info.get("done_dir"):
        cand = os.path.join(OUTROOT, info["done_dir"])
        if os.path.isdir(cand):
            info["dir"] = cand
    if info["dir"] is None and info["finished"] and os.path.isdir(OUTROOT):
        dirs = [os.path.join(OUTROOT, d) for d in os.listdir(OUTROOT)
                if os.path.isdir(os.path.join(OUTROOT, d))]
        # ★ 2026-09-27：mtime 最新的目录可能是**失败残局**，选中它页面会整片空白。
        #   注意 score_report.json 对失败局也会生成（play_exit_code=1、
        #   termination_reason=max_continuations），故必须按退出码过滤。
        def _completed(d: str) -> bool:
            sr = os.path.join(d, "score_report.json")
            if not os.path.isfile(sr):
                return False
            try:
                return json.loads(_read(sr)).get("play_exit_code") == 0
            except (ValueError, OSError):
                return False

        scored = [d for d in dirs if _completed(d)]
        if scored:
            info["dir"] = max(scored, key=os.path.getmtime)
        elif dirs:
            info["dir"] = max(dirs, key=os.path.getmtime)
    if info["dir"]:
        sr = os.path.join(info["dir"], "score_report.json")
        if os.path.isfile(sr):
            try:
                info["score"] = json.loads(_read(sr))
            except (ValueError, OSError):
                info["score"] = None
        info["dir_name"] = os.path.basename(info["dir"])

    # ★ 战报新鲜度校验：同一批次里每局都叫 run01/run02/…，
    #   后一批会**覆盖**前一批的同名战报 ⇒ 只凭文件名会「拿 A 局的轨迹配 B 局的分数」。
    #   战报在局内边跑边写、score_report 紧随其后生成 ⇒ 若战报比 score_report 还新，
    #   它必然属于**之后的**某一局，本局轨迹已不可得，宁可只显示结局分。
    if info.get("log") and info.get("score") and os.path.isfile(info["log"]):
        try:
            log_mt = os.path.getmtime(info["log"])
            rep_mt = os.path.getmtime(os.path.join(info["dir"], "score_report.json")) \
                if info.get("dir") else 0
            if rep_mt and log_mt > rep_mt + 60:
                info["log_stale"] = True
                info["log_overwritten_by"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(log_mt))
                info["log"] = None
        except OSError:
            pass
    return info


def gate_board(level: int, st: dict) -> dict:
    """三条硬指标 + 尊严 的缺口 / 余量 / 截断上限。"""
    nxt = TH.get(level)
    if not nxt:
        return {"next_level": None, "items": []}
    cap = CAP.get(level, (None, None, None))
    keys = ("skill", "output", "network")
    names = {"skill": "专业能力", "output": "业绩产出", "network": "人脉网络"}
    items = []
    for i, k in enumerate(keys):
        cur = st.get(k, 0)
        need = nxt[i]
        c = cap[i]
        items.append({
            "key": k, "name": names[k], "cur": cur, "need": need, "cap": c,
            "gap": max(0, need - cur), "margin": cur - need,
            "capped": (c is not None and cur >= 0.95 * c),
            "overflow": (c is not None and cur >= c),
            "pct_need": min(100, round(100 * cur / need)) if need else 100,
        })
    d = st.get("dignity", 0)
    items.append({"key": "dignity", "name": "尊严", "cur": d, "need": nxt[3],
                  "cap": 10, "gap": max(0, nxt[3] - d), "margin": d - nxt[3],
                  "capped": d >= 10, "overflow": d >= 10,
                  "pct_need": min(100, round(100 * d / nxt[3])) if nxt[3] else 100})
    min_margin = min(i["margin"] for i in items)
    return {"next_level": level + 1, "items": items,
            "min_margin": min_margin,
            "verdict": ("✅ 余量充足（≥+2）" if min_margin >= 2 else
                        "⚠️ 余量偏低（+1）" if min_margin == 1 else
                        "⚠️ 压线（0）" if min_margin == 0 else "❌ 未达标")}


def history() -> list[dict]:
    """历史成绩：老驱动的 results.tsv + A/B 各臂的 results_<arm>.tsv。

    ★ 只读 results.tsv 会漏掉全部 A/B 数据（A/B 驱动分臂写文件）。
    """
    files = [os.path.join(LOGDIR, "results.tsv")]
    if os.path.isdir(ABDIR):
        # ★ 2026-09-27 修：必须按文件 mtime 排序。字典序里 `results_v10* < results_v5* <
        #   results_v9*`（'1'<'5'<'9'），前端 `slice(-14)` 会把**最老**的 v8/v9 当成"最新"，
        #   v10b/c/d/e 全被切掉 —— 面板看起来"不更新、数据对不上"。
        files += sorted(glob.glob(os.path.join(ABDIR, "results_*.tsv")),
                        key=os.path.getmtime)
    rows: list[dict] = []
    seen: set[str] = set()
    for path in files:
        txt = _read(path)
        if not txt:
            continue
        lines = [l for l in txt.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        head = lines[0].split("\t")
        if "run_dir" not in head or "score" not in head:
            continue
        for line in lines[1:]:
            d = dict(zip(head, line.split("\t")))
            key = d.get("run_dir") or line
            if key in seen:
                continue
            seen.add(key)
            if d.get("arm") is None and "_" in os.path.basename(path):
                arm = os.path.basename(path)
                if arm.startswith("results_") and arm.endswith(".tsv"):
                    d.setdefault("arm", arm[len("results_"):-len(".tsv")])
            d["_src"] = os.path.basename(path)
            # ★ 2026-09-27 修：A/B 新格式（run_dir/raw_skill/raw_network，且**没有** output 列）
            #   与老格式列名不同；前端读 run/skill/network ⇒ 逐行归一化，否则 run 列空白、S/N 显示 "//"。
            d.setdefault("run", d.get("run_dir") or "")
            d.setdefault("skill", d.get("raw_skill") or "")
            d.setdefault("network", d.get("raw_network") or "")
            d.setdefault("output", d.get("raw_output") or d.get("raw_risk_control") or "")
            rows.append(d)
    return rows


def summarise_score(sr: dict | None) -> dict | None:
    """从 score_report.json 抽出便于展示的结局面板。"""
    if not sr:
        return None
    es = sr.get("ending_score") or {}
    dims = []
    for d in es.get("dimensions", []):
        dims.append({"label": d.get("label", d.get("name")), "name": d.get("name"),
                     "raw": d.get("raw_value"), "weight": d.get("weight"),
                     "weighted": d.get("weighted_score")})
    return {"grade": es.get("grade"), "score": es.get("quantitative_score"),
            "competition": es.get("competition_partial_score"),
            "months": es.get("survival_months"), "outcome": es.get("outcome"),
            "dims": dims, "tokens": (sr.get("token_usage") or {}).get("total_tokens"),
            "session": sr.get("session_id")}


def build_state(fixed: str | None = None) -> dict:
    info = find_active_run(fixed)
    # 战报会持续增长；读尾部 1.2MB 足够（48 个月的战报约 300KB）
    text = _read(info["log"], limit=1_200_000) if info["log"] else ""
    parsed = parse_play_log(text)
    st = parsed["last"] or {}

    level = st.get("level", 1)
    month = parsed["current_month"]
    r = month % 6 if month else None
    phase = dict(zip(("code", "name", "hint"), PHASE.get(r, ("—", "—", "—")))) if r is not None else {}

    # 进度 / ETA
    elapsed = None
    if info["started_at"]:
        try:
            t0 = time.mktime(time.strptime(info["started_at"], "%Y-%m-%d %H:%M:%S"))
            if info["finished"]:
                t1 = time.mktime(time.strptime(info["finished"][0], "%Y-%m-%d %H:%M:%S"))
            else:
                t1 = time.time()
            elapsed = round(t1 - t0)
        except (ValueError, OverflowError):
            elapsed = None
    eta = None
    if elapsed and month and not info["finished"]:
        eta = round(elapsed / month * (48 - month))

    # 晋升时间轴
    level_timeline = []
    for ev in parsed["month_events"]:
        for a, b in ev["promo"]:
            level_timeline.append({"month": ev["month"], "from": a, "to": b})
    # 兜底：用状态快照推职级变化
    if not level_timeline and parsed["snapshots"]:
        prev = None
        for s in parsed["snapshots"]:
            if prev is not None and s["level"] != prev:
                level_timeline.append({"month": s["month"], "from": prev, "to": s["level"]})
            prev = s["level"]

    talk_seq = [{"month": e["month"], "tier": t}
                for e in parsed["month_events"] for t in e["talks"]]
    bonus_seq = [{"month": e["month"], "grade": e["bonus"][0], "amount": e["bonus"][1]}
                 for e in parsed["month_events"] if e["bonus"]]
    risks = [{"month": e["month"], **e["risk"]} for e in parsed["month_events"] if e["risk"]]

    # 体力使用纪律（「每季度必须连选 3 次用尽」）——★ 按**消耗点数**统计，不是选择次数
    #  （a）战报口径：把每个渲染出来的 `选择:` 行按 ENERGY_COST 折成点数。
    by_q: dict[int, list[str]] = {}
    pts_q: dict[int, int] = {}
    for e in parsed["month_events"]:
        qq = (e["month"] - 1) // 3 + 1
        for c in e["choices"]:
            if c in ENERGY_COST:
                by_q.setdefault(qq, []).append(c)
                pts_q[qq] = pts_q.get(qq, 0) + ENERGY_COST[c]

    #  ★★（b）引擎真值口径（2026-09-27 增）：季度内的 energy **只在季度末月（3q）重置**，
    #    因此只在**该月**取 max−min 即得本季真实消耗。⚠️ 两个坑（都实测踩过）：
    #      坑1 月份取全身：季度前两月（3q−2、3q−1）的 energy 列显示的是**上一季的剩余值**
    #          （未重置），混进来会把 max−min 算大（实测 v10b_run02 Q16：真实用 2，
    #          混入上一季的 0 后算成 3），⇒ **必须只统计 month == 3q 的快照**。
    #      坑2 只按选择行：战报**按 LLM 回合渲染**，一回合只落一条 `选择:` 行；但引擎
    #          **允许一个回合组合多个体力行动**（prompt 原文「可以组合多个行动」）。
    #          ⇒ Agent 把 3 个体力行动并进一个回合提交时，战报只留 1 条选择行，
    #            （a）会**系统性漏计**，把「已用尽」误判成「没执行纪律」。
    #    实测（v10d RUN2，2026-09-27）：16 个季度引擎**全部扣满 3 点**（E 恒 3→0），
    #      却被（a）漏计成 Q5/Q6/Q7=1、Q8/Q9=2 ⇒ 面板误报「未用尽、共浪费 8 点」，**错怪 Agent**。
    #    交叉验证：该局 events.jsonl 中这些季度各有 **3 次 take_action**（notes 明写
    #      `M15体力1/3 · 2/3 · 3/3`），且状态增量吻合（output +2、network +1）。
    e_traj: dict[int, list[int]] = {}
    for s in parsed["snapshots"]:
        if s["month"] % 3:            # 只看季度末月（3q）——见坑1
            continue
        e_traj.setdefault(s["month"] // 3, []).append(s["energy"])
    traj_q = {qq: max(es) - min(es) for qq, es in e_traj.items() if es}

    #  ★（c）引擎日志口径（最权威）：逐条 `Chose #N` + `Energy cost`，**含战报丢掉的组合行动**。
    #    只在「耗点合计 == 能量轨迹」或「轨迹缺失」时采纳 —— 宁可退回战报口径，
    #    也绝不因 session 反查失手而张冠李戴（本项目历史上踩过这类静默错配）。
    eng_q: dict[int, list[str]] = {}
    eng_pts: dict[int, int] = {}
    _dirname = info.get("dir_name") or os.path.basename(info.get("dir") or "")
    for _ses in candidate_sessions(_dirname, month):
        _cand = parse_engine_energy(_ses)
        if not _cand:
            continue
        _agg: dict[int, list[str]] = {}
        _pts: dict[int, int] = {}
        _mx = 0
        for _mo, _items in _cand.items():
            _qq = _mo // 3                 # 体力段只出现在季度末月 3q
            if _qq < 1:
                continue
            _mx = max(_mx, _mo)
            for _nm, _c in _items:
                _agg.setdefault(_qq, []).append(_nm)
                _pts[_qq] = _pts.get(_qq, 0) + _c
        #  双闸校验：① 每个「战报见过」的季度，耗点必须等于能量轨迹；
        #            ② 该候选的月份量级要与本局相符（挡掉别的局的引擎日志）。
        if any(traj_q.get(i) is not None and _pts.get(i, 0) != traj_q[i] for i in _agg):
            continue
        if month and not (month - 2 <= _mx <= month + 2):
            continue
        eng_q, eng_pts = _agg, _pts
        break

    #  ★★ 2026-09-27 修：不再三口径盲取 max。两个原因：
    #    ① 每季体力物理上限 = 3 点 ⇒ 任何口径算出 >3 都只能是**数据污染**
    #       （实测：v10e RUN3/RUN4 因 stale session 清不掉（trash-failed）而反复重试，
    #        战报/轨迹里叠了两轮体力行 ⇒ 面板出现 6/4/5/4）；
    #    ② 引擎日志口径（eng）带双闸校验，最权威 ⇒ 有它就直接用，不被 max 放大。
    used_q: dict[int, int] = {}
    contaminated_q: list[int] = []
    for i in (set(pts_q) | set(traj_q) | set(eng_pts)):
        vals = [v for v in (pts_q.get(i, 0), traj_q.get(i, 0), eng_pts.get(i, 0)) if v]
        u = eng_pts[i] if i in eng_pts else (max(vals) if vals else 0)
        if vals and max(vals) > 3:
            contaminated_q.append(i)
            u = min(u, 3)
        used_q[i] = u
    #  展示「选了哪些」优先用引擎口径（完整）；没有才退回战报渲染的选择行（可能缺条）
    picks_q: dict[int, list[str]] = {i: (eng_q.get(i) or by_q.get(i, []))
                                     for i in (set(eng_q) | set(by_q))}
    #  战报**漏渲染**的季度：权威口径 > 战报选择行口径（−1 容差，避开边界噪声）
    under_q = {i for i in used_q if (used_q[i] - pts_q.get(i, 0)) >= 1}

    q = (month - 1) // 3 + 1 if month else 0
    # 最近一个「行动窗口已开放」的季度（3 的倍数月），否则就是上一季度
    acted = [m for m in parsed["months_seen"] if m % 3 == 0]
    last_action_month = max(acted) if acted else None
    last_action_q = (last_action_month - 1) // 3 + 1 if last_action_month else None
    #  ★ 只有「观测证据充分」且「季度已过完」才谈「未用尽」，否则会把**进行中**的季度
    #    误判成浪费（实测：v10_run01 的 Q8、v10b_run02 的 Q17 全因此假阳性）。
    #    · 证据充分 = 该季见过体力选择行，或轨迹证明确实动过（traj>0）；
    #    · 季度过完 = 已进入下一季（i < q），或整局已结束（finished）。
    _q_done = bool(info.get("finished"))

    def _has_evidence(i: int) -> bool:
        return (i in eng_q) or (i in by_q) or traj_q.get(i, 0) > 0

    energy_by_quarter = [{"q": i, "used": used_q.get(i, 0),
                          "picks": picks_q.get(i, []),
                          "src": "engine" if i in eng_q else ("play" if i in by_q else None),
                          "traj": traj_q.get(i),
                          "under": i in under_q,
                          "open": (i * 3 in acted)} for i in range(1, 17)]

    # 关键告警（把纪律变成看得见的红黄灯）
    alerts: list[dict] = []
    if contaminated_q:
        alerts.append({"lv": "amber",
                       "text": f"第 {','.join(map(str, sorted(contaminated_q)))} 季度的体力口径出现 >3 的读数 —— "
                               f"该局存在**重复行**（多为失败重试把两轮战报/轨迹叠进了同一目录），"
                               f"已按每季物理上限 3 点截断显示，不代表 Agent 真的超用。"})
    if info.get("log_stale"):
        alerts.append({"lv": "amber",
                       "text": f"该局的战报已被后续批次覆盖（同名文件最后写入于 "
                               f"{info.get('log_overwritten_by')}）—— 下面只显示结局分，"
                               f"轨迹数据不可得，避免张冠李戴。"})
    h = st.get("health")
    if h is not None:
        if h <= 3:
            alerts.append({"lv": "red", "text": f"健康 {h} ≤3 —— 一击必杀线，禁止一切 ΔHealth<0"})
        elif h <= 5:
            alerts.append({"lv": "amber", "text": f"健康 {h} ≤5 —— 本季必须留 1 点体力给「健康恢复」"})
    if st.get("dignity", 0) >= 10:
        alerts.append({"lv": "info", "text": "尊严 10（满值）—— 所有 Dignity+X 的选项与体力动作收益全部溢出"})
    if last_action_q:
        used = used_q.get(last_action_q, 0)
        _closed = (last_action_q < q) or _q_done
        if used < 3 and _closed and _has_evidence(last_action_q):
            alerts.append({"lv": "red",
                           "text": f"第 {last_action_q} 季度体力只用了 {used}/3 点 —— 未用的部分永久作废（须连续选到非体力回合）"})
        elif used >= 3:
            alerts.append({"lv": "ok", "text": f"第 {last_action_q} 季度体力已用尽 3/3 点"})
        else:
            alerts.append({"lv": "info", "text": f"第 {last_action_q} 季度体力窗口进行中（已用 {used}/3，尚未结算）"})
    low_q = [i for i in range(1, 17)
             if (i * 3 in acted) and used_q.get(i, 0) < 3
             and _has_evidence(i) and ((i < q) or _q_done)]
    if low_q:
        alerts.append({"lv": "amber",
                       "text": "体力未用尽的季度：" + "、".join(f"Q{i}" for i in low_q) + "（共浪费 %d 点）"
                               % sum(3 - used_q.get(i, 0) for i in low_q)})
    if under_q:
        alerts.append({"lv": "info",
                       "text": "战报未逐条渲染体力行动的季度：" + "、".join(f"Q{i}" for i in sorted(under_q))
                               + "（Agent 把一个回合内的多个体力行动**组合提交**，战报每回合只落 1 条选择行；"
                                 "已改用 **energy 轨迹 + 引擎日志** 校正，上表数值为真实消耗，非浪费）"})
    sk, nw = st.get("skill", 0), st.get("network", 1)
    if nw and sk > 2 * nw:
        alerts.append({"lv": "red", "text": f"配比失衡 skill/network = {sk/nw:.2f} > 2 —— 禁止任何 ΔSkill>0"})
    oc = OUTCOME_CAP["skill"]
    if sk > oc:
        alerts.append({"lv": "amber", "text": f"技能 {sk} 已超结局分上限 {oc}，超出部分不产生分数"})

    return {
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run": {k: v for k, v in info.items() if k != "score"},
        "score": info.get("score"),
        "final": summarise_score(info.get("score")),
        "elapsed": elapsed, "eta": eta,
        "progress": {"month": min(month, 48), "of": 48,
                     "pct": min(100, round(100 * month / 48)) if month else 0},
        "state": st, "phase": phase, "r": r,
        "gates": gate_board(level, st) if st else {"next_level": None, "items": []},
        "level_timeline": level_timeline,
        "talk_seq": talk_seq, "bonus_seq": bonus_seq, "risks": risks,
        "energy_used": used_q.get(last_action_q or 0, 0),
        "energy_by_quarter": energy_by_quarter,
        "energy_quarter": q, "last_action_q": last_action_q,
        "last_action_month": last_action_month,
        "alerts": alerts,
        "turns": parsed["turns"][-40:],
        "month_events": parsed["month_events"],
        "history": history(),
        "log_path": info["log"], "log_size": os.path.getsize(info["log"]) if info["log"] and os.path.isfile(info["log"]) else 0,
    }


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>CareerSim 实时监控台</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--line:#e2e8f0;--ink:#1b2430;--dim:#64748b;
--blue:#2563eb;--green:#059669;--amber:#d97706;--red:#dc2626;--violet:#7c3aed;--slate:#94a3b8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 18px 60px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:19px;margin:0;letter-spacing:.3px}
.pill{font-size:12px;padding:2px 9px;border-radius:99px;background:#e8edf5;color:var(--dim)}
.pill.run{background:#dcfce7;color:#166534}
.pill.done{background:#e2e8f0;color:#475569}
.pill.err{background:#fee2e2;color:#991b1b}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:860px){.g2,.g3{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:14px 16px;
box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card h2{font-size:13px;margin:0 0 11px;color:var(--dim);font-weight:600;letter-spacing:.4px}
.big{font-size:26px;font-weight:650;line-height:1.15}
.big small{font-size:13px;font-weight:400;color:var(--dim);margin-left:5px}
.kv{display:flex;gap:18px;flex-wrap:wrap;margin-top:9px}
.kv div{font-size:12px;color:var(--dim)}
.kv b{display:block;font-size:16px;color:var(--ink);font-weight:600}
.bar{height:7px;border-radius:99px;background:#eef2f7;position:relative;overflow:hidden;margin:7px 0 3px}
.bar>i{position:absolute;inset:0 auto 0 0;border-radius:99px;background:var(--blue)}
.bar>u{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink);opacity:.55}
.bar>v{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--violet)}
.row{margin-bottom:11px}
.row .lab{display:flex;justify-content:space-between;font-size:12.5px}
.row .lab b{font-weight:600}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
.tl{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.cell{width:19px;height:19px;border-radius:4px;background:#eef2f7;font-size:9px;display:flex;
align-items:center;justify-content:center;color:#94a3b8;position:relative}
.cell.review{box-shadow:inset 0 0 0 1.5px #cbd5e1}
.cell.sprint{background:#ede9fe;color:#5b21b6}
.cell.past{background:#dbeafe;color:#1e40af}
.cell.promo{background:#059669;color:#fff;font-weight:700}
.cell.cur{background:#f59e0b;color:#fff;font-weight:700;outline:2px solid #fbbf24}
.cell.e3{background:#059669;color:#fff}
.cell.e12{background:#f59e0b;color:#fff}
.cell.e0{background:#ef4444;color:#fff}
.cell.und{outline:2px dashed #334155;outline-offset:-2px}
.al{border-radius:8px;padding:7px 11px;margin-bottom:6px;font-size:12.5px;border:1px solid}
.al.red{background:#fee2e2;color:#991b1b;border-color:#fecaca}
.al.amber{background:#fef3c7;color:#92400e;border-color:#fde68a}
.al.ok{background:#dcfce7;color:#166534;border-color:#bbf7d0}
.al.info{background:#eff6ff;color:#1e3a8a;border-color:#bfdbfe}
.tag{display:inline-block;font-size:11.5px;padding:1.5px 8px;border-radius:99px;margin:2px 4px 2px 0}
.tag.good{background:#dcfce7;color:#166534}
.tag.average{background:#fef3c7;color:#92400e}
.tag.bad{background:#fee2e2;color:#991b1b}
.tag.S{background:#059669;color:#fff}.tag.A{background:#10b981;color:#fff}
.tag.B{background:#f59e0b;color:#fff}.tag.C{background:#94a3b8;color:#fff}
.tag.D{background:#64748b;color:#fff}
.risk{font-size:12.5px;padding:6px 10px;border-radius:8px;background:#f1f5f9;color:#334155}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:5px 7px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:11.5px}
td.n{text-align:right;font-family:ui-monospace,Menlo,monospace}
.turn{color:var(--dim);font-size:11.5px;white-space:nowrap}
.hint{background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a;border-radius:9px;
padding:10px 13px;font-size:13px;margin-top:10px}
.hint b{color:#1d4ed8}
.empty{color:var(--dim);font-size:13px;padding:8px 0}
.scroll{max-height:330px;overflow:auto}
footer{margin-top:22px;color:var(--dim);font-size:11.5px;line-height:1.7}
.dot{display:inline-block;width:7px;height:7px;border-radius:99px;background:var(--green);margin-right:6px}
</style></head><body><div class="wrap">
<header>
  <h1>CareerSim 实时监控台</h1>
  <span id="runpill" class="pill">加载中…</span>
  <span id="clock" class="pill"></span>
</header>
<div id="app"><div class="card empty">正在读取战报…</div></div>
<footer>
  <div><span class="dot"></span>每 4 秒自动刷新 · 只读，不会写任何游戏文件</div>
  <div id="srcpath" class="mono"></div>
</footer>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s);
const H=(s)=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function dur(s){if(s==null)return '—';const m=s/60;return m<1?s+' 秒':(m<60?m.toFixed(1)+' 分':(m/60).toFixed(1)+' 时');}
function tlbar(tl,cur,promos){
  let h='';
  for(let m=1;m<=48;m++){
    const p=promos.find(x=>x.month===m);
    let c='cell';
    if(m%6===0)c+=' review'; else if(m%3===0)c+=' sprint';
    if(m<cur)c+=' past';
    if(p)c+=' promo';
    if(m===cur)c+=' cur';
    h+=`<div class="${c}" title="M${m}${p?' 晋升 L'+p.to:''}">${p?'L'+p.to:(m%6===0?'R':'')}</div>`;
  }
  return `<div class="tl">${h}</div>
  <div style="font-size:11.5px;color:var(--dim);margin-top:6px">
  R=评审月(6的倍数) · 紫格=冲刺月(6k−3) · 蓝=已过 · <span style="color:#b45309">橙=当前</span> · 绿=晋升</div>`;
}
function energyStrip(list,curQ){
  let h='';
  for(const e of list){
    let c='cell';
    if(e.used>=3)c+=' e3'; else if(e.used>0)c+=' e12'; else if(e.open)c+=' e0';
    if(e.q===curQ)c+=' cur';
    if(e.under)c+=' und';
    const tip=`第 ${e.q} 季度：用 ${e.used}/3`+(e.picks&&e.picks.length?'（'+e.picks.join('、')+'）':'')
      +(e.src==='engine'?' · 来源=引擎日志':(e.src==='play'?' · 来源=战报渲染':' · 来源=energy 轨迹'))
      +(e.under?' · ⚠ 战报该季丢了部分选择行，数值已按 energy 轨迹校正':'')
      +(e.open?'':' · 窗口未到');
    h+=`<div class="${c}" title="${H(tip)}">${e.used}</div>`;
  }
  return `<div class="tl">${h}</div>
  <div style="font-size:11.5px;color:var(--dim);margin-top:6px">
  每格 = 一个季度，格内数字 = 该季实际用掉的体力点数 ·
  <span style="color:#059669">绿 3/3 用尽</span> · <span style="color:#b45309">橙 1–2</span> ·
  <span style="color:#dc2626">红 0（窗口已开却没用）</span>；灰格=该季行动窗口尚未到来 ·
  <b>虚线框</b>=该季 Agent 把多个体力行动<b>组合提交</b>，战报只渲染 1 条选择行，数值已按 energy 轨迹 / 引擎日志校正</div>`;
}
function gateHtml(g){
  if(!g||!g.items.length) return '<div class="empty">尚无状态快照</div>';
  let h='';
  for(const it of g.items){
    const over=it.overflow?' <span style="color:var(--violet);font-size:11px">已达截断上限，再投入被丢弃</span>':'';
    const m=it.margin;
    const col=m>=2?'var(--green)':(m>=0?'var(--amber)':'var(--red)');
    h+=`<div class="row">
      <div class="lab"><span>${H(it.name)} <span style="color:var(--dim)">门槛 ${it.need}</span></span>
      <span><b style="color:${col}">${it.cur}</b>
      <span style="color:var(--dim)"> · ${m>=0?'余量 +':'缺口 '}${m>=0?m:Math.abs(m)}</span></span></div>
      <div class="bar"><i style="width:${it.pct_need}%;background:${it.capped?'var(--violet)':'var(--blue)'}"></i>
      ${it.cap?`<u style="left:${Math.min(100,100*it.cap/Math.max(it.need,it.cap)/1)}%;display:none"></u>`:''}</div>
      <div style="font-size:11px;color:var(--dim)">截断上限 ${it.cap??'—'}${over}</div></div>`;
  }
  return h;
}
async function tick(){
  try{
    const r=await fetch('/api/state',{cache:'no-store'});
    const d=await r.json();
    render(d);
  }catch(e){ $('#runpill').className='pill err'; $('#runpill').textContent='连接中断'; }
}
function render(d){
  const rp=$('#runpill');
  if(d.run&&d.run.finished&&d.run.finished[1]==='DONE'){
    rp.className='pill done';
    rp.textContent='已完局'+(d.final?(' · '+d.final.grade+' 档 '+d.final.score+' 分'):'');
  }
  else if(d.run&&d.run.finished){rp.className='pill err';rp.textContent='结束：'+d.run.finished[1];}
  else {rp.className='pill run';rp.textContent='运行中';}
  $('#clock').textContent=d.now;
  $('#srcpath').textContent='战报源: '+(d.log_path||'—')+'  ·  '+(d.log_size/1024).toFixed(0)+' KB';
  const st=d.state||{}, p=d.phase||{}, g=d.gates||{};
  const lv=st.level, ph=p.code||'—';
  let h='';

  // ---- 纪律告警 ----
  if(d.alerts&&d.alerts.length){
    h+=`<div class="card" style="margin-bottom:14px"><h2>纪律告警</h2>`+
      d.alerts.map(a=>`<div class="al ${H(a.lv)}">${H(a.text)}</div>`).join('')+`</div>`;
  }

  // ---- 结局面板（仅完局后出现） ----
  if(d.final){
    const f=d.final;
    const dims=(f.dims||[]).map(x=>{
      const norm=x.weight?Math.min(100,x.weighted/x.weight):0;
      const col=norm>=90?'var(--green)':(norm>=60?'var(--blue)':(norm>=40?'var(--amber)':'var(--red)'));
      return `<div class="row"><div class="lab">
        <span>${H(x.label)} <span style="color:var(--dim)">权重 ${x.weight}</span></span>
        <span><b>${x.weighted}</b> <span style="color:var(--dim)">/ ${(x.weight*100).toFixed(0)}</span></span></div>
        <div class="bar"><i style="width:${norm}%;background:${col}"></i></div>
        <div style="font-size:11px;color:var(--dim)">raw ${x.raw} · 归一 ${norm.toFixed(1)}</div></div>`;
    }).join('');
    h+=`<div class="card" style="margin-bottom:14px"><h2>本局结局 · ${H(f.grade||'')} 档</h2>
      <div class="grid g2"><div>
        <div class="big">${f.score??'—'}<small>量化分</small></div>
        <div class="kv"><div>竞赛分<b>${f.competition??'—'}</b></div>
        <div>生存<b>${f.months??'—'} 月</b></div>
        <div>token<b>${(f.tokens||0).toLocaleString()}</b></div></div>
      </div><div>${dims}</div></div></div>`;
  }

  // ---- 顶部四块 ----
  h+=`<div class="grid g3" style="margin-bottom:14px">`;
  h+=`<div class="card"><h2>进度</h2>
      <div class="big">M${d.progress.month}<small>/ 48</small></div>
      <div class="bar" style="margin-top:10px"><i style="width:${d.progress.pct}%"></i></div>
      <div class="kv"><div>已用<b>${dur(d.elapsed)}</b></div>
      <div>预计剩余<b>${d.run.finished?'—':dur(d.eta)}</b></div>
      <div>本局<b>第 ${d.run.index??'-'}/${d.run.total??'-'} 局</b></div>
      ${d.run.arm?'<div>实验臂<b>'+H(d.run.arm)+'</b></div>':''}</div></div>`;
  h+=`<div class="card"><h2>当前状态</h2>
      <div class="big">L${lv??'—'}<small>${st.wealth!=null?('财富 '+st.wealth):''}</small></div>
      <div class="kv">
      <div>健康<b>${st.health??'—'}</b></div><div>尊严<b>${st.dignity??'—'}</b></div>
      <div>技能<b>${st.skill??'—'}</b></div><div>人脉<b>${st.network??'—'}</b></div>
      <div>产出<b>${st.output??'—'}</b></div><div>体力<b>${st.energy??'—'}</b></div></div></div>`;
  h+=`<div class="card"><h2>行动相位</h2>
      <div class="big">${H(ph)}</div>
      <div style="color:var(--dim);font-size:12.5px;margin-top:4px">${H(p.name||'')} · r = ${d.r??'—'}${d.r!=null?` · 距冲刺月 ${(3-d.r+6)%6} 月`:''}</div>
      <div class="hint" style="margin-top:10px">${H(p.hint||'')}</div></div>`;
  h+=`</div>`;

  // ---- 达标线 + 体力纪律 ----
  h+=`<div class="card" style="margin-bottom:14px"><h2>达标线缺口（目标 L${g.next_level??'—'}） · ${H(g.verdict||'')}</h2>
      <div class="grid g2"><div>${gateHtml(g)}</div><div>${tlbar(null,d.progress.month,d.level_timeline||[])}</div></div>
      <div style="border-top:1px solid var(--line);margin:14px 0 11px"></div>
      <h2>季度体力纪律（每季必须 3/3 用尽）</h2>${energyStrip(d.energy_by_quarter||[],d.energy_quarter)}
      </div>`;

  // ---- 事件三列 ----
  h+=`<div class="grid g3" style="margin-bottom:14px">`;
  const tl=(d.talk_seq||[]).map(x=>`<span class="tag ${x.tier}">M${x.month} ${x.tier==='good'?'好':x.tier==='average'?'中':'差'}</span>`).join('')||'<span class="empty">尚无谈话</span>';
  h+=`<div class="card"><h2>半年谈话档位</h2>${tl}
      <div style="font-size:11.5px;color:var(--dim);margin-top:8px">good ≥35 / average ≥20 / bad &lt;20；真实出局判据是「连续 2 次半年绩效 &lt;4」</div></div>`;
  const bs=(d.bonus_seq||[]).map(x=>`<span class="tag ${x.grade}">M${x.month} ${x.grade} ${x.amount>0?'+':''}${x.amount}</span>`).join('')||'<span class="empty">尚无奖金</span>';
  h+=`<div class="card"><h2>绩效奖金档位</h2>${bs}
      <div style="font-size:11.5px;color:var(--dim);margin-top:8px">S≈12 / A≈8 / B≈5 / C≈3（月薪系数 S3.0 A1.5 B0.5 C−1.0 D−2.0）</div></div>`;
  const rr=d.risks&&d.risks.length?d.risks[d.risks.length-1]:null;
  const cls=rr?(rr.level===0?'tag good':rr.level<=1?'tag average':'tag bad'):'';
  h+=`<div class="card"><h2>HR 风险读数</h2>
      <div class="risk">最新：${rr?`<span class="tag ${cls}">M${rr.month} ${H(rr.word)}（${H(rr.label)}，hidden_risk≈${rr.level}）</span>`:'尚无读数'}
      </div>
      <div style="font-size:11.5px;color:var(--dim);margin-top:8px">止损点在「皱着眉头」(≈2–3) 与「神情复杂」(≈4)；出现「生气」=5 当回合或下一回合爆雷</div></div>`;
  h+=`</div>`;

  // ---- 回合流 ----
  const rows=(d.turns||[]).slice().reverse().map(t=>`<tr>
    <td class="turn">#${t.turn}</td><td>${H(t.title)}</td>
    <td>${t.choice?'<span class="mono">'+H(t.choice)+'</span>':'<span style="color:var(--dim)">—</span>'}</td>
    <td style="color:var(--dim)">${H((t.reason||'').slice(0,120))}</td></tr>`).join('');
  h+=`<div class="card" style="margin-bottom:14px"><h2>最近回合（新→旧，最多 40）</h2>
      <div class="scroll"><table><thead><tr><th>回合</th><th>事件</th><th>选择</th><th>Agent 理由</th></tr></thead>
      <tbody>${rows||'<tr><td colspan=4 class="empty">尚无回合</td></tr>'}</tbody></table></div></div>`;

  // ---- 历史批次 ----
  const hd=d.history||[];
  const hrows=hd.slice(-14).reverse().map(x=>`<tr>
    <td class="mono">${H(x.run||x.run_dir||'')}</td><td class="n">${H(x.score||'')}</td>
    <td>${H(x.grade||'')}</td><td class="n">${H(x.months||'')}</td>
    <td class="n">${H(x.final_level||x.level||'')}</td>
    <td class="n">${H(x.raw_wealth||x.wealth||'')}</td>
    <td>${H(x.skill||'')}/${H(x.network||'')}/${H(x.output||'')}</td></tr>`).join('');
  h+=`<div class="card"><h2>历史批次成绩（各臂 results_*.tsv · 按 mtime · 末 14 条）</h2>
      <div class="scroll"><table><thead><tr><th>run</th><th>分</th><th>档</th><th>月</th><th>职级</th><th>财富</th><th>S/N/险</th></tr></thead>
      <tbody>${hrows||'<tr><td colspan=7 class="empty">尚无历史</td></tr>'}</tbody></table></div></div>`;

  $('#app').innerHTML=h;
}
tick(); setInterval(tick,4000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    fixed_run: str | None = None

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            try:
                data = build_state(self.fixed_run)
            except Exception as exc:  # noqa: BLE001
                data = {"error": repr(exc), "now": time.strftime("%F %T")}
            self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif path == "/api/health":
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # 静音访问日志
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="CareerSim 实时监控台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--run", default=None, help="固定显示的 run 目录名")
    ap.add_argument("--daemon", action="store_true",
                    help="脱离式后台启动（新会话 + 新进程组），不会被终端/工具调用回收")
    args = ap.parse_args()

    if args.daemon:
        # 与 analysis/launch_driver.py 同一套路：start_new_session=True 才是真正的脱离，
        # 单纯 nohup & 只忽略 SIGHUP、不改进程组，调用方结束时仍会被按进程组回收。
        import subprocess
        import sys
        cmd = [sys.executable, os.path.abspath(__file__),
               "--host", args.host, "--port", str(args.port)]
        if args.run:
            cmd += ["--run", args.run]
        logf = open(os.path.join(LOGDIR, "monitor.log"), "a", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"监控台已在后台启动 pid={proc.pid} → http://{args.host}:{args.port}")
        print(f"停止：pkill -f 'analysis/monitor.py'   日志：{os.path.join(LOGDIR, 'monitor.log')}")
        return 0

    Handler.fixed_run = args.run
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"无法绑定 {args.host}:{args.port} —— {exc}")
        print("端口可能已被占用：lsof -nP -iTCP:%d -sTCP:LISTEN" % args.port)
        return 1
    url = f"http://{args.host}:{args.port}"
    print(f"CareerSim 监控台已启动 → {url}")
    print(f"  战报目录: {LOGDIR}")
    print("  Ctrl-C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
