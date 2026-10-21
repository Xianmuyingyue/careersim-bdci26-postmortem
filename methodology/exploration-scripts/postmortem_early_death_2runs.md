# 早亡局根因复盘 · 20260925T222709Z 与 20260925T195633Z

> 档位：**源码级验证**（引擎已安装包 + 数据集 `.data` 解码 + 局内权威日志 + 观测流三方交叉）。
> 结论可直接用于改技能；本文件只做分析，未改动 `solution/skills/`。

---

## 0. 结论速览

| 局 | 生存 | 结局 | 出局机制 | 一句话根因 |
|---|---|---|---|---|
| **222709Z** | **9 个月** | 喝西北风end | `wealth_deficit`（HP2，第 2 次触发） | 两次主动挑中**带 `Wealth −` 的选项**（M1 `−2`、M6 `−1`），而同一选项列表里都存在**零财富成本的孪生选项**；L1 工资是「每 3.3 个月才到账 1 点整财」的定点累加，一次 −1 就足以压出 3 个月的赤字连击 |
| **195633Z** | **24 个月** | 炒鱿鱼end | `consecutive_bad_performance`（HP2，第 2 次触发） | **在 L1 停留 24 个月**。L1 的绩效数学天花板 = **3 < 4**，而 mercy 护盾只到 `month ≤ 12` ⇒ M18、M24 两次评审对任何仍在 L1 的 Agent 都是「绩效不佳」⇒ 连击两次即出局；M24 那一枪与晋升同刻结算，**计数器先于晋升更新**，最后时刻补上门槛也救不回来 |

**两局是两条互不相干的死路**，不是同一个病：一个是**财富**、一个是**绩效**；一个是**决策失误**（有免费替代却选了付费的），一个是**阶段落后**（该升没升，撞上职级天花板）。

---

## 1. 证据来源（全部可复现）

| 类别 | 路径 |
|---|---|
| 引擎源码（权威） | `.venv/lib/python3.12/site-packages/career_emulator/{failure_conditions,salary_conditions,ending_score}.py`、`server/models.py`、`game.py` |
| 数据集（`.data` 解码） | `data/dataset/failure_conditions/wealth_deficit.data`、`consecutive_bad_performance.data`；`salary_conditions/{config,monthly_base_salary,half_year_performance_bonus}.data`；`performance_score/config.data`；`talk_mechanism/config.data`；`promotion/{config,levels}.data` |
| 局内权威日志 | `CareerSim-BDCI26/.career_sim_runner/career_emu/emulator_logs/{013c1c5d0a8540a4b8aff18fc3925c89,8634c33bf60748cc94a72c3935c2453a}.log` |
| 局内观测流 | `outputs/九问/<run>/events-<run>.jsonl`（逐回合 state 快照） |
| 结局 | `outputs/九问/<run>/score_report.json` |
| 动作池全量 | `data/dataset/action_pool/**`（173 文件，递归解出全部 `status_updates`） |

---

## 2. 本次新解出的引擎机制（7 条，此前技能里没有或写错）

### 2.1 ★ 财富是「整数 + 十分位定点累加器」——`0.3/月` ≠ `+0.3 财富/月`

`salary_conditions/config.data` → `{"wealth_scale": 10}`；`apply_fractional_wealth()`：

```python
units_to_add = round(amount * wealth_scale)          # 0.3 → 3 个「十分位」
total_units  = remainder + units_to_add
career.wealth += total_units // wealth_scale         # 满 10 个十分位 → +1 点整财
statistics["wealth_fraction_units"] = total_units % wealth_scale
```

`career.wealth` 是**整点财富**，小数部分存在 `wealth_fraction_units` 里。

⇒ **L1 月薪 0.3 的到账节奏是：连攒 4 个月 → 第 4 个月末才 +1 点整财**（3/6/9/12 个十分位）。
⇒ 「工资 0.3/月」**不能**用来抵扣一次 `Wealth −1`，恢复期是 **≈3.3 个月**。
⇒ `ending_score` 用 `effective_wealth = wealth + fraction_units/10` 计分（222709Z 因此得 `0 + 1/10 = 0.1`）。

### 2.2 负财富选项按职级**放大**

