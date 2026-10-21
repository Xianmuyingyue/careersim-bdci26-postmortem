"""存活探针：每隔 15s 往 /tmp/probe_<TAG>.log 追加一行时间戳。

用于判定「脱离式后台进程在当前沙箱里到底能活多久」，以及
「清理发生在回合边界，还是发生在每次工具调用边界」。
"""
from __future__ import annotations

import datetime
import os
import time

TAG = os.environ.get("PROBE_TAG", "unknown")
PATH = f"/tmp/probe_{TAG}.log"


def main() -> None:
    for i in range(80):  # 80 * 15s = 20 min
        try:
            with open(PATH, "a", encoding="utf-8") as f:
                f.write(
                    f"{datetime.datetime.now():%H:%M:%S} tick={i} pid={os.getpid()} "
                    f"ppid={os.getppid()} sid={os.getsid(0)}\n"
                )
        except Exception:
            pass
        time.sleep(15)


if __name__ == "__main__":
    main()
