#!/usr/bin/env python3
"""夜间自动连跑总控（无人值守）。

流程：
  1. 等待当前 v8_4 批次（2 局）结束；
  2. 以同一份技能快照建 v8_4b，连跑 5 局；
  3. 每局完成即写入 runs.jsonl（输入快照 / 输出指标 / 耗时 / 通过情况 / 异常）；
  4. 到 07:00 截止（或 5 局跑完）后生成 report.md 汇总报告。

所有原始数据与日志持久化在 analysis/night_run/。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path("<PROJECT_ROOT>/CareerSim-BDCI26")
AB = REPO / "analysis" / "ab"
OUT = REPO / "analysis" / "night_run"
OUT.mkdir(parents=True, exist_ok=True)
RUNS_LOG = OUT / "runs.jsonl"
CTRL_LOG = OUT / "controller.log"
REPORT = OUT / "report.md"
PY = REPO / ".venv" / "bin" / "python"
SKILLS = ["decision-policy", "risk-guardian", "situation-awareness"]

_dl = os.environ.get("NIGHT_DEADLINE")  # 形如 "07:55"，覆盖默认的 07:00
if _dl:
    _h, _m = [int(x) for x in _dl.split(":")]
    DEADLINE = datetime.now().replace(hour=_h, minute=_m, second=0, microsecond=0)
else:
    DEADLINE = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
if DEADLINE <= datetime.now():
    DEADLINE += timedelta(days=1)

TSV_HDR = ["run_dir", "session", "grade", "score", "months", "final_level", "raw_level",
           "raw_wealth", "raw_skill", "raw_network", "raw_risk_control", "raw_resilience",
           "bursts", "tokens", "level_path", "energy_actions", "main_actions",
           "talk_tiers", "hr_ladder"]


def log(msg):
    line = "[{}] {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(CTRL_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def md5_of(arm):
    out = {}
    for s in SKILLS:
        p = AB / arm / s / "SKILL.md"
        if p.exists():
            out[s] = hashlib.md5(p.read_bytes()).hexdigest()
    return out


def line_counts(arm):
    out = {}
    for s in SKILLS:
        p = AB / arm / s / "SKILL.md"
        if p.exists():
            out[s] = len(p.read_text(encoding="utf-8").splitlines())
    return out


def tsv_rows(arm):
    p = AB / "results_{}.tsv".format(arm)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("run_dir\t"):
            continue
        rows.append(dict(zip(TSV_HDR, line.split("\t"))))
    return rows


def driver_log():
    p = AB / "driver.log"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


def run_window(log_text, run_dir):
    """返回 (start_ts, done_ts, ending, 异常行列表)。

    ★ start 必须取「该 run 的 DONE 之前最近一次 RUN START」，
      否则会被同日志里后续局的 START 覆盖成未来时刻 ⇒ 算出负耗时（实测踩过）。
    """
    start = done = ending = None
    anomalies = []
    events = []          # [(ts, body)]
    for line in log_text.splitlines():
        m = re.match(r"\[([\d\-]+ [\d:]+)\]\s+(.*)", line)
        if m:
            events.append((m.group(1), m.group(2)))
    start_idx = None
    for i, (ts, body) in enumerate(events):
        if "dir={}".format(run_dir) in body and "DONE" in body:
            done = ts
            em = re.search(r"ending=(\S+)", body)
            if em:
                ending = em.group(1)
            # 回溯最近一次 RUN START（不得晚于 done）
            for j in range(i, -1, -1):
                b = events[j][1]
                if re.search(r"RUN\s+\d+/\d+\s+START", b) and events[j][0] <= ts:
                    start, start_idx = events[j][0], j
                    break
            break
    # 异常扫描范围 = 该局 START → DONE 的整个窗口（★ 重试/会话冲突行不含 run_dir，
    #   只按 run_dir 匹配会漏掉「attempt N exit=1 / stale session」⇒ 误判为策略失败）
    lo = start_idx if start_idx is not None else 0
    hi = next((i for i, (ts, b) in enumerate(events)
               if "dir={}".format(run_dir) in b and "DONE" in b), len(events))
    for ts, body in events[lo:hi + 1]:
        # 注：`cleared N stale session dir(s)` 是每局开跑前的例行清理，**不是**异常，必须排除，
        # 否则每一局都会被误判成"环境问题"。真正的异常 = retry / attempt exit≠0 / FAIL|ERROR|Traceback。
        if "cleared" in body and "stale session dir" in body:
            continue
        if re.search(r"FAIL|ERROR|Traceback|retry|attempt \d+ exit=[^0]", body):
            anomalies.append("[{}] {}".format(ts, body.strip()))
    return start, done, ending, anomalies


def minutes(a, b):
    try:
        fa = datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
        fb = datetime.strptime(b, "%Y-%m-%d %H:%M:%S")
        return round((fb - fa).total_seconds() / 60.0, 1)
    except Exception:
        return None


def record(arm, run_dir, row, input_sig):
    text = driver_log()
    start, done, ending, anomalies = run_window(text, run_dir)
    months = row.get("months", "")
    bursts = row.get("bursts", "")
    try:
        bursts_n = int(float(bursts))
    except Exception:
        bursts_n = 0
    passed = (months == "48")
    if bursts_n > 0:
        anomalies.append("爆雷 {} 次".format(bursts_n))
    if not passed:
        anomalies.append("未通关（{} 个月，结局 {}）".format(months, ending))
    rec = {
        "arm": arm,
        "run_dir": run_dir,
        "input": input_sig,
        "start": start,
        "done": done,
        "minutes": minutes(start, done) if (start and done) else None,
        "grade": row.get("grade"),
        "score": row.get("score"),
        "months": months,
        "level": row.get("raw_level"),
        "wealth": row.get("raw_wealth"),
        "skill": row.get("raw_skill"),
        "network": row.get("raw_network"),
        "risk_control": row.get("raw_risk_control"),
        "resilience": row.get("raw_resilience"),
        "bursts": bursts_n,
        "tokens": row.get("tokens"),
        "ending": ending,
        "passed": passed,
        "anomalies": anomalies,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log("记录 {} → 分数 {} / {} 级 / {} 月 / 爆雷 {} / {}".format(
        run_dir, rec["score"], rec["level"], months, bursts_n,
        "通过" if passed else "未通过"))
    return rec


def wait_arm_done(arm, expect_n, timeout_min=200):
    """等待某 arm 跑完 expect_n 局（或日志出现 FINISHED）。"""
    t0 = time.time()
    while time.time() - t0 < timeout_min * 60:
        if datetime.now() >= DEADLINE:
            log("已到 07:00 截止，停止等待 {}".format(arm))
            return False
        rows = tsv_rows(arm)
        text = driver_log()
        if len(rows) >= expect_n or "ARM {} FINISHED".format(arm) in text:
            log("{} 已完成 {}/{} 局".format(arm, len(rows), expect_n))
            return True
        time.sleep(30)
    log("等待 {} 超时".format(arm))
    return False


def already_recorded():
    """runs.jsonl 里已有的 run_dir 集合（防止重启总控后重复入库）。"""
    out = set()
    if RUNS_LOG.exists():
        for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.add(json.loads(line).get("run_dir"))
            except Exception:
                pass
    return out


def ingest_new(arm, seen, input_sig):
    """把新出现的局写入日志，返回 (更新后的 seen, 本次真正新写入的 run_dir 列表)。

    ★ 必须返回"新写入"列表而不是让调用方用 len(seen) 差值计算：
      seen 里会并入 already_recorded()（历史记录），用差值会把历史局算成本轮新局
      （实测踩过：一进来就判成"完成 7/2 局"）。
    """
    seen |= already_recorded()
    fresh = []
    for row in tsv_rows(arm):
        rd = row.get("run_dir")
        if rd and rd not in seen:
            record(arm, rd, row, input_sig)
            seen.add(rd)
            fresh.append(rd)
    return seen, fresh


def write_report(notes=""):
    recs = []
    if RUNS_LOG.exists():
        for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    total = len(recs)
    passed = sum(1 for r in recs if r.get("passed"))
    scores = [float(r["score"]) for r in recs if r.get("score") not in (None, "")]
    mins = [r["minutes"] for r in recs if r.get("minutes")]
    bursts = [r.get("bursts", 0) for r in recs]
    levels = [r.get("level") for r in recs]

    lines = []
    lines.append("# 夜间自动连跑汇总报告")
    lines.append("")
    lines.append("生成时间：{}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    lines.append("")
    lines.append("## 一、总体")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 测试局数 | {} |".format(total))
    lines.append("| 通过局数（48 个月通关） | {} |".format(passed))
    lines.append("| 通过率 | {}% |".format(round(100.0 * passed / total, 1) if total else 0))
    lines.append("| 平均分 | {} |".format(round(sum(scores) / len(scores), 2) if scores else "-"))
    lines.append("| 最高分 / 最低分 | {} / {} |".format(
        max(scores) if scores else "-", min(scores) if scores else "-"))
    lines.append("| 平均单局耗时（分钟） | {} |".format(
        round(sum(mins) / len(mins), 1) if mins else "-"))
    lines.append("| 总爆雷次数 | {} |".format(sum(bursts)))
    lines.append("")
    lines.append("## 二、逐局明细")
    lines.append("")
    lines.append("| # | run_dir | 起止 | 耗时(分) | 评级 | 分数 | 月数 | 职级 | 财富 | 爆雷 | 结局 | 通过 | 异常 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(recs, 1):
        lines.append("| {} | {} | {} → {} | {} | {} | {} | {} | L{} | {} | {} | {} | {} | {} |".format(
            i, r.get("run_dir"), (r.get("start") or "-")[11:16], (r.get("done") or "-")[11:16],
            r.get("minutes") or "-", r.get("grade"), r.get("score"), r.get("months"),
            r.get("level"), r.get("wealth"), r.get("bursts"), r.get("ending") or "-",
            "是" if r.get("passed") else "否",
            "；".join(r.get("anomalies") or []) or "无"))
    lines.append("")
    lines.append("## 三、输入（技能快照）")
    lines.append("")
    # ★ 一个批次一套快照：按 arm 分组列出，不要只取 recs[0]
    by_arm = {}
    for r in recs:
        by_arm.setdefault(r.get("arm"), r.get("input") or {})
    for arm in sorted(by_arm):
        sig = by_arm[arm]
        lines.append("**批次 `{}`**".format(arm))
        lines.append("")
        lines.append("| 技能 | md5 |")
        lines.append("|---|---|")
        for k, v in (sig.get("md5") or {}).items():
            lines.append("| {} | {} |".format(k, v))
        lines.append("")
        lines.append("技能行数：{}".format(sig.get("lines")))
        lines.append("")
    lines.append("")
    lines.append("## 四、发现的问题")
    lines.append("")
    INFRA = re.compile(r"retry|stale session|trash contention|attempt \d+ exit=[^0]|FAIL|ERROR|Traceback")
    probs, real_deaths, infra = [], [], []
    for r in recs:
        if r.get("passed"):
            for a in (r.get("anomalies") or []):
                probs.append("{}（通关）：{}".format(r.get("run_dir"), a))
            continue
        hits = [a for a in (r.get("anomalies") or []) if INFRA.search(a)]
        if hits:
            infra.append(r)
            probs.append("{}（{} 个月，结局 {}）：**疑似环境问题，非策略失败** —— {}".format(
                r.get("run_dir"), r.get("months"), r.get("ending"),
                "；".join(hits[:3])))
        else:
            real_deaths.append(r)
            probs.append("{}（{} 个月，结局 {}）：**真实早死**".format(
                r.get("run_dir"), r.get("months"), r.get("ending")))
    if probs:
        for p in probs:
            lines.append("- {}".format(p))
    else:
        lines.append("- 全部局未发现异常（无早死、无爆雷、无引擎报错）")
    if infra or real_deaths:
        valid = [r for r in recs if r not in infra]
        vs = [float(r["score"]) for r in valid if r.get("score") not in (None, "")]
        lines.append("")
        lines.append("**判定口径**：早死局若在 START→DONE 窗口内出现 `retry` / `stale session` / "
                     "`trash contention` / `attempt N exit≠0`，归为**环境问题**（引擎会话被回收站冲突打断，"
                     "该局数据不可用），不计入策略失败；否则为**真实早死**。")
        lines.append("")
        lines.append("| 口径 | 局数 | 真实早死 | 平均分 |")
        lines.append("|---|---|---|---|")
        all_s = [float(r["score"]) for r in recs if r.get("score") not in (None, "")]
        lines.append("| 全部记录 | {} | {} | {} |".format(
            len(recs), len(real_deaths),
            round(sum(all_s) / len(all_s), 2) if all_s else "-"))
        lines.append("| **剔除环境问题局** | {} | {} | **{}** |".format(
            len(valid), len(real_deaths),
            round(sum(vs) / len(vs), 2) if vs else "-"))
    if notes:
        lines.append("")
        lines.append("## 五、备注")
        lines.append("")
        lines.append(notes)
    lines.append("")
    lines.append("## 六、原始数据位置")
    lines.append("")
    lines.append("- 逐局结构化日志：`analysis/night_run/runs.jsonl`")
    lines.append("- 总控日志：`analysis/night_run/controller.log`")
    arms = sorted({r.get("arm") for r in recs if r.get("arm")})
    lines.append("- 批次结果：{}".format(
        "、".join("`analysis/ab/results_{}.tsv`".format(a) for a in arms) or "-"))
    lines.append("- 驱动日志：`analysis/ab/driver.log`")
    lines.append("- 每局原始产物：`.career_sim_runner/career_emu/outputs/九问/<run_dir>/`")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log("报告已生成：{}".format(REPORT))


def main():
    # 用法：night_run.py <arm> [n]   （不传 arm 则走旧默认：先等 v8_4 再跑 v8_4b:5）
    arm = sys.argv[1] if len(sys.argv) > 1 else None
    expect_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    log("=== 夜间总控启动 ===")
    log("截止时间：{}".format(DEADLINE.strftime("%Y-%m-%d %H:%M:%S")))
    src_arm = arm or "v8_4"
    input_sig = {"md5": md5_of(src_arm), "lines": line_counts(src_arm), "arm": arm or "v8_4/v8_4b"}
    log("输入快照 md5：{}".format(json.dumps(input_sig["md5"], ensure_ascii=False)))

    seen = set()

    if arm is None:
        # 阶段 1：等待当前 v8_4（2 局）
        log("阶段 1：等待 v8_4 当前批次结束")
        wait_arm_done("v8_4", 2)
        seen, _ = ingest_new("v8_4", seen, input_sig)
        log("v8_4 入库 {} 局".format(len(seen)))
        run_arm, dst = "v8_4b", AB / "v8_4b"
        if not dst.exists():
            shutil.copytree(AB / "v8_4", dst)
    else:
        run_arm = arm
        log("跳过阶段 1（arm 已指定 = {}）".format(arm))

    # 阶段 2：启动目标 arm 连跑 N 局
    if datetime.now() < DEADLINE:
        log("阶段 2：启动 {} 连跑 {} 局".format(run_arm, expect_n))
        proc = subprocess.Popen(
            [str(PY), "analysis/ab_driver.py", "{}:{}".format(run_arm, expect_n)],
            cwd=str(REPO),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        log("{} 子进程 pid={}".format(run_arm, proc.pid))
    else:
        proc = None
        log("已过截止时间，跳过阶段 2")

    # 阶段 3：轮询直到「本轮新入库 N 局」或到截止时间
    # ★ 不能用 len(tsv_rows) >= N 判完成：补跑时 tsv 里已有上一批的局，会立刻误判并杀掉子进程
    #   （实测踩过：06:36 判成"已完成 5/2 局"，子进程刚起就被 terminate）。
    log("阶段 3：监控中")
    n_new = 0
    while True:
        if datetime.now() >= DEADLINE:
            log("到达截止 {}，停止监控".format(DEADLINE.strftime("%H:%M")))
            break
        seen, fresh = ingest_new(run_arm, seen, input_sig)
        n_new += len(fresh)
        if n_new >= expect_n:
            log("{} 本轮已完成 {}/{} 局".format(run_arm, n_new, expect_n))
            break
        if proc is not None and proc.poll() is not None and len(rows) >= 1:
            if "ARM {} FINISHED".format(run_arm) in driver_log():
                log("{} 批次结束".format(run_arm))
                break
        time.sleep(45)

    if proc is not None and proc.poll() is None:
        log("仍在运行的子进程将被终止（已到截止时间）")
        try:
            proc.terminate()
        except Exception:
            pass

    # 收尾：再抓一次，确保无遗漏
    seen, _ = ingest_new(run_arm, seen, input_sig)
    write_report("无人值守自动执行；批次 `{}` 连跑 {} 局，截止 {} 收尾。"
                 "全程未改任何技能策略数值与逻辑。".format(
                     run_arm, expect_n, DEADLINE.strftime("%H:%M")))
    log("=== 夜间总控结束 ===")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        # 兜底：只根据已落盘的 runs.jsonl 重新出报告
        log("收到 report 指令，直接汇总现有日志")
        write_report("由 finalize 指令生成（依据已落盘的 runs.jsonl）。")
        sys.exit(0)
    try:
        main()
    except Exception as exc:  # 任何异常都要留痕并出报告
        log("总控异常：{!r}".format(exc))
        try:
            write_report("总控异常收尾：{!r}".format(exc))
        except Exception:
            pass
        sys.exit(1)