`CareerState.apply_delta()`：

```python
if key == "wealth" and value < 0:
    value = round(value * (1 + round((level_num / 4) ** 2)))
```

| 职级 | 放大系数 | 一个 `Wealth −1` 选项的真实代价 |
|---|---|---|
| **L1 / L2** | **×1** | −1 点整财 |
| L3 / L4 | ×2 | −2 |
| L5–L7 | ×3 | −3 |
| L8–L10 | ×5 | −5 |

### 2.3 `wealth_deficit` 精确规则（+ 触发时的「假重置」）

```json
{"name":"wealth_deficit","hp":2,
 "trigger_condition":{"wealth_deficit_consecutive_months":{"cmp":">=","threshold":3}},
 "streak_tracking":{"counter":"wealth_deficit_consecutive_months",
                    "increment_when":{"wealth":{"cmp":"<=","threshold":0}}},
 "trigger_stat_change":{"dignity":{"op":"-","value":1},
                        "wealth_deficit_consecutive_months":{"op":"=","value":0},
                        "wealth":{"op":"=","value":0}}}
```

- 计数器在**每个月末**（`_on_month_advanced` → `update_derived_stats`）更新：`career.wealth ≤ 0` → `+1`，否则**清零**。
- 结算顺序（`game.py:_on_month_advanced` + 调用方）：**计数器 → 半年谈话 → 工资/奖金 → 晋升 → 失败判定**。
- 第一次触发（HP 2→1）：播报 `[warning] 工资日变成了还债日…`，`dignity−1`、**`wealth` 被强制置 0**、计数器清零 —— **这不是救济**：`0` 仍然是「赤字月」，下一次月末照样 `+1`。三次连击即出局。

### 2.4 ★ 绩效公式与 **L1 天花板 = 3**

```
stat_term  = (min(high, low×2.0) + max(0, high − low×2.0)×0.3) / 15      # low/high = min/max(skill, network)
output_term = output / 10
level_term  = 9 次多项式(L)   →  L1 = 2.0 , L2 = 3.0 , L3 = 2.0 , L4 = 0.0 , L5 = −4.0 , L6 = −8.0
perf = round(stat_term + output_term + level_term) + adjustment
```

L1 段（CAP：skill 9 / network 3 / output 3）取**理论最优**：

| 状态 | perf |
|---|---|
| S9 N3 O3 | **3**（raw 2.76） |
| S9 N3 O2 | **3**（raw 2.66） |
| S9 N3 O0 | 2 |
| **L2** S18 N6 O5 | **4**（raw 4.42） |
| **L2** S9 N3 O2（刚升上来什么都不做） | **4**（raw 3.66） |

⇒ **L1 的 perf 数学上限就是 3，永远 < 4。** 出局线是 `performance_score < 4` ⇒ **在 L1，任何一次评审都会被判「绩效不佳」。**

### 2.5 mercy 只护 `month ≤ 12`

`performance_score/config.data` 的 `mercy`：

```json
{"condition":{"current_month":{"cmp":"<=","threshold":12},"performance_score":{"cmp":"<","value":4}},
 "adjust":{"performance_score":{"op":"=","value":4}}}
```

⇒ M6、M12 两次评审被强行抬到 `perf = 4`（安全）；**M18、M24 无保护**。

### 2.6 `consecutive_bad_performance` 规则 + 自我强化环

```json
{"hp":2,"trigger_condition":{"consecutive_bad_performance":{"cmp":">=","threshold":1}},
 "streak_tracking":{"counter":"consecutive_bad_performance","on_month_modulo":6,
                    "increment_when":{"performance_score":{"cmp":"<","threshold":4}}},
 "trigger_stat_change":{"network":{"op":"-","value":1},"dignity":{"op":"-","value":3},
                        "consecutive_bad_performance":{"op":"=","value":0}}}
```

**只在 `current_month % 6 == 0` 时更新**（即 M6/M12/M18/M24 评审），`perf < 4` → `+1`，否则清零。

半年谈话分档（`talk_mechanism/config.data`）：

