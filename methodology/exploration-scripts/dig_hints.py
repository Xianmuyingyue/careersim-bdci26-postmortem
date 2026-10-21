"""Dig implicit hints out of observe payloads.

The event narrative is the only channel through which the engine volunteers
state information it does not expose as a numeric field. This script clusters
repeated hint-bearing sentences so that fixed "tells" can be separated from
one-off flavour text.

Usage:
    python3 analysis/dig_hints.py [run_dir ...]
"""

from __future__ import annotations

import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_metrics import load_observe  # noqa: E402

REPO = "<PROJECT_ROOT>/CareerSim-BDCI26"
OUTROOT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")

SENT_RE = re.compile(r"[^。！？\n]{4,70}[。！？]")
# digits / level tokens normalised away so templates cluster
NORM_RE = re.compile(r"\d+")

HINT_KW = (
    # HR risk ladder (known)
    "笑着", "偷偷", "皱着眉头", "神情复杂", "生气",
    # risk vocabulary
    "风险", "埋雷", "隐患", "雷", "炸", "爆",
    # warning / pressure
    "提醒", "警告", "注意", "小心", "麻烦", "后果", "危险", "不太",
    # evaluation vocabulary
    "评估", "考核", "观察", "名单", "表现", "印象", "分寸", "底线",
    # relationship
    "关系", "得罪", "面子", "人情",
)


def run_dirs(argv: list[str]) -> list[str]:
    if len(argv) > 1:
        return argv[1:]
    return sorted(d for d in glob.glob(os.path.join(OUTROOT, "*"))
                  if os.path.isdir(d) and any(f.startswith("events-")
                                              for f in os.listdir(d)))


def main() -> int:
    dirs = run_dirs(sys.argv)
    print(f"扫描 {len(dirs)} 局\n")
    raw: collections.Counter = collections.Counter()
    norm: collections.Counter = collections.Counter()
    per_dir: dict[str, int] = {}

    for d in dirs:
        obs = load_observe(d)
        n = 0
        for o in obs:
            ev = o.get("events") or ""
            for s in SENT_RE.findall(ev):
                s = s.strip()
                if not any(k in s for k in HINT_KW):
                    continue
                raw[s] += 1
                norm[NORM_RE.sub("#", s)] += 1
                n += 1
        per_dir[os.path.basename(d)] = n

    print("每局命中句数：", per_dir)
    print(f"\n总命中 {sum(raw.values())} 句，去重后 {len(raw)} 句 / 模板 {len(norm)} 条\n")

    print("=== 高频模板（数字归一化，出现 ≥2 次）===")
    shown = 0
    for s, c in norm.most_common():
        if c < 2:
            break
        print(f"{c:3d}  {s}")
        shown += 1
        if shown >= 30:
            break
    if shown == 0:
        print("（无）")

    print("\n=== 仅出现 1 次的样例（前 12 句，属一次性文案）===")
    singles = [s for s, c in raw.most_common() if c == 1][:12]
    for s in singles:
        print(f"  1  {s}")
    if not singles:
        print("（无）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
