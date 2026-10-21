#!/usr/bin/env python3
"""盘点 outputs 目录：哪些是「真对局」、哪些已进回放浏览器、哪些是必须排除的半成品。

用途（每次跑完批次、要更新 replay_browser.html 之前必做一次）：
    1. 找出**真对局**的目录（补 replay 只能补给它们）
    2. 找出**半成品**目录（绝不能补 replay，否则脏数据混进对比）
    3. 找出「真对局但未入包」的目录（说明构建器的 BATCHES 漏了）

真对局判据（两条必须成立，外加一条防空壳检查）：
    · `score_report.json` 存在且 `play_exit_code == 0`
    · `ending_score.quantitative_score` 非空
    · events 里 `mcp_career-emulator_observe` 与 `mcp_career-emulator_take_action` **各 ≥ 1 次**
      ⚠️ **不要用「≥50 次」当判据**：早死短局（`E` 档、十几到三十几次 observe）是**合法对局**，
         例如 `20260924T173408Z`（obs 23）、`20260926T204818Z`（obs 10）都在浏览器里。
         真正的"假对局"是**根本没有 observe/take_action**（工具调用只有 bash/file/grep），
         例如 `20260926T120028Z` —— 它的 replay 已被移到 `analysis/ab/_excluded_replays/`。
    · 另附「疑似空壳」告警：`obs < 15` 时打印出来人工确认（可能只是极短局，也可能被误算）。

⚠️ 字段名易踩坑：
    · `score_report.json` 里的分数是 **`ending_score.quantitative_score`**（`ending_score` 是个字典，
      不是标量；顶层没有 `quantitative_score`）
    · events 的工具名是 **`mcp_career-emulator_observe` / `mcp_career-emulator_take_action`**，
      直接数字符串 `"observe"` 会得到 0（因此不要用 `txt.count('"observe"')` 判真伪）
    · 构建器的收录判据只有两条：**有 `replay-*.md`** 且 **`load_score()` 能取到 score**

用法：
    .venv/bin/python3 analysis/scan_real_runs.py
    .venv/bin/python3 analysis/scan_real_runs.py --arm 20260927      # 只看某天
"""
import argparse
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
BUILDER = os.path.join(REPO, "analysis", "build_replay_html.py")
EXCLUDED = os.path.join(REPO, "analysis", "ab", "_excluded_replays")

OBSERVE_TOOL = "mcp_career-emulator_observe"
TAKE_TOOL = "mcp_career-emulator_take_action"


def packed_dirs():
    """构建器 BATCHES + HISTORIC 里已列出的目录名。"""
    t = open(BUILDER, encoding="utf-8").read()
    i = t.find("BATCHES = [")
    j = t.find("HISTORIC")
    names = set(re.findall(r'"(\d{8}T\d{6}Z)"', t[i:]))
    names |= set(re.findall(r'"(\d{8}T\d{6}Z)"', t[j:j + 2500]))
    return names