```
talk_score = 3.5×perf + dignity + 0.25×health − 2×hidden_risk − 4×爆雷次数
             − 0.8×dignity_zero_streak − 3.0×consecutive_bad_performance
good ≥35 → D+2 N+1 risk−1，review: perf +2
average ≥20 → D+1
bad  <20 → D−2 risk+1 H−1，review: perf −2      ← ★
```

★ **自我强化环**：计数器在谈话**之前**就已 +1 ⇒ `talk_score` 立刻被 `−3.0` 拖进 `bad` 档 ⇒ `perf −2` ⇒ 奖金档下跌（C→D）⇒ 下一次评审更难过线。**一旦吃到第一次「绩效不佳」，本窗口基本上已经锁死。**

### 2.7 动作池里 **74 个选项**能直接增减财富——推翻技能中的「零命中」

递归解出全部 173 个事件文件的 `status_updates`：

| 取值 | 数量 |
|---|---|
| `Wealth −3` | 1 |
| `Wealth −2` | 8 |
| `Wealth −1` | 30 |
| `Wealth +1` | 29 |
| `Wealth +2` | 4 |
| `Wealth +3` | 2 |
| **合计** | **74 个选项 / 33 个事件（负 39 / 正 35）** |

而当前技能 `decision-policy/SKILL.md:36` 写的是：
> **财富是职级的影子。** 全事件池 171 个文件中 `wealth` **零命中**——没有任何选项能直接增减财富。

**这条前提是错的**（当时是纯文本 grep，漏掉了嵌套在 `nodes.*.choices[].status_updates` 里的字段），而它正是 222709Z 全程不把财富当约束的认知起点。

---

## 3. 222709Z 复盘：财富出局（喝西北风end，生存 9 个月）

`score_report`：L1 / wealth raw **0.1** / 结局 `eliminated` / `play_exit_code = 0` / 34 个决策回合。

### 3.1 逐月账本（由 2.1/2.3 规则复算，与观测流逐点吻合）

| 月末结算点 | 检查时 wealth | 计数器 | 结算后 wealth / 十分位余数 | 事件 |
|---|---|---|---|---|
| 起始 | — | 0 | **1** / 0 | 初始财富 = 1 点 |
| roll1（M1） | **−1** | **1** | −1 / 3 | M1 选「也送咖啡加入人情战」→ `Wealth −2` |
| roll2（M2） | −1 | **2** | −1 / 6 | — |
| roll3（M3） | −1 | **3 → 触发#1** | 0 / 9 | ★ 播报「工资日变成了还债日…」；`D−1`，wealth 置 0，计数器清零 |
| roll4（M4） | 0 | 1 | **1** / 2 | 十分位攒满 12 → 首次 +1 整财 |
| roll5（M5） | **1** | **0（清零）** | 1 / 2 | 奖金 C（0.3×−1.0 = −0.3 → −3 十分位） |
| roll6（M6） | **0** | **1** | 0 / 5 | M6 选「立即停止在个人项目使用公司设备」→ `Wealth −1` |
| roll7（M7） | 0 | **2** | 0 / 8 | — |
| roll8（M8） | 0 | **3 → 触发#2** | 1 / 1 → 置 0 | ★ **HP 2→0 ⇒ 喝西北风end**；`effective_wealth = 0 + 1/10 = 0.1`（与 `score_report.raw_value = 0.1` 完全一致） |

### 3.2 ★ 两次致命选择，都是「有免费替代却选了付费的」

**M1 · `sc_evt_coffee_favor_politics_079`（带咖啡同事积累人情选组长）**

| 选项 | status_updates |
|---|---|
| **[4] 也送咖啡加入人情战**（选中） | `{Wealth −2, Network +1, Dignity −1}` ← **唯一带财富成本** |
| [5] 接受值班，维持关系 | `{Network +1, Health −2, Dignity −1}` ← 同 N/D 画像，**零财富成本** |
| [1] 拒绝站台，评审只讲事实 | `{Dignity +2, Network −2}` |

Agent 的决定理由（原文）：「选送咖啡（命中"分享"补N组，ΔN +0.24~+1.28 且 ΔRisk −0.35~−0.79，双赢）」——**用「补 N + 降风险」两维打分，把亏损项完全没算进去**。

