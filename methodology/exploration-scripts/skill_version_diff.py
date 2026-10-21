#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_version_diff.py —— v3 / v8_3 / v10e 三版技能的结构化 diff。

用途：回答「技能膨胀 5.5× 到底是进步还是净负担」。
输出四张表：
  ① 章节骨架对照（## / ### 标题清单，标注 新增/删除/保留）
  ② 条款级新增（v10e 有、v3 无 的编号/表行，按文件分组）
  ③ 条款级删除（v3 有、v10e 无 —— 即「被稀释掉的激进条款」）
  ④ 段落级相似度：v3 的每个段落，在 v10e 里最相似的段落及相似度

数据源：
  v3   = analysis/_skillhist/v3/（从旧对局 events 还原）
  v8_3 = analysis/ab/v8_3/（臂目录仍在，权威）
  v10e = analysis/_skillhist/v10e/（从 v10e 对局 events 还原）
"""
from __future__ import annotations

import os
import re
import sys
import difflib
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = ("situation-awareness", "risk-guardian", "decision-policy")
SRC = {
    "v3":   os.path.join(REPO, "analysis", "_skillhist", "v3"),
    "v8_3": os.path.join(REPO, "analysis", "ab", "v8_3"),
    "v10e": os.path.join(REPO, "analysis", "_skillhist", "v10e"),
}
LABEL = {"v3": "v3 (13.1K)", "v8_3": "v8_3 (43.1K)", "v10e": "v10e (72.6K)"}


def read(ver: str, sk: str) -> str:
    p = os.path.join(SRC[ver], sk, "SKILL.md")
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def headings(txt: str):
    """返回 [(level, title)]，跳过代码块内。"""
    out, in_fence = [], False
    for line in txt.split("\n"):
        s = line.rstrip()
        if s.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{2,4})\s+(.*)$", s)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


def norm(s: str) -> str:
    """归一化：去加粗、去表格填充、去多余空白、全角标点统一。"""
    s = s.replace("**", "").replace("`", "")
    s = re.sub(r"\s+", "", s)
    return s.strip()


def clauses(txt: str):
    """条款级单位：表格数据行 + 有序/无序列表项（去表头分隔行）。"""
    out = []
    in_fence = False
    for line in txt.split("\n"):
        s = line.rstrip()
        if s.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        t = s.strip()
        if t.startswith("|") and not re.match(r"^\|[\s:\-|]+\|$", t):
            cells = [c.strip() for c in t.strip("|").split("|")]
            # 跳过纯表头（首列是「编号/维度/参数」之类）——用启发式：跳过含「---」的行已在上方
            out.append(("row", norm("|".join(cells))))
        elif re.match(r"^([-*+]|\d+[.)逐]|[①-⑳]|[（(]\d+[)）])\s*", t) and len(t) > 6:
            out.append(("li", norm(t)))
    return out


def paras(txt: str):
    out, buf, in_fence = [], [], False
    for line in txt.split("\n"):
        s = line.rstrip()
        if s.lstrip().startswith("```"):
            in_fence = not in_fence
        if not s.strip():
            if buf:
                out.append("\n".join(buf)); buf = []
            continue
        buf.append(s)
    if buf:
        out.append("\n".join(buf))
    return [p for p in out if not p.lstrip().startswith("#") and len(p) > 30]


def sec(title: str, ch: str = "=") -> None:
    print("\n" + ch * 78)
    print(title)
    print(ch * 78)


def main() -> None:
    V = ("v3", "v8_3", "v10e")
    T = {v: {sk: read(v, sk) for sk in SKILLS} for v in V}

    # ---------- ① 章节骨架 ----------
    sec("① 章节骨架对照（## 二级标题）")
    for sk in SKILLS:
        print(f"\n### {sk}")
        hs = {v: [t for lv, t in headings(T[v][sk]) if lv == 2] for v in V}
        base, now = hs["v3"], hs["v10e"]
        print(f"  v3 {len(base)} 个 → v10e {len(now)} 个   v8_3 {len(hs['v8_3'])} 个")
        nb = {norm(x) for x in base}
        for t in base:
            if norm(t) not in {norm(x) for x in now}:
                print(f"    [删] {t}")
        for t in now:
            if norm(t) not in nb:
                print(f"    [增] {t}")
        for t in now:
            if norm(t) in nb:
                pass  # 保留的太多，不逐一列

    # ---------- ② / ③ 条款级增删 ----------
    for tag, a, b in (("② v10e 新增条款（v3 中不存在）", "v3", "v10e"),
                      ("③ v3 条款在 v10e 中消失（被稀释/删除）", "v10e", "v3")):
        sec(tag)
        for sk in SKILLS:
            A = {norm(x[1]) for x in clauses(T[a][sk])}
            Bl = clauses(T[b][sk])
            added = [(k, c) for (k, c) in Bl if norm(c) not in A]
            # 过滤掉纯数字/极短噪声
            added = [(k, c) for (k, c) in added if len(c) > 12]
            print(f"\n### {sk} —— {len(added)} 条")
            for k, c in added[:40]:
                print(f"  [{k}] {c[:150]}")
            if len(added) > 40:
                print(f"  … 另有 {len(added)-40} 条")

    # ---------- ④ 段落相似度：v3 每段在 v10e 的最近邻 ----------
    sec("④ v3 段落在 v10e 中的最近邻（<0.60 视为「语义已丢失」）")
    for sk in SKILLS:
        print(f"\n### {sk}")
        P3, P10 = paras(T["v3"][sk]), paras(T["v10e"][sk])
        n3 = [norm(p) for p in P3]
        n10 = [norm(p) for p in P10]
        lost, kept = [], []
        for p, np_ in zip(P3, n3):
            best, bi = 0.0, -1
            for i, q in enumerate(n10):
                r = difflib.SequenceMatcher(None, np_, q).quick_ratio()
                if r > best:
                    best, bi = r, i
                if best > 0.95:
                    break
            (kept if best >= 0.60 else lost).append((best, p))
        if lost:
            print(f"  v3 {len(P3)} 段 → 保留 {len(kept)} / 丢失 {len(lost)}")
            for r, p in sorted(lost)[:12]:
                first = p.split("\n")[0][:110]
                print(f"    [{r:.2f}] {first}")

    # ---------- ⑤ 关键词计数（决定性指标） ----------
    sec("⑤ 关键词密度对照（每万字符出现次数）")
    KW = ["晋升", "职级", "申请关键项目", "岗位轮岗", "低调避险", "保留体力",
          "健康恢复", "MARGIN", "SPRINT", "SETTLE", "不得", "禁止", "必须",
          "例外", "门槛", "截断", "爆雷", "hidden", "风险", "余量"]
    print(f"  {'关键词':<16}" + "".join(f"{LABEL[v]:>14}" for v in V))
    for k in KW:
        row = f"  {k:<16}"
        for v in V:
            tot = sum(len(T[v][sk]) for sk in SKILLS)
            n = sum(T[v][sk].count(k) for sk in SKILLS)
            row += f"{n:>6} ({n/tot*1e4:>4.1f})"
        print(row)


if __name__ == "__main__":
    main()
