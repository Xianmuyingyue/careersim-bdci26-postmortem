"""起两个存活探针，对比 env 策略：

  raw   — 原样继承当前环境（含 CODEBUDDY_* / sandbox broker 变量）
  clean — 剔除 CODEBUDDY_* / CLAUDE_* / TRACEPARENT / BAGGAGE

两者都 start_new_session=True。用途：判定沙箱是按「进程组」还是按
「会话 ID 环境变量」追踪并收割脱离进程。
"""
from __future__ import annotations

import os
import subprocess

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
PY = os.path.join(REPO, ".venv", "bin", "python3")
PROBE = os.path.join(REPO, "analysis", "probe_survive.py")

STRIP_PREFIX = ("CODEBUDDY_", "CLAUDE_")
STRIP_EXACT = ("TRACEPARENT", "BAGGAGE")


def launch(tag: str, clean: bool) -> int:
    env = dict(os.environ)
    if clean:
        for k in list(env):
            if k.startswith(STRIP_PREFIX) or k in STRIP_EXACT:
                env.pop(k, None)
    env["PROBE_TAG"] = tag
    out = open(f"/tmp/probe_{tag}.out", "a", encoding="utf-8")
    p = subprocess.Popen(
        [PY, PROBE],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"{tag}: pid={p.pid} sid={os.getsid(p.pid)}")
    return p.pid


if __name__ == "__main__":
    launch("raw", clean=False)
    launch("clean", clean=True)
