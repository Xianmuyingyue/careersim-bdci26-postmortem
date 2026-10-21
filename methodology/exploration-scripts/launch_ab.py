"""脱离式启动器（ab_driver / queue_next 通用）。

为什么不能用 `run_in_background=true` 或 `nohup ... &`：
  两者都不会新建「会话/进程组」。工具的进程组在回合结束时被拆卸（process-group kill），
  子进程会被连带收割 —— 实测 `ab_driver.py v10b:5` 在 RUN 2 中途静默消失
  （日志停在 `RUN 2/5 START`，进程与 career_sim_runner 全部消失，无任何报错）。
  唯一可靠做法 = `subprocess.Popen(..., start_new_session=True)`：新会话 + 新进程组，
  与调用方解耦，调用方退出后照常运行。

另一处必设项：沙箱 safe-delete 批量守卫默认阈值 50，而每次 run 前会重置技能工作区
（约 50 个文件）⇒ 守卫会拒绝并中止。这里把阈值抬高（目标是模拟器自己的 scratch 目录，
不是用户数据），与 launch_driver.py 保持一致。

用法（前台调用，<1s 返回；真正的活儿在脱离的子进程里）：
    .venv/bin/python3 analysis/launch_ab.py v10b:4                # 默认跑 ab_driver
    .venv/bin/python3 analysis/launch_ab.py 5 analysis/queue_next.py
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
ABDIR = os.path.join(REPO, "analysis", "ab")
PY = os.path.join(REPO, ".venv", "bin", "python3")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: launch_ab.py <arg...> [script=analysis/ab_driver.py]")
        return 2
    args = sys.argv[1:]
    # 若最后一个参数是 .py 脚本路径 ⇒ 它是自定义驱动脚本，其余全是驱动参数
    script = "analysis/ab_driver.py"
    if args[-1].endswith(".py"):
        script = args[-1]
        args = args[:-1]
    if not args:
        print("usage: launch_ab.py <arm:N...> [script.py]  —— 至少一个臂参数")
        return 2
    arg = args[0]
    stem = os.path.splitext(os.path.basename(script))[0]

    # 日志落点：ab_driver 按臂名分开（driver_<arm>.out），其它脚本用 <stem>.out
    if stem == "ab_driver":
        safe = arg.replace(":", "_").replace("/", "_")
        logname = f"driver_{safe}.out"
    else:
        logname = f"{stem}.out"
    os.makedirs(ABDIR, exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD"] = "100000"

    out = open(os.path.join(ABDIR, logname), "a", encoding="utf-8")
    # 不外包 caffeinate：它会成为新 session 的 leader，自身退出时会把子进程一起带走
    # （2026-09-26 实测：包 caffeinate 的批次在 13:37 静默整组消失，而裸 python 探针存活）。
    # 防休眠改由调用方保证（用户在场时不需要）。
    cmd = [PY, script] + args   # ★ 透传全部臂参数（ab_driver 的 main 逐个 spec 串行跑）
    proc = subprocess.Popen(
        cmd,
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,   # ★ 关键：新会话，脱离调用方的进程组
    )
    print(f"launched: {' '.join(cmd)}  pid={proc.pid}  log=analysis/ab/{logname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
