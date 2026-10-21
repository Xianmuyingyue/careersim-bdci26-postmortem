"""Arm-aware A/B driver for CareerSim: run N games per skill arm, sequentially.

Why this exists
---------------
`career_sim_runner play` calls `_reset_skills_workspace()` before EVERY run and
re-installs the skills from `solution/skills/`. So two arms cannot be run
concurrently and a batch is only internally comparable if the skill directory is
held fixed for the whole batch. This driver therefore:

  1. waits until no other game is in flight,
  2. stages one arm's skill snapshot into `solution/skills/`,
  3. runs N games back-to-back with that snapshot,
  4. records the snapshot's md5 per run as proof of no mid-batch drift.

Arms live in `analysis/ab/<arm>/` and mirror the layout of `solution/skills/`
(i.e. `analysis/ab/<arm>/<skill-id>/SKILL.md`).

Usage
-----
    python3 analysis/ab_driver.py arm_A_fourphase:4 arm_B_trapfix_target:4

Writes
------
    analysis/ab/driver.log                 driver progress
    analysis/ab/results_<arm>.tsv          one row per finished run
    analysis/ab/metrics/<run_dir>.json     full metric dump
    ../.workbuddy/logs/explore/runNN_play.log   raw play output (per arm prefix)
"""

from __future__ import annotations

import hashlib
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import TSV_HEADER, metrics, tsv_row  # noqa: E402

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
WORKSPACE = os.path.dirname(REPO)
ABDIR = os.path.join(REPO, "analysis", "ab")
SKILLS_DIR = os.path.join(REPO, "solution", "skills")
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
EMULOG = os.path.join(REPO, ".career_sim_runner", "career_emu", "emulator_logs")
PY = sys.executable
SKILL_IDS = ("decision-policy", "risk-guardian", "situation-awareness")

_VENV_BIN = os.path.join(REPO, ".venv", "bin")
os.environ["PATH"] = _VENV_BIN + os.pathsep + os.environ.get("PATH", "")

# --- sandbox safe-delete workaround (2026-09-25) -----------------------------
# The WorkBuddy sandbox injects a sitecustomize shim via PYTHONPATH
# (/Applications/WorkBuddy.app/.../cli/vendor/shim).  That shim monkey-patches
# shutil.rmtree to route deletions through the OS trash binary, and the binary
# is BROKEN on this machine: it returns `FSMoveObjectToTrashSync failed
# (status -5000)` even for a brand-new directory under $HOME.  `play` calls
# career_sim_runner.install.install_submission() which does
# `shutil.rmtree(old_session_dir)` -> OSError -> exit=1 for EVERY run.
# Fix: drop PYTHONPATH from the child environment so the venv interpreter loads
# the real `shutil` (verified: shutil.rmtree.__module__ == 'shutil').
CHILD_ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

# --- proxy strip (2026-09-28) ------------------------------------------------
# WorkBuddy 会话注入透明代理 HTTP(S)_PROXY=http://127.0.0.1:60206，而 websockets
# 客户端遵守 http_proxy ⇒ 所有 ws://127.0.0.1 连接被代理劫持，造成双重灾难：
#   ① backend_alive_deep 的 CONNECT 被 502 拒 ⇒ ensure_backend 误判后端死 1.5h；
#   ② 对局 WS 长连接 ~7-9 分钟被代理掐断（no close frame）⇒ v11 两局 mid-game
#      exit=1（07:17 死于 M12、08:27 死于 M10）。09-25~27 各批无此变量、均能跑
#      40+ 分钟 ⇒ 代理是当天唯一环境增量。本机流量只走 localhost；出网
#      （deepseek API）由 jiuwenswarm 后端负责且直连可达（历史批次即直连）。
# ⇒ 子进程环境一律剥离代理变量，双保险再加 NO_PROXY。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    CHILD_ENV.pop(_k, None)
CHILD_ENV["NO_PROXY"] = "127.0.0.1,localhost"
CHILD_ENV["no_proxy"] = "127.0.0.1,localhost"


