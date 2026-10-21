#!/usr/bin/env python3
"""通用队列器：等「指定的前一批 ab_driver」退出后，自动接着跑目标臂。

与 queue_v10.py 的区别：queue_v10.py 把前一批硬编码为 `ab_driver.py v9_wealthguard`，
只适用于那一次交接。本脚本把「前一批模式」也做成常量，但目标是任意臂（由环境变量给）。

为什么必须排队：
  引擎同一时刻只能有一局在跑。两个 ab_driver 并行时，各自的 wait_until_idle() 会在
  「前一批局间空闲」的瞬间互相抢跑，导致两臂交错、结果串味。

为什么前一批模式不能从 argv 传入：
  `pgrep -f <模式>` 会匹配到本脚本自己的命令行（因为 argv 里就带着这个模式）
  ⇒ 永远认为前一批还活着，队列永久阻塞。故本脚本把模式写成模块常量，
  自己的 cmdline 里不含它，再叠加一次 self-pid 过滤做双保险。

用法（后台）：
    QUEUE_ARM=v10c QUEUE_PREDECESSOR="ab_driver.py v10b" \
        .venv/bin/python3 analysis/queue_next.py 5
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("<PROJECT_ROOT>/CareerSim-BDCI26")
AB = REPO / "analysis" / "ab"
LOG = AB / "queue_next.log"
PY = REPO / ".venv" / "bin" / "python3"

ARM = os.environ.get("QUEUE_ARM", "v10c")
# ★ 缺省前一批：v10b（当前正在跑的那一批）。不接受 argv 覆盖（见模块 docstring）。
PREDECESSOR = os.environ.get("QUEUE_PREDECESSOR_INTERNAL", "ab_driver.py v10b")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def log(msg: str) -> None:
    line = time.strftime("[%F %T] ") + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def predecessor_alive() -> bool:
    """前一批 ab_driver 是否还活着（用 pgrep，本沙箱 ps 被拒）。"""
    try:
        out = subprocess.run(["pgrep", "-f", PREDECESSOR],
                             capture_output=True, text=True, timeout=15)
    except Exception:
        return False
    pids = [p for p in out.stdout.split() if p.isdigit()]
    pids = [p for p in pids if p != str(os.getpid())]
    return bool(pids)


def main() -> int:
    log(f"队列器启动：等待前一批（{PREDECESSOR}）退出，随后跑 {ARM}:{N}")
    waited = 0
    while predecessor_alive():
        if waited % 300 == 0:
            log(f"  前一批仍在跑 —— 已等待 {waited}s")
        time.sleep(20)
        waited += 20
    log(f"前一批已退出（累计等待 {waited}s），开始 {ARM}:{N}")

    cmd = ["caffeinate", "-dimsu", str(PY), "analysis/ab_driver.py", f"{ARM}:{N}"]
    log("exec: " + " ".join(cmd))
    with open(AB / "queue_next.out", "a", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=str(REPO),
                            stdout=fh, stderr=subprocess.STDOUT,
                            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"}).returncode
    log(f"{ARM}:{N} 批次结束 rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
