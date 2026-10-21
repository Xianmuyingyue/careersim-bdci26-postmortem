#!/usr/bin/env python3
"""让当前 A/B 批次跑完指定 RUN 后立即停止（不进入下一局）。

## 为什么需要
`ab_driver.py` 在每局 DONE 之后会**立刻**进入下一局，人工来不及中断。
但它 DONE 与下一个 `RUN i START` 之间会调 `wait_until_idle()`，
而该函数的判据是「emulator 日志 **120 秒**内无写入」⇒ **DONE 之后有约 100s 的可中断窗口**。
本脚本就卡在这个窗口里杀进程，从而「跑完第 N 局就停」。

## 为什么不直接杀驱动
`ab_driver` 的顺序是：**先写 `results_<arm>.tsv` 行 → 再打印 `RUN i DONE`**。
⇒ 只要监控到 `RUN i DONE`，该局数据**已经落盘**，此时杀驱动不会丢数据。
（若提前杀，则该局的 TSV 行与 metrics json 都不会生成 —— 只能用
 `run_metrics.py` 从 run 目录离线补，麻烦且易错。）

## 用法
    analysis/stop_after.py <RUN序号> [臂名子串]
    # 例：跑完 v10 的 RUN 1 就停
    analysis/stop_after.py 1 v10

**必须用 `run_in_background=true` 启动**：`nohup ... &` 在工具调用返回后会被沙箱按进程组回收。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("<PROJECT_ROOT>/CareerSim-BDCI26")
LOG = REPO / "analysis" / "ab" / "driver.log"
OUT = REPO / "analysis" / "ab" / "stop_after.log"


def log(msg: str) -> None:
    line = time.strftime("[%F %T] ") + msg
    print(line, flush=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    n = int(sys.argv[1])
    arm = sys.argv[2] if len(sys.argv) > 2 else ""

    # ★ 基线行号：driver.log 跨批次追加，历史批次的同名行会让匹配立刻误判
    lines_all = LOG.read_text(encoding="utf-8", errors="replace").splitlines() \
        if LOG.exists() else []
    base = len(lines_all)

    # ★★ 臂名必须在「全文件」里解，不能在基线之后的尾部解 ——
    # `########## ARM <name> ——` 这一行出现在**批次开始时**，即**基线之前**，
    # 在尾部永远找不到它，会让臂校验恒为 "?" 而永不触发（2026-09-26 踩过）
    hits_arm = re.findall(r"#{5,}\s*ARM\s+([A-Za-z0-9_.\-]+)", "\n".join(lines_all))
    cur = hits_arm[-1] if hits_arm else "?"
    if arm and arm not in cur:
        log(f"✗ 当前在跑的是 {cur}，不是 {arm} ⇒ 立即退出（避免杀错批次）")
        return 3

    pat = re.compile(r"RUN\s+%d\s+(DONE|FAILED|TIMEOUT)" % n)
    log(f"待命：等 {cur} 的 RUN {n} 结束（基线行号={base}）")

    deadline = time.time() + 3 * 3600
    while time.time() < deadline:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[base:]
        hit = next((l for l in lines if pat.search(l)), None)
        if hit:
            log(f"命中：{hit.strip()}")
            log(f"  臂={cur} ⇒ RUN {n} 数据已落盘，现在杀掉驱动与队列（不进入 RUN {n+1}）")
            for sig in (["pkill", "-f", "analysis/ab_driver.py"],
                        ["pkill", "-f", "queue_v10.py"]):
                r = subprocess.run(sig, capture_output=True, text=True)
                log(f"  {' '.join(sig)} -> rc={r.returncode}")
            time.sleep(3)
            r = subprocess.run(["pgrep", "-lf", "ab_driver.py|queue_v10.py"],
                              capture_output=True, text=True)
            alive = [x for x in r.stdout.splitlines() if x.strip()]
            log(f"  残留进程：{alive if alive else '无 ✓'}")
            log("完成：批次已在指定 RUN 后停止。")
            return 0
        time.sleep(10)

    log("超时（3 小时）未等到目标 RUN，放弃。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
