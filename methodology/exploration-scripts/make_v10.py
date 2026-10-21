#!/usr/bin/env python3
"""v10 快照 = 当前 solution/skills 的冻结副本（目标/红线二分 + 删除财富平衡项 + perf 立为第二目标）。

与 v8_5 的关系：v8_5 是「v8_3 的合规泛化版」（make_v8_5.py）。v10 是一次整块重写，
   因此本脚本不再做批量正则替换，只做两件事：
     1) 把当前 solution/skills 原样冻结到 analysis/ab/v10/（唯一可信时间轴）；
     2) 用比 v8_5 更严的 BAD 正则校验「引擎内部引用」已清零
        （v8_5 的 BAD 放过 `*_conditions`；v10 把它们也纳入检查）。

只读 solution/skills，写 analysis/ab/v10。不改任何策略数值与逻辑。
"""
import re
import shutil
import hashlib
from pathlib import Path

ROOT = Path("<PROJECT_ROOT>/CareerSim-BDCI26")
SRC = ROOT / "solution" / "skills"
DST = ROOT / "analysis" / "ab" / "v10"
SKILLS = ["decision-policy", "risk-guardian", "situation-awareness"]

if DST.exists():
    shutil.rmtree(DST)
DST.mkdir(parents=True)
(DST / ".gitkeep").write_text("", encoding="utf-8")
for s in SKILLS:
    (DST / s).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / s / "SKILL.md", DST / s / "SKILL.md")

# 严格版 BAD：v8_5 的集合 + *_conditions / config 键 / snake 函数调用
BAD = re.compile(
    r"\.py\b|\.data\b|\.json\b|config\.|::|源码|写死"
    r"|promotion_conditions|salary_conditions|optional_conditions"
    r"|_on_month_advanced|apply_delta|apply_level_delta|_evaluate_failure_conditions"
    r"|wealth_scale|streak_tracking|min_duration_in_level|rapid_promotion|increment_when|trigger_condition"
)
# 白名单：可观察输入字段（agent 必须读的 API，非引擎内部符号）
ALLOW = re.compile(r"^(current_state|current_event|simulation_flags|status|time)\.")

print("=== v10 快照生成 ===")
rows = []
for s in SKILLS:
    src = SRC / s / "SKILL.md"
    dst = DST / s / "SKILL.md"
    a, b = hashlib.md5(src.read_bytes()).hexdigest(), hashlib.md5(dst.read_bytes()).hexdigest()
    rows.append((s, len(src.read_text(encoding="utf-8").splitlines()), a, b, a == b))
for s, n, a, b, ok in rows:
    print("  {:<22} {:>4} 行  md5={}  {}  {}".format(s, n, a[:8], "冻结一致" if ok else "!! 不一致", "OK" if ok else "FAIL"))
print("  合计 =", sum(r[1] for r in rows), "行  |  冻结一致性 =", "PASS" if all(r[4] for r in rows) else "FAIL")

print("=== 引擎内部引用残留检查（严格版）===")
leftover = []
for s in SKILLS:
    for i, line in enumerate((DST / s / "SKILL.md").read_text(encoding="utf-8").splitlines(), 1):
        for m in BAD.finditer(line):
            if ALLOW.match(m.group(0)):
                continue
            leftover.append((s, i, m.group(0), line.strip()[:110]))
if leftover:
    for s, i, sym, line in leftover:
        print("  !! {} : {} : [{}] {}".format(s, i, sym, line))
else:
    print("  无残留（.py/.data/.json/config./::/源码/写死/*_conditions/引擎函数名/配置键 全部清除）")

print("=== 契约校验 ===")
ok_all = True
for s in SKILLS:
    L = (DST / s / "SKILL.md").read_text(encoding="utf-8").splitlines()
    fm_end = next((i for i, x in enumerate(L[1:], 1) if x.strip() == "---"), -1)
    fm = "\n".join(L[1:fm_end]) if fm_end > 0 else ""
    nm = re.search(r"^name:\s*(\S.*)$", fm, re.M)
    ds = re.search(r"^description:\s*(\S.*)$", fm, re.M)
    good = L[0].strip() == "---" and fm_end > 0 and bool(nm) and bool(ds and len(ds.group(1)) > 20)
    ok_all &= good
    print("  {:<22} {}".format(s, "PASS" if good else "FAIL"))
print("  契约 =", "PASS" if ok_all else "FAIL")