**M6 · `sc_evt_office_equipment_personal_259`（办公设备私用边界）**

| 选项 | status_updates |
|---|---|
| **[1] 立即停止在个人项目使用公司设备**（选中） | `{Dignity +2, HiddenRisk −1, Skill +1, Wealth −1}` |
| [2] 向 Leader 和合规部门确认…请求书面确认（**被它显式否决**） | `{Dignity +2, Network +1, HiddenRisk −1, Output −1}` ← 零财富成本 |
| [5] 按建议减少周末使用，把主要开发转到个人设备 | `{Dignity +2, Network +1, HiddenRisk −1}` ← **严格占优**（D/风险同，N 更高，零财富成本） |
| [4] 保持低调，认为个人选择无需推广 | `{Dignity +1, HiddenRisk −1}` ← 零成本纯赚 |

在 L1，`Skill +1` 是**溢出为 0** 的（S 已顶 CAP 9），而 `Network +1` 是 L1→L2 门槛（N≥3）急需的硬指标 ⇒ **选项 5 在「价值更高 + 零财富成本」两个维度上同时碾压选项 1**，Agent 却选了被支配的那个，理由写的是「主动纠错，降风险，**最干净**」。这是**纯决策错误，不是运气**。

### 3.3 决定性反事实

- 若 M6 不选带 `Wealth −1` 的选项：roll6 wealth = 1、roll7 = 1、roll8 = 1（十分位 5→8→11 才 +1）⇒ **计数器恒为 0 ⇒ 不会出局**。
- 若 M1 不选 `Wealth −2`：wealth 全程 ≥ 0，第 1 次触发也不会发生（M1–M3 的连击消失）。

### 3.4 过程失败（可量化）

- 全 34 条决策 `notes` 里，出现「财富 / Wealth / 现金流」的条目数 = **0**（脚本统计）。
- M3 已经收到引擎播报的财富警告，之后 12 个回合中**从未**把财富列入约束。
- 技能侧的缺陷：`risk-guardian/SKILL.md:34` 只写了

  > | 4 | **财富不可连续 3 月 ≤0** | `wealth ≤ 2` | 优先保证正向现金流 |

  —— **「触发阈」有了，「行动规则」没有**：没有「候选选项含 `Wealth ≤ −1` 时一票否决 / 降权」这种可执行条款，也没有「L1 一次 −1 = 立刻进入 3 个月倒计时」的量级提示。

---

## 4. 195633Z 复盘：绩效出局（炒鱿鱼end，生存 24 个月）

`score_report`：L1→(M24)L2 / wealth 9.4 / 结局 `eliminated`。

### 4.1 四次评审时间线（引擎日志 + 观测流 + 公式复算，三方一致）

| 评审（`current_month`） | 检查时状态 | perf（公式） | mercy | 计数器 | 谈话档 | 奖金 | 结果 |
|---|---|---|---|---|---|---|---|
| **M6** | S9 N0 O0 | 3 | **生效→4** | 0（4 不 <4 ⇒ 清零） | average | C −0.3 | 未晋升（O0/N0 挂门） |
| **M12** | S9 N3 O2 | 3 | **生效→4** | 0 | average | C −0.3 | 未晋升（O=2<3 挂门） |
| **M18** | S9 N3 O2 | 3 | **失效** | **0→1 ⇒ 触发#1** | **bad**（被 `−3×1` 拖落） | **D −0.6** | ★ 播报「收到了一次不妙的半年绩效…」；`D−5`（实测 10→5：谈话 bad −2 + 触发 −3 ✓）、`N−1`、`perf −2`（→ 奖金档从 C 掉到 D ✓） |
| **M24** | S9 N3 O2（仍在 L1） | 3 | **失效** | **0→1 ⇒ 触发#2** | — | C −0.3 | ★ **HP 2→0 ⇒ 炒鱿鱼end**；**同月同刻**还完成了 L1→L2 晋升（日志 691 行晋升、692 行出局） |

### 4.2 根因：**「M18 前没离开 L1」是一条机械化的死亡线**

