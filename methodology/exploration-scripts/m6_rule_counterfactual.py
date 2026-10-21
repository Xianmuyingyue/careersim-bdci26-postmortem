#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ M6 零成本律的「节点级反事实 + 判据排行榜」。

与前两版的关系：
  · pool_option_audit       → 全池上「有没有」安全选项（可能性）
  · pool_heuristic_search   → 全池上「文本特征有没有判别力」（选项级）
  · 本脚本                  → 在 57 局**真实出现的 M5 节点**上，逐条候选判据算**可实现晋级率**（决策级）

反事实的合法性（机制，非假设）：
  L1 的 CAP(O/N) == M6 门槛(O/N) ⇒ 安全选项的增益至多被截断、绝不会造成损失
  ⇒ M5 末 (S,O,N) 达标 + 改选安全选项 ⇒ 评审态必然仍达标。

用法：.venv/bin/python3 analysis/m6_rule_counterfactual.py
"""
import json, glob, pathlib, re
from collections import defaultdict

OUTROOT = pathlib.Path(".career_sim_runner/career_emu/outputs/九问")
POOL = pathlib.Path("../官方资料/decoded_dev/action_pool")
DEC = json.JSONDecoder()

TH = dict(skill=8, output=3, network=3, cap_skill=9, cap_output=3, cap_network=3)  # L1

COMPLIANCE = ["承认", "如实", "按事实", "提出异议", "异议", "拒绝", "守边界", "边界",
              "合规交接", "坚持原则", "澄清", "举报", "反映", "不解释", "匿名", "沉默"]
NUMWORD = re.compile(r"\d+\s*(天|周|个月|月|小时|次|遍|轮)")


def stream(path):
    out = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        st, call = None, None
        if "current_state" in line:
            t = line.replace('\\"', '"')
            i = t.find('{"current_state":{')
            while i != -1:
                try:
                    obj, _ = DEC.raw_decode(t[i:])
                except Exception:
                    obj = None
                if isinstance(obj, dict) and "current_state" in obj:
                    st = obj
                i = t.find('{"current_state":{', i + 1)
        if o.get("kind") == "tool_call" and "take_action" in line:
            js = json.dumps(o, ensure_ascii=False)
            a = re.search(r'"arguments": "((?:[^"\\]|\\.)*)"', js)
            if a:
                for load in (lambda s: json.loads(s),
                             lambda s: json.loads(s.replace('\\"', '"'))):
                    try:
                        call = load(a.group(1))
                        break
                    except Exception:
                        call = None
        out.append((o.get("seq"), o.get("kind"), st, call))
    return out


def load_pool():
    by_actions = defaultdict(list)
    files = sorted(glob.glob(str(POOL / "short_chain" / "*.json"))) + \
            sorted(glob.glob(str(POOL / "long_chain" / "*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for nid, node in (d.get("nodes") or {}).items():
            chs = node.get("choices") or []
            if not chs:
                continue
            key = frozenset(str(c.get("action") or "") for c in chs)
            by_actions[key].append(dict(ename=d.get("event_name", ""), nid=nid, chs=chs))
    return by_actions


def g(u, k):
    return (u or {}).get(k, 0)


def safe(o):
    u = o.get("status_updates") or {}
    return g(u, "Network") >= 0 and g(u, "Output") >= 0


def ok(st):
    return st["skill"] >= TH["skill"] and st["output"] >= TH["output"] and st["network"] >= TH["network"]


# ---------------- 候选判据（全部只用「游戏内可见」的信息） ----------------
def mk_rules():
    R = {}
    R["位置1"] = lambda order, acts: order[0] if order else None
    R["位置最后"] = lambda order, acts: order[-1] if order else None
    R["最长文本"] = lambda order, acts: max(order, key=lambda c: len(str(c.get("action") or "")))
    R["最短文本"] = lambda order, acts: min(order, key=lambda c: len(str(c.get("action") or "")))
    R["最长且非原则族"] = lambda order, acts: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not any(k in str(c.get("action") or "") for k in COMPLIANCE)), None)
    R["最长且无承诺数字"] = lambda order, acts: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not NUMWORD.search(str(c.get("action") or ""))), None)
    R["非主动族里最长"] = lambda order, acts: next(
        (c for c in sorted(order, key=lambda c: -len(str(c.get("action") or "")))
         if not any(k in str(c.get("action") or "") for k in ["主动", "争取", "牵头", "承担", "报名", "请缨", "加班", "投入"])), None)
    R["神谕(真值上限)"] = lambda order, acts: next((c for c in order if safe(c)), None)
    return R


def main():
    by_actions = load_pool()
    rules = mk_rules()
    rows = []
    for p in sorted(glob.glob(str(OUTROOT) + "/*/events-*.jsonl")):
        rd = pathlib.Path(p).parent.name
        st = stream(pathlib.Path(p))
        snaps = [(i, s) for i, (sq, k, s, c) in enumerate(st) if s]
        rev = None
        for i, s in snaps:
            if s["current_state"]["time"].get("current_month") == 6 and "【半年谈话】" in (s.get("events") or ""):
                rev = (i, s)
                break
        if rev is None:
            continue
        ri, rst = rev
        base = None
        for i, s in snaps:
            if i >= ri:
                break
            if s["current_state"]["time"].get("current_month") == 5:
                base = (i, s)
        if base is None:
            continue
        bi, bst = base
        chs = bst.get("choices") or []
        acts = [str(c.get("action") or "") for c in chs]
        if not acts:
            continue
        cand = by_actions.get(frozenset(acts))
        node = cand[0] if cand and len({x["nid"] for x in cand}) == 1 else None
        chosen, chosen_idx = None, None
        for j in range(bi, ri):
            sq, k, s, c = st[j]
            if k == "tool_call" and isinstance(c, dict) and "choice" in c:
                chosen, chosen_idx = c, c.get("choice")
        by_act = {}
        if node:
            for c in node["chs"]:
                by_act.setdefault(str(c.get("action") or ""), c)
        order = [by_act[a] for a in acts if a in by_act]
        rows.append(dict(rd=rd, b=bst["current_state"]["status"], r=rst["current_state"]["status"],
                         event=(bst.get("current_event") or {}).get("title", ""),
                         acts=acts, node=node, order=order, chosen_idx=chosen_idx))

    n = len(rows)
    nb = sum(1 for x in rows if ok(x["b"]))
    nr = sum(1 for x in rows if ok(x["r"]))
    print(f"=== M6 评审局 {n} 局；M5 末达标 {nb}/{n} = {nb/n*100:.1f}%；评审态达标 {nr}/{n} = {nr/n*100:.1f}%（现实晋级率）")
    print(f"    节点全池唯一匹配：{sum(1 for x in rows if x['node'])}/{n}")
    print(f"    【关键空洞】M5 末达标却落榜 = {sum(1 for x in rows if ok(x['b']) and not ok(x['r']))} 局"
          f"；M5 末不达标却晋级 = {sum(1 for x in rows if not ok(x['b']) and ok(x['r']))} 局")

    # 现实选中项（按序号对齐）
    real_safe = 0
    for x in rows:
        if x["chosen_idx"] and 1 <= x["chosen_idx"] <= len(x["acts"]):
            a = x["acts"][x["chosen_idx"] - 1]
            o = next((c for c in x["order"] if str(c.get("action")) == a), None)
            if o and safe(o):
                real_safe += 1

    print(f"\n【1】判据排行榜（在真实 M5 节点上）")
    print(f"    {'判据':<16}{'选到安全':<10}{'命中率':<10}{'反事实晋级':<12}{'晋级率':<10}{'相对现实':<10}")
    res = []
    for nm, fn in rules.items():
        hit = 0
        good = 0
        for x in rows:
            o = fn(x["order"], x["acts"]) if x["order"] else None
            if o and safe(o):
                hit += 1
            # 反事实：选中安全 + 末态达标 ⇒ 保住；否则保持现实结果
            if o and safe(o) and ok(x["b"]):
                good += 1
            elif o and safe(o) and not ok(x["b"]):
                u = o.get("status_updates") or {}
                nb2 = dict(x["b"])
                nb2["network"] = min(nb2["network"] + g(u, "Network"), TH["cap_network"])
                nb2["output"] = min(nb2["output"] + g(u, "Output"), TH["cap_output"])
                nb2["skill"] = nb2["skill"] + g(u, "Skill")
                good += 1 if ok(nb2) else (1 if ok(x["r"]) else 0)
            else:
                good += 1 if ok(x["r"]) else 0
        res.append((nm, hit, hit / n, good, good / n))
    for nm, hit, hr, good, gr in res:
        star = " ★" if nm == "神谕(真值上限)" else ""
        print(f"    {nm:<16}{hit:<10}{hr*100:>5.0f}%{'':<4}{good}/{n}{'':<6}{gr*100:>5.1f}%{'':<4}{gr*100-nr/n*100:>+6.1f}pp{star}")
    print(f"    {'【现实】':<16}{real_safe:<10}{real_safe/n*100:>5.0f}%{'':<4}{nr}/{n}{'':<6}{nr/n*100:>5.1f}%")

    print("\n【2】为什么「位置1」在 M5 上失灵？（全池 74% → M5 仅够一半）")
    print("    M5 是「两难抉择」高发月：第 1 位常被写成最主动/最合规的那个 ⇒ 恰好是最贵的那个。")
    from collections import Counter
    c = Counter(x["event"] for x in rows)
    for ev, k in c.most_common(8):
        sub = [x for x in rows if x["event"] == ev]
        s1 = sum(1 for x in sub if x["order"] and safe(x["order"][0]))
        print(f"      {ev[:24]:<26} 出现 {k} 次   位置1 安全率 {s1}/{k}")

    print("\n【3】结论口径")
    up = [r for r in res if "神谕" in r[0]][0]
    print(f"    理论天花板（需要真值，游戏内不可得）：{up[4]*100:.1f}%  = 现实 {nr/n*100:.1f}% 的 {up[4]/(nr/n):.2f} 倍")
    best = max((r for r in res if "神谕" not in r[0]), key=lambda r: r[4])
    print(f"    可见判据最优（{best[0]}）：{best[4]*100:.1f}%  ⇒ 仅 {best[4]*100-nr/n*100:+.1f}pp")
    print(f"    ⇒ 缺口 {(up[4]-best[4])*100:.1f}pp 全部来自「剧情选项在游戏内无 status_updates」这一事实。")


if __name__ == "__main__":
    main()