def inspect(name):
    d = os.path.join(OUT, name)
    files = os.listdir(d)
    ev = [f for f in files if f.startswith("events-")]
    replay = [f for f in files if f.startswith("replay-")]
    excluded = os.path.exists(os.path.join(EXCLUDED, "replay-%s.md" % name))

    code = quant = outcome = months = None
    session = None
    report = os.path.join(d, "score_report.json")
    if os.path.exists(report):
        try:
            payload = json.load(open(report, encoding="utf-8"))
            code = payload.get("play_exit_code")
            session = payload.get("session_id")
            ending = payload.get("ending_score") or {}
            quant = ending.get("quantitative_score")
            outcome = ending.get("outcome")
            months = ending.get("survival_months")
        except Exception:
            pass

    nobs = ntake = 0
    evkb = 0
    if ev:
        path = os.path.join(d, ev[0])
        evkb = os.path.getsize(path) // 1024
        tools = {}
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                tc = (obj.get("payload") or {}).get("tool_call") or {}
                tn = tc.get("name")
                if tn:
                    tools[tn] = tools.get(tn, 0) + 1
        nobs = tools.get(OBSERVE_TOOL, 0)
        ntake = tools.get(TAKE_TOOL, 0)

    real = (code == 0) and quant is not None and nobs >= 1 and ntake >= 1
    return dict(name=name, has_ev=bool(ev), has_replay=bool(replay), excluded=excluded,
                exit_code=code, quant=quant, outcome=outcome, months=months,
                session=session, evkb=evkb, obs=nobs, tak=ntake, real=real)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default=None, help="只显示目录名包含该前缀的项，例如 20260927")
    args = ap.parse_args()

    known = packed_dirs()
    rows = []
    for name in sorted(os.listdir(OUT)):
        if not os.path.isdir(os.path.join(OUT, name)):
            continue
        if args.arm and not name.startswith(args.arm):
            continue
        rows.append(inspect(name))

    print("已收录目录数 =", len(known))
    print("%-18s%4s%4s%5s%5s%8s%6s%5s%5s%4s%4s" % (
        "run_dir", "ev", "rp", "exc", "exit", "score", "evKB", "obs", "tak", "真局", "入包"))
    for r in rows:
        print("%-18s%4d%4d%5d%5s%8s%6d%5d%5d%4s%4s" % (
            r["name"], r["has_ev"], r["has_replay"], r["excluded"], str(r["exit_code"]),
            str(r["quant"]), r["evkb"], r["obs"], r["tak"],
            "Y" if r["real"] else "", "Y" if r["name"] in known else ""))

    gap = [r for r in rows if r["real"] and r["name"] not in known]
    junk = [r for r in rows if r["has_replay"] and not r["real"] and not r["excluded"]]
    missing = [r for r in rows if r["real"] and not r["has_replay"]]

    # 同一 session_id 出现多个 run_dir ⇒ 其中必有一个是「中间快照 / 被取代的旧局」
    by_session = {}
    for r in rows:
        if r["real"] and r["session"]:
            by_session.setdefault(r["session"], []).append(r)

    # 标出被同会话更长局取代的目录（它们不该被算作「漏收录」）
    for sid, group in by_session.items():
        if len(group) < 2:
            continue
        keep = max(group, key=lambda x: x["months"] or 0)
        for r in group:
            r["superseded"] = (r is not keep)

    gap = [r for r in rows if r["real"] and not r.get("superseded") and r["name"] not in known]
    junk = [r for r in rows if r["has_replay"] and not r["real"] and not r["excluded"]]
    missing = [r for r in rows if r["real"] and not r.get("superseded") and not r["has_replay"]]

    print("\n=== ★ 重复 session_id（同一次会话留下多个 run_dir ⇒ 只应保留一个） ===")
    dup_found = False
    for sid, group in by_session.items():
        if len(group) < 2:
            continue
        dup_found = True
        print("  session %s… 共 %d 个目录：" % (sid[:12], len(group)))
        for r in sorted(group, key=lambda x: x["months"] or 0):
            print("     %s  score=%-6s outcome=%-10s months=%-3s evKB=%-5d replay=%s  inpack=%s  %s"
                  % (r["name"], r["quant"], r["outcome"], r["months"], r["evkb"],
                     "Y" if r["has_replay"] else "n", "Y" if r["name"] in known else "n",
                     "← 保留" if not r.get("superseded") else "← 中间快照，勿收录"))
    if not dup_found:
        print("  无")

    print("\n=== 真对局但未入包（构建器 BATCHES 漏了） ===")
    for r in gap:
        print("  %s  score=%s outcome=%s months=%s session=%s"
              % (r["name"], r["quant"], r["outcome"], r["months"], (r["session"] or "")[:12]))
    if not gap:
        print("  无")

    print("\n=== 真对局但缺 replay（需补生成） ===")
    for r in missing:
        print("  %s  score=%s" % (r["name"], r["quant"]))
    if not missing:
        print("  无")

    print("\n=== 有 replay 但不是真对局（★ 需排查，可能是脏数据） ===")
    for r in junk:
        print("  %s  exit=%s score=%s obs=%d tak=%d evKB=%d"
              % (r["name"], r["exit_code"], r["quant"], r["obs"], r["tak"], r["evkb"]))
    if not junk:
        print("  无")

    print("\n=== 疑似空壳（obs < 15，请人工确认是否只是极短局） ===")
    shell = [r for r in rows if r["real"] and r["obs"] < 15]
    for r in shell:
        print("  %s  score=%s obs=%d tak=%d evKB=%d" % (r["name"], r["quant"], r["obs"], r["tak"], r["evkb"]))
    if not shell:
        print("  无")


if __name__ == "__main__":
    main()