1. L1 的 perf 上限 = 3（§2.4），**恒定 < 4**；
2. mercy 只到 `month ≤ 12`（§2.5）；
3. ⇒ **M18 与 M24 两次评审对任何仍在 L1 的 Agent 必然是「绩效不佳」**；
4. `consecutive_bad_performance` 是 HP2 ⇒ 连吃两次即出局；
5. 且第一次触发把 `consecutive_bad_performance` 顶成 1，谈话公式里 `−3.0×1` 直接把谈话压到 `bad` 档，再 `perf −2`（§2.6）⇒ **M18 吃过警告后，M24 几乎不可能翻盘**。

**⇒ 等价于一条硬生存线：`duration_in_level ≥ 18 且仍在 L1` = 死缓，M24 必执行。**
唯一出路是**在 M12 窗（含）之前升到 L2**——因为 L2 的 `level_term = 3.0`，即便状态不变（S9 N3 O2）perf 也立刻从 3 变成 4（§2.4），评审当场变安全。

### 4.3 它为什么三个窗口都挂门（门槛：skill ≥8 / output ≥3 / network ≥3 / dignity ≥2）

| 窗口 | 实测状态 | 挂在哪一维 |
|---|---|---|
| M6 | S9 **O0 N0** | output、network 双挂 |
| M12 | S9 **O2** N3 | output 差 1 |
| M18 | S9 **O2** N3 | output 差 1 |
| M24 | S9 **O3** N3 | ✓ 门槛终于够了（但为时已晚） |

Agent 自己的诊断（`analysis/find_miss_reason.py` 抽取，与实测一致）：
「★M6评审已结算:未晋升(四维 S9✓ 但 **O0/N0** ✗)」「M12评审已结算:未晋升(**M11 末 O=2<3 挂门**)」。

**真正的短板是 `output`，不是 `network`。** L1 段 `CAP(output) = 门槛 = 3`（余量恒 0，§一硬约束），只要评审前 output 掉 1 点就直接挂门；而这局在 M6/M12/M18 三个窗口的 output 分别是 0 / 2 / 2，**整整 18 个月都没把 output 顶到 3**。

### 4.4 ★ 出局与晋升「同一刻」结算——顺序细节

`game.py:_on_month_advanced` 的顺序是「**计数器 → 谈话 → 工资 → 晋升**」，`_evaluate_failure_conditions()` 在其后：

```
计数器（此时仍是 L1 ⇒ perf=3 ⇒ +1）
  → 谈话（bad，perf−2）
  → 工资/奖金
  → 晋升（L1→L2，门槛恰好达标）
  → 失败判定（counter ≥1 ⇒ 第 2 次 ⇒ 出局）
```

⇒ **计数器用的是晋升前的职级。** 在 M24 才补上门槛 = 无用。
这也解释了日志里看似矛盾的一幕：`[promotion] 从 L1 晋升至 L2` 与 `[failure] 炒鱿鱼end` 出现在同一秒。

---

## 5. 两局对照

| 维度 | 222709Z | 195633Z |
|---|---|---|
| 出局通道 | `wealth_deficit`（HP2） | `consecutive_bad_performance`（HP2） |
| 死因性质 | **单点决策错误**（可选免费替代却选了付费项 ×2） | **阶段落后**（该升没升，撞职级天花板） |
| 死亡时钟 | 3 个连续「赤字月末」= **约 3 个月** | 2 次「mod-6 评审 perf<4」= **约 6~12 个月** |
| 首次警告月 | M3 | M18 |
| 警告→出局 | 5 个结算点 | 6 个月 |
| 收到警告后是否改策略 | ❌ 又选了一次 `Wealth −1` | ❌ 仍没把 output 顶到 3 |
| 技能中的对应条款 | 有（约束 4），但只有「优先保证正向现金流」，**无可执行规则**；且被错误前提「wealth 零命中」抵消 | 有（M11 生死线 / 评审四维），但**没有「L1 停留 ≥18 月 = 死缓」这条**，也没把 output 的「余量恒 0」当作第一保护对象 |

**三条共同结构性缺陷**

