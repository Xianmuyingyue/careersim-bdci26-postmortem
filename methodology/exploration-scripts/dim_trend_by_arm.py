#!/usr/bin/env python3
"""按臂聚合六维原始值 + 结局分，定位「行为漂移」从哪一臂开始。

回答：分数下滑是「健康/风险保护过度而发育不足」，还是别的？
输出每臂的：n / 均值分 / level / wealth / resilience / skill / risk_control / network
"""
import json
import os
import statistics as st

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, ".career_sim_runner", "career_emu", "outputs", "九问")
HTML = os.path.join(os.path.dirname(REPO), "analysis", "replay_browser.html")

ORDER = ["hist", "v1", "v2", "v3", "v5", "v7", "v8", "v8_1", "v8_2", "v8_3", "v8_4",
         "v8_5", "v9", "v10", "v10b", "v10c", "v10d", "v10e"]

DIMS = ["level", "wealth", "resilience", "skill", "risk_control", "network"]


def arm_map():
    h = open(HTML, encoding="utf-8").read()
    data, _ = json.JSONDecoder().raw_decode(h[h.find('{"runs":'):])
    m = {}
    for b in data["batches"]:
        for dn in b["dirs"]:
            m[dn] = b["tag"]
    for r in data["runs"]:
        if r["dir"] not in m:
            m[r["dir"]] = "hist" if (r["metrics"] or {}).get("arm") in (None, "?") else r["metrics"]["arm"]
    return m


def main():
    m = arm_map()
    per = {}
    for dn in sorted(os.listdir(OUT)):
        d = os.path.join(OUT, dn)
        if not os.path.isdir(d):
            continue
        sr = os.path.join(d, "score_report.json")
        if not os.path.exists(sr):
            continue
        try:
            payload = json.load(open(sr, encoding="utf-8"))
        except Exception:
            continue
        e = payload.get("ending_score") or {}
        if not e.get("quantitative_score"):
            continue
        dims = {x["name"]: x["raw_value"] for x in (e.get("dimensions") or [])}
        per.setdefault(m.get(dn, "?"), []).append(
            dict(score=e["quantitative_score"], months=e.get("survival_months"), **dims))

    print("%-7s%3s%8s%7s%7s%7s%7s%7s%7s%7s%8s" % (
        "arm", "n", "score", "sd", "level", "wealth", "resil", "skill", "risk", "netw", "mon"))
    for arm in ORDER + sorted(set(per) - set(ORDER)):
        rows = per.get(arm)
        if not rows:
            continue
        sc = [r["score"] for r in rows]
        print("%-7s%3d%8.2f%7.2f%7.2f%7.2f%7.2f%7.2f%7.2f%7.2f%7.1f" % (
            arm, len(rows), st.mean(sc), (st.stdev(sc) if len(sc) > 1 else 0.0),
            st.mean([r.get("level") or 0 for r in rows]),
            st.mean([r.get("wealth") or 0 for r in rows]),
            st.mean([r.get("resilience") or 0 for r in rows]),
            st.mean([r.get("skill") or 0 for r in rows]),
            st.mean([r.get("risk_control") or 0 for r in rows]),
            st.mean([r.get("network") or 0 for r in rows]),
            st.mean([r.get("months") or 0 for r in rows])))

    print("\n=== 只看「完赛 48 月」的局（剔除早死干扰）===")
    print("%-7s%3s%8s%8s%8s%8s%8s%8s%8s" % (
        "arm", "n", "score", "level", "wealth", "resil", "skill", "risk", "netw"))
    for arm in ORDER + sorted(set(per) - set(ORDER)):
        rows = [r for r in per.get(arm, []) if (r.get("months") or 0) >= 48]
        if not rows:
            continue
        print("%-7s%3d%8.2f%8.2f%8.2f%8.2f%8.2f%8.2f%8.2f" % (
            arm, len(rows), st.mean([r["score"] for r in rows]),
            st.mean([r.get("level") or 0 for r in rows]),
            st.mean([r.get("wealth") or 0 for r in rows]),
            st.mean([r.get("resilience") or 0 for r in rows]),
            st.mean([r.get("skill") or 0 for r in rows]),
            st.mean([r.get("risk_control") or 0 for r in rows]),
            st.mean([r.get("network") or 0 for r in rows])))


if __name__ == "__main__":
    main()