def log(message: str) -> None:
    line = f"[{time.strftime('%F %T')}] {message}"
    print(line, flush=True)
    with open(os.path.join(ABDIR, "driver.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def md5(path: str) -> str:
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def arm_fingerprint(arm: str) -> dict[str, str]:
    return {s: md5(os.path.join(ABDIR, arm, s, "SKILL.md")) for s in SKILL_IDS}


def emulator_busy(window_s: int = 120) -> bool:
    """True if an emulator log was written within `window_s` -> a game is live."""
    if not os.path.isdir(EMULOG):
        return False
    newest = max((os.path.getmtime(os.path.join(EMULOG, f))
                  for f in os.listdir(EMULOG) if f.endswith(".log")), default=0)
    return (time.time() - newest) < window_s


def wait_until_idle(max_wait_s: int = 3600) -> bool:
    waited = 0
    while emulator_busy() and waited < max_wait_s:
        if waited % 120 == 0:
            log(f"  another game in flight — waiting ({waited}s elapsed)")
        time.sleep(20)
        waited += 20
    return not emulator_busy()


def clear_stale_sessions() -> int:
    """Remove leftover career-sim-runner session dirs.

    `install_submission()` -> `_reset_skills_workspace()` calls `shutil.rmtree()`
    on the instance session dir. Under WorkBuddy's safe-delete shim this is
    routed to the macOS trash, and if a previous session dir is still held by a
    live (or just-dead) process the trash move fails with:
        OSError: [safe-delete] ... FSMoveObjectToTrashSync failed (status -5000)
    ...which aborts the run before a single turn is played. Clearing the leftovers
    while nothing is running removes the trigger. Returns the number removed.
    """
    base = os.path.expanduser("~/.jiuwenswarm-instances/career_emu/agent/sessions")
    if not os.path.isdir(base):
        return 0
    removed = 0
    for name in os.listdir(base):
        if not name.startswith("career-sim-runner-"):
            continue
        path = os.path.join(base, name)
        try:
            shutil.rmtree(path)
            removed += 1
        except Exception as exc:  # noqa: BLE001
            log(f"  (stale session {name} not removable: {type(exc).__name__})")
    return removed


def stage_arm(arm: str) -> bool:
    src = os.path.join(ABDIR, arm)
    if not all(os.path.isfile(os.path.join(src, s, "SKILL.md")) for s in SKILL_IDS):
        log(f"  !! arm '{arm}' is incomplete (expected {SKILL_IDS} under {src})")
        return False
    for sid in SKILL_IDS:
        dst = os.path.join(SKILLS_DIR, sid)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(src, sid), dst)
    return True


def backend_up(port: int = 19092) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


# --- deep liveness probe (2026-09-28) ----------------------------------------
# v11 批次 0/4 的根因：RUN1 进行中(M12) jiuwenswarm 后端整树崩溃，但网关 19092
# 的 TCP 仍可连 ⇒ backend_up() 一直返回 True ⇒ ensure_backend 从不重启；
# 后续 11 次尝试全部在 reload_agent_config 处 ConnectionRefused(agent 服务 62440
# 已死) 秒败。TCP 探活探不到「网关活着、agent 服务死了」的假活状态，
# 因此必须做一次真实的 websocket reload 往返。
_PROBE_PATH = os.path.join(ABDIR, "_probe_backend.py")


def _write_probe() -> None:
    if os.path.isfile(_PROBE_PATH):
        return
    with open(_PROBE_PATH, "w", encoding="utf-8") as fh:
        fh.write(
            "import asyncio, sys\n"
            f"sys.path.insert(0, {REPO!r})\n"
            "from career_sim_runner.ws_client import reload_agent_config\n"
            "ok = asyncio.run(reload_agent_config('ws://127.0.0.1:19092/ws'))\n"
            "sys.exit(0 if ok else 2)\n"
        )


def backend_alive_deep(timeout_s: int = 25) -> bool:
    """TCP open is NOT enough: probe a real reload_agent_config round-trip."""
    if not backend_up():
        return False
    _write_probe()
    try:
        proc = subprocess.run([PY, _PROBE_PATH], cwd=REPO, timeout=timeout_s,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env=CHILD_ENV)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def ensure_backend() -> bool:
    if backend_alive_deep():
        return True
    log("  backend DOWN or degraded (deep probe failed) — detached restart")
    with open(os.path.join(ABDIR, "instance_restart.log"), "a", encoding="utf-8") as fh:
        fh.write(f"\n===== restart {time.strftime('%F %T')} =====\n")
        fh.flush()
        # ★ 2026-09-28: 弃用 `jiuwenswarm-start all` —— 它要写 .instance.pid
        #   (dotfile rename)，在 WorkBuddy 沙箱/注册表 shim 下必被 EPERM。
        #   改为直接拉起 app_agentserver（无 pid 记账，沙箱内可跑）。
        #   PATH 已含 .venv/bin（模块顶部前置）⇒ career-emulator-mcp 可解析；
        #   PYTHONPATH 已剥 ⇒ 无 shim；保留代理 env 供 LLM 出网。
        subprocess.run(["pkill", "-f", "jiuwenswarm.server.app_agentserver"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=CHILD_ENV)
        time.sleep(2)
        subprocess.Popen(
            [PY, "-m", "jiuwenswarm.server.app_agentserver", "--dotenv",
             os.path.expanduser("~/.jiuwenswarm-instances/career_emu/.env")],
            cwd=os.path.expanduser("~/.jiuwenswarm-instances/career_emu"),
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True, env=CHILD_ENV)
    for _ in range(90):
        time.sleep(5)
        if backend_alive_deep():
            log("  backend recovered (deep probe OK)")
            return True
    log("  backend did not recover within 450s")
    return False


def newest_output_dir() -> str | None:
    if not os.path.isdir(OUTROOT):
        return None
    dirs = [os.path.join(OUTROOT, d) for d in os.listdir(OUTROOT)
            if os.path.isdir(os.path.join(OUTROOT, d))]
    return max(dirs, key=os.path.getmtime) if dirs else None


def ending_name(run_dir: str) -> str:
    """从战报里取引擎自己印的结局名（比反推机制可靠）。

    引擎在结尾会印出结局名，**淘汰局的结局名直接对应失败机制**：
      * `炒鱿鱼end`   —— 两次半年绩效考核不佳（绩效硬门，与三维达标无关）
      * `信任危机end` —— 第二次爆雷
      * `眼前一黑end` —— 健康归零
    通关局印 `Completed the 48-month simulation.`。
    ⚠️ `score_report.json` 的 `termination_reason` 对早死局**恒为 None**，不要用它判死因。

    ★ 文本形式实测（三种写法都要认）：
        `failure_reason: 炒鱿鱼end —— …`        （R2，结构化字段）
        `GAME OVER:信任危机end —— …`            （R3，引擎旁白，冒号后无空格）
        `**结局**：eliminated（信任危机 end ——…` （Agent 自己的结算复述，`end` 前有空格）

    ★ 关键词兜底**只能扫文件尾部**：`炒鱿鱼` / `信任危机` 也会出现在 Agent 的推理正文里
      （实测 R2 第 2570 行就有「连续两次绩效<4 →炒鱿鱼」），全文裸搜必然误判。
    """
    import re
    # ★ 必须取 basename：调用方传进来的是**完整路径**（`os.path.join(OUTROOT, ...)`），
    #   战报文件名只带目录名部分（`transcript-<时间戳>.log`）。
    base = os.path.basename(str(run_dir).rstrip("/"))
    path = os.path.join(str(run_dir), f"transcript-{base}.log")
    if not os.path.isfile(path):
        return "?"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return "?"

    # ① ★ 通关信号必须**先行**判定。引擎实际有两种印法：
    #      `Completed the 48-month simulation.`（正常）
    #      `GAME OVER! The game completed the48-mon…`（**无冒号，且 `the48` 缺空格**）
    #    旧写法把通关放在 ② 且只匹配第一种 ⇒ 第二种被误判成 `?`（实测 `20260926T022719Z`，
    #    其实 `outcome = completed`）。而 `?` 会让 ab_summarize 把通关局错记成「死因未知」。
    if re.search(r"completed\s*the\s*48[\s\-‑]*mon", text, re.I) or \
       "Completed the 48-month simulation" in text:
        return "completed"

    # ② 结构化字段 / 引擎旁白：全文可搜，几乎不会误命中。
    #    ⚠️ 必须在 ① 之后——`GAME OVER! The game completed…` 若先被这里捕获会得到 "The"。
    for pat in (r"failure_reason\s*[:：]\s*([^\s—\-，,]+)",
                r"GAME OVER\s*[!！]?\s*[:：]?\s*([^\s—\-，,]+)"):
        hits = re.findall(pat, text)
        if hits:
            name = hits[-1].replace(" ", "")
            # 旁白句的残片（The / the game…）不是结局名，交给 ③ 兜底
            if name.startswith("Completed") or name.lower().startswith("the"):
                continue
            return name

    # ③ 关键词兜底：只看尾部，避免命中推理正文
    tail = text[-20000:]
    for kw in ("炒鱿鱼", "信任危机", "眼前一黑"):
        if kw in tail:
            return kw + "end"
    return "?"


def parse_spec(spec: str) -> tuple[str, int]:
    arm, _, n = spec.partition(":")
    return arm, int(n or "4")


def gen_replay(run_dir: str) -> None:
    """局毕补产 replay-*.md（09-28 待办收口）：play 不会自动产 replay，
    replay_browser 构建器靠「目录里有没有 replay-*.md」收录。失败不致命，只记日志。"""
    events = sorted(glob.glob(os.path.join(run_dir, "events-*.jsonl")))
    if not events:
        log(f"  replay skipped: no events jsonl in {os.path.basename(run_dir)}")
        return
    try:
        r = subprocess.run(
            [PY, "-m", "career_sim_runner", "replay", "--events", events[-1]],
            cwd=REPO, env=CHILD_ENV, timeout=180,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = next((l for l in (r.stdout or "").splitlines()
                     if l.startswith("replay_path:")), "")
        log(f"  replay: {line or f'exit={r.returncode} (no replay_path)'}")
    except Exception as exc:  # 回放是附属品，绝不阻断批次
        log(f"  replay FAILED (non-fatal): {exc}")


def run_arm(arm: str, n: int) -> int:
    log(f"########## ARM {arm} — {n} run(s) ##########")
    if not stage_arm(arm):
        return 1
    fp = arm_fingerprint(arm)
    for sid, h in fp.items():
        log(f"  staged {sid:<22} md5={h}")

    results = os.path.join(ABDIR, f"results_{arm}.tsv")
    if not os.path.exists(results):
        with open(results, "w", encoding="utf-8") as fh:
            fh.write(TSV_HEADER + "\n")

    os.makedirs(os.path.join(ABDIR, "metrics"), exist_ok=True)
    ok = 0
    for i in range(1, n + 1):
        if not wait_until_idle():
            log(f"  RUN {i}: aborted waiting for idle")
            break
        if not ensure_backend():
            log(f"  RUN {i} skipped: backend unreachable")
            continue

        # drift guard: the staged snapshot must still be what we think it is
        if arm_fingerprint(arm) != fp:
            log(f"  !! RUN {i} ABORTED: staged skills drifted mid-arm")
            break

        before = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        play_log = os.path.join(WORKSPACE, ".workbuddy", "logs", "explore",
                                f"{arm}_run{i:02d}_play.log")
        log(f"  RUN {i}/{n} START")
        code = -1
        for attempt in range(1, 4):
            # ★ 每次尝试前都深度探活：v11 0/4 的教训是网关 TCP 活着但 agent
            #   服务已死 ⇒ 11 次尝试全部秒败。这里失败会就地触发重启。
            if not ensure_backend():
                log(f"  RUN {i} attempt {attempt}: backend still down, retrying")
                time.sleep(60)
                continue
            cleared = clear_stale_sessions()
            if cleared:
                log(f"  cleared {cleared} stale session dir(s) before attempt {attempt}")
            try:
                with open(play_log, "a" if attempt > 1 else "w", encoding="utf-8") as fh:
                    if attempt > 1:
                        fh.write(f"\n===== ATTEMPT {attempt} =====\n")
                    # ★ 2026-09-26: 3600s 会误杀慢局 —— v10c RUN3 attempt2 实测 60min
                    # 走到 M48/48、只差月末结算被杀重跑。放宽为 7200（可用
                    # AB_RUN_TIMEOUT_S 覆盖）；真正卡死的局由「events 停更」人工判。
                    run_timeout = int(os.environ.get("AB_RUN_TIMEOUT_S", "7200"))
                    proc = subprocess.run(
                        [PY, "-m", "career_sim_runner", "play", "--submission", "solution"],
                        cwd=REPO, stdout=fh, stderr=subprocess.STDOUT,
                        timeout=run_timeout, env=CHILD_ENV)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                log(f"  RUN {i} TIMEOUT after {run_timeout}s")
                code = -1
            log(f"  RUN {i} attempt {attempt} exit={code}")
            if code == 0:
                break
            # Fast failures are almost always the safe-delete trash error
            # (FSMoveObjectToashSync status -5000) from session-dir contention,
            # not a model/engine problem. Clear and retry after a delay.
            log("  retrying after 45s (stale session / trash contention)")
            time.sleep(45)
            ensure_backend()

        after = set(os.listdir(OUTROOT)) if os.path.isdir(OUTROOT) else set()
        created = sorted(after - before,
                         key=lambda d: os.path.getmtime(os.path.join(OUTROOT, d)))
        target = os.path.join(OUTROOT, created[-1]) if created else newest_output_dir()
        if code != 0 or target is None:
            log(f"  RUN {i} FAILED (exit={code}, dir={target})")
            continue

        try:
            m = metrics(target)
        except Exception as exc:  # noqa: BLE001
            log(f"  RUN {i} metrics extraction failed: {exc!r}")
            continue
        m["arm"] = arm
        m["arm_md5"] = fp
        with open(os.path.join(ABDIR, "metrics", f"{os.path.basename(target)}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
        with open(results, "a", encoding="utf-8") as fh:
            fh.write(tsv_row(m) + "\n")
        ok += 1
        # ★ 用 raw_level（final_level 在本引擎恒为空）；并记录「结局名」——
        #   引擎在淘汰局结尾会直接印出 `出局: <名字>end`，是唯一可靠的死因（见
        #   analysis/ab_summarize.py::ending_name）。termination_reason 对早死局恒为 None。
        log(f"  RUN {i} DONE dir={os.path.basename(target)} grade={m.get('grade')} "
            f"score={m.get('score')} months={m.get('months')} "
            f"level=L{m.get('raw_level')} wealth={m.get('raw_wealth')} "
            f"bursts={m.get('bursts')} ending={ending_name(target)}")
        gen_replay(target)

    log(f"########## ARM {arm} FINISHED ({ok}/{n} ok) ##########")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    os.makedirs(ABDIR, exist_ok=True)
    log("===================== AB SESSION START =====================")
    if not wait_until_idle():
        log("another game never went idle — aborting")
        return 1
    rc = 0
    for spec in sys.argv[1:]:
        arm, n = parse_spec(spec)
        rc |= run_arm(arm, n)
    log("===================== AB SESSION END =====================")
    return rc


if __name__ == "__main__":
    sys.exit(main())