1. **技能不知道「HP2 累计型出局是有倒计时的」**：两局都在收到 `[warning]` 后继续原策略。技能里没有「接到警告 ⇒ 该维度进入 3/6 个月不可再跌保护」的整改协议。
2. **技能的价值函数缺项**：222709Z 的两次选择都是「N/风险两维打分」的产物；`Wealth` 不在评分表里 ⇒ 平票时随机/按词典命中挑，恰好吃到付费项。
3. **技能把「补量」当成目标而不是「在哪个职级补」**：L1 的天花板（perf 3、CAP(O)=3）使得「留在 L1 精修」不是稳健而是自杀；真正的最优是**尽早换职级**（L2 的 level_term 3.0 让一切评审变安全）。

---

## 6. 需要修正的既有结论

| 旧结论 | 更正 |
|---|---|
| `report.md` 记 222709Z「**疑似环境问题，非策略失败**」 | **改判为真实早死**（财富出局）。它确实有 2 次 `attempt exit≠0`，但第 3 次尝试正常跑完 34 回合、`play_exit_code = 0`、产出完整结局分 ⇒ **数据有效**，「环境问题」判据须补一条：**只有未产出有效结局（无 `score_report` / `play_exit_code≠0`）才算环境问题**。 |
| v8_5 真实早死率 1/7（14%） | **2/7（≈29%）** |
| `decision-policy`「wealth 零命中，没有任何选项能直接增减财富」 | **错**。动作池有 **74 个**选项带 `Wealth` 增减（39 负 / 35 正），覆盖 33 个事件。 |
| 「L1 段 perf 数学上限 = 3 < 出局线 4」（原表述为 M11 生死线） | 数值正确，但**机制表述需精确**：L1 的 perf 恒 < 4 本身**不致命**（mercy 护到 M12）；致命组合是「**L1 天花板 3** + **mercy 止于 month 12**」⇒ M18/M24 连击。这不是 M11 的问题，是 **M18–M24 的问题**。 |

---

## 7. 待议修法（未改任何技能，等拍板）

| 优先级 | 修法 | 针对 |
|---|---|---|
| **P0** | 新增硬门：**`duration_in_level ≥ 12 且仍在 L1` ⇒ 全部资源转攻晋升门槛**（尤其 output/network），视为与「health≤3」同级的最高优先级；`≥18 且仍在 L1` 标记为「死缓，M24 必死」 | 195633Z |
| **P0** | 新增**财富否决条款**（可执行版）：候选选项 `Wealth ≤ −1` 时，①若同事件存在 `Wealth ≥ 0` 且 N/风险维度不劣的替代 ⇒ **一票否决**；②若必须选，则要求 `wealth ≥ 3`（L1/L2）/`≥ 4`（L3+，考虑 ×2 放大）。同时写明**识别方法**：读选项的 `status_updates` 里的 `Wealth` 字段 | 222709Z |
| **P0** | 新增**警告整改协议**：一旦收到 `[warning]`（财富 / 绩效 / 爆雷 / 人缘任一），该维度在下一次结算点之前进入「**不可再跌**」保护；连续两次同源警告 ⇒ 升级为「禁止任何负增量选项」 | 两局 |
| **P1** | 纠正 `decision-policy` 的错误前提（wealth 零命中 → 74 个选项），并列出**高危事件族**：合规/诚实/自担成本型选项（`sc_evt_travel_expense_gray_241`、`sc_evt_side_project_conflict_229`、`sc_evt_voluntary_paycut_326`、`sc_evt_noncompete_signoff_154`、`lc_evt_client_dubious_venue_expense_049`、`sc_evt_office_equipment_personal_259`…）**大量以 `Wealth −1/−2` 为代价**，而配对的「+1 但注风险」选项正是被「合规优先」策略否决的那一个 ⇒ 需要「合规 vs 财富」的显式裁决条款 | 两局 |
| **P2** | L1 段把 `output` 定为评审窗**第一保护对象**（先于 network）：`CAP(output) = 门槛 = 3`，余量恒 0，任何一次 `ΔO<0` 都可能直接挂门 | 195633Z |
| **P2** | 生存盘复算：把「L1 停留月数」加入 `run_metrics.py`，作为与 `clamp_occupancy` 并列的一级指标 | 工具链 |

---

*生成时间：2026-09-26 · 数据源：引擎包 1.0.1 + `.career_sim_runner` 局内日志*
