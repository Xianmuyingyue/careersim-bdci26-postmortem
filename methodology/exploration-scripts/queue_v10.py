#!/usr/bin/env python3
"""队列器：等 v9_wealthguard 批次进程退出后，自动接着跑 v10 批次。

为什么要排队而不是直接起第二个 ab_driver：
  引擎同一时刻只能有一局在跑。两个 ab_driver 并行时，各自的 wait_until_idle()
  会在「前一批局间空闲」的瞬间互相抢跑，导致两臂交错、结果串味。
  ⇒ 必须等前一批进程真正退出，再起下一批。

为什么不在 v9 批次中途改 solution/skills：
  `play` 每次运行前都会 `_reset_skills_workspace()` 并从 `solution/skills/` 重装技能。
  ab_driver 的 drift guard 只比对「arm 快照自身」，**不监视 solution/skills**
  ⇒ 中途改 solution/skills 会静默污染后续 run（标签仍是旧 arm）。
  本脚本因此在启动 v10 前不碰 solution/skills —— ab_driver 的 stage_arm('v10')
  会自己把 analysis/ab/v10/ 复制过去。

用法（后台）：
    .venv/bin/python3 analysis/queue_v10.py [n]
默认 n = 4。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("<PROJECT_ROOT>/CareerSim-BDCI26")
AB = REPO / "analysis" / "ab"
LOG = AB / "queue_v10.log"
PY = REPO / ".venv" / "bin" / "python3"
ARM = os.environ.get("QUEUE_ARM", "v10")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
PREDECESSOR = "ab_driver.py v9_wealthguard"


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
    # 排除自身（本脚本 cmdline 不含 PREDECESSOR，但仍做防御）
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

    # 起 ab_driver（它会自己 stage_arm(ARM) 并做 wait_until_idle）
    cmd = ["caffeinate", "-dimsu", str(PY), "analysis/ab_driver.py", f"{ARM}:{N}"]
    log("exec: " + " ".join(cmd))
    with open(AB / "queue_v10.out", "a", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=str(REPO),
                            stdout=fh, stderr=subprocess.STDOUT,
                            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"}).returncode
    log(f"{ARM}:{N} 批次结束 rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
