"""对照探针：与 probe_launch.py 相同，但外面包一层 `caffeinate -dimsu`。

如果 raw/clean 探针存活、而 caff 探针死亡，则说明 caffeinate 作为
session leader 时会把子进程一起带走（这就是 ab_driver 静默消失的根因）。
"""
from __future__ import annotations

import os
import subprocess

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
PY = os.path.join(REPO, ".venv", "bin", "python3")
PROBE = os.path.join(REPO, "analysis", "probe_survive.py")

env = dict(os.environ)
env["PROBE_TAG"] = "caff"
out = open("/tmp/probe_caff.out", "a", encoding="utf-8")
p = subprocess.Popen(
    ["caffeinate", "-dimsu", PY, PROBE],
    cwd=REPO,
    env=env,
    stdin=subprocess.DEVNULL,
    stdout=out,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(f"caff: pid={p.pid} sid={os.getsid(p.pid)}")
