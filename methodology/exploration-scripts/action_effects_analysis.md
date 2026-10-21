# 月度体力行动：短程 / 长程 / 长尾 / 跨区间作用全景分析

> 全部数值来自引擎权威解码（`career_emulator_bdci26/.../initialization_n_regular/energy_event.data`
> 的 `status_updates`，以及 `promotion/`、`performance_score/`、`talk_mechanism/`、`failure_conditions/`
> 各 `.data`）。体力预算 3 点 / 季，超预算组合无效，同行动可重复，`allow_no_action=True`，**未用体力不累计**。

---

## 0. ★ 先更正一个影响全局的旧结论

旧版（MEMORY.md §v7 与 2026-09-25 日志 line 1524/1569）写「`当前读数+ΔRisk ≤ 3` 拒收 /
单次注入≥+3 充要」。**这是错的。** 权威解码 `risk_burst.data`：

- 触发条件：**`hidden_risk >= 5`**，不是剩余 ≤3；
- `hp = 2` ⇒ **两次爆雷才出局**：首次爆雷即重罚 —— `output` 回写为 **6 个月前快照值** + `dignity−2`
  + `wealth−2` + `hidden_risk=0` + 爆雷计数+1；第二次 = `信任危机end`；
- 大额注入来自**剧情事件**（043821Z 的 +3/+5 是事件选项），体力行动 `high_intensity_work` **每季仅 +1**，
  唯一降险体力动作是 `处理历史埋雷`（−1/季）。

⇒ v7 `risk-guardian` 的「约束5 ≤3」必须按 `>=5` 重校，否则会误拒完全安全的体力行动。

---

## 1. 让作用"跨区间"共享的五台机器

| 机器 | 机制 | 对体力行动的含意 |
|---|---|---|
| **perf 公式** | `perf = (skill/network 软帽项)/15 + output/10 + level_term(职级)`；`level_term` 随职级**递减**（L1:+2 → L4:0 → L10:−27） | output 每点稳定 +0.1 perf；skill/network 若失衡（一维 >另维×2），溢出部分只按 0.3/15≈0.02/点计，几乎白给 |
| **stat_clamp（CAP）** | 每次晋升把 `skill/network/output` 钉死在 **下一职级门槛 × 1.2**；超限投入被丢弃 | 已被截断的维度再投 = 长期浪费（长尾） |
| **晋升回扣** | 每次晋升扣 `network`：L3→L4 −2、L4→L5 −2、L5→L6 −3、… L8→L9/L9→L10 −5 | 你攒的 network 会在每次晋升时被"征税"（长尾） |
| **半年谈话** | `month%6==0` 在评审**前**结算：`talk_score=3.5·perf+1.0·dignity+0.25·health−2.0·hidden_risk−4.0·burst−0.8·尊严连零−3.0·绩劣连`；good(≥35)→perf_adjustment **+2**、average(≥20)→无、bad(<20)→**−2** | 任一动作影响 dignity/health/hidden_risk/perf → 拨动谈话档 → 拨动当月评审 perf 门 |
| **失败 HP 模型** | 每条规则独立 `hp`；触发时 `hp−1` 并施加 `stat_change`；`hp<=0` 出局。多数规则 `hp=2`（首次=警告+惩罚，二次=出局）；仅 `health_zero` hp=1（即时死）、`skill_obsolete` hp=5 | 多数失败机制给你**一次免费命中**的宽限期（长尾宽限） |

---

## 2. 八个体力行动逐维拆解

> 符号：短程 = 本季 `status_updates` 即时结算；长程 = 累积后如何影响晋升/perf/财富/结局；
> 长尾 = 延迟/持续的后效；跨区间 = 跨越上述「五台机器」的连锁。

### ① 高强度工作　`high_intensity_work`（耗 2）
- **短程**：`Output+2 / Health−1 / Dignity−1 / HiddenRisk+1`（单季最强 output 源，但三处埋雷）。
- **长程**：Output 是高层级（L4 需 22、L5 需 32、L6 需 45…）**首要瓶颈**；Health/Dignity 持续下探。
- **长尾**：`HiddenRisk+1` 季季累积，静默直到 `>=5` 引爆（首次爆雷把 output 回写 6 月前快照！）；
  Health 若与 `技能学习` 叠加 −1/季，长期滑向 `health<=0` 即时死；Dignity 滑向 `<=1` 触发尊严连零计数。
- **跨区间**：HiddenRisk → 谈话（−2 权重，压低档位→perf−2→晋升失败）**且** → 爆雷失败规则；
  Health → `health_zero`；Dignity → `dignity_crisis` + 谈话。**三机制同时暴露，杠杆最高也最危险。**

### ② 技能学习　`skill_learning`（耗 2）
- **短程**：`Skill+1 / Health−1`。
- **长程**：Skill 是硬晋升门（L1 需 8 → L9 需 290），并作为 perf 软帽两维之一参与。
- **长尾**：若 `skill ≫ network`（或反之），溢出只按 ≈0.02/点计，**失衡投资近乎无效**；
  超 CAP 部分被钉死丢弃；Health−1 累积 → `health_zero` 风险。
- **跨区间**：Skill 主连**晋升门**与 perf 软帽；Health−1 连 `health_zero`。**本身不直接触发任何失败规则**（Skill 只增不减，除非剧情事件减）。

### ③ 人脉维护　`network_maintenance`（耗 1）
- **短程**：`Network+1 / Dignity+1`（最便宜的双增益）。
- **长程**：Network 是晋升门（L1 需 3 → L9 需 120）+ perf 软帽另一维 + Dignity 晋升门。
- **长尾**：每次晋升**扣 network**（−2~−5），你攒的会被征税；超 CAP 被钉；`network<=1` 连满 3 月 → `network_isolated`（孤岛 end）。
- **跨区间**：Network 连 perf + 晋升门 + 晋升回扣 + 谈话（good 档再 +1）+ `network_isolated`；
  Dignity 连 `dignity_crisis` + 谈话。**最"联网"的动作，触碰 perf、晋升、谈话与两条失败规则。**

### ④ 处理历史埋雷　`defuse_legacy_risk`（耗 2）
- **短程**：`HiddenRisk−1`（**唯一降险的体力动作**，无任何正收益，纯防御）。
- **长程**：把 `hidden_risk` 压在爆雷线（>=5）之下；不让 ① 的 +1/季累积成炸弹。
- **长尾**：数学上 净险增长 = (高强度次数 − 埋雷次数)；最多可承受 4 季纯 `high_intensity_work` 不埋雷，
  第 5 季才触爆。**埋雷是"保险"，不是"得分"。**
- **跨区间**：HiddenRisk↓ → 谈话（−2 权重解除，可把档位从 bad 推回 good → perf+2）+ 直接预防 `risk_burst`。
  **纯防御却间接抬升谈话/晋升。**

### ⑤ 心理修复　`mental_recovery`（耗 1）
- **短程**：`Dignity+2`（单季最大尊严增量）。
- **长程**：Dignity 是晋升门（L1 需 2 → L9 需 7）+ 谈话 +1 权重 + 尊严连零计数。
- **长尾**：Dignity **不受 CAP 限制**（只有 skill/network/output 被钉），可一直有用；
  但若已 `>=6` 则属"纯存款"（0.75 分/点，边际递减）；`+2` 可把 `<=1` 的尊严连零计数**立即打断**。
- **跨区间**：Dignity 是中枢态 → 谈话（good 档倒送 hidden_risk−1）→ 晋升门 → `dignity_crisis`。

### ⑥ 健康恢复　`health_recovery`（耗 1）
- **短程**：`Health+2`。
- **长程**：Health **不是得分变量**（谈话权重仅 0.25，不入 perf、不是晋升门）；唯一角色是**活着**——
  `health<=0` → `health_zero` hp=1 即时出局（眼前一黑 end），**无补救回合**。
- **长尾**：`health>=7` 时再恢复记 0 分（浪费）；`<=3` 必须禁净减健康动作、`<=5` 每季预留 1 点。
- **跨区间**：几乎只连 `health_zero`（二元生死）+ 谈话（0.25，微小）。**最孤立的动作——不参与晋升/perf，只保命。**

### ⑦ 准备汇报材料　`prepare_report_material`（耗 1）
- **短程**：`Output+1 / Dignity+1`（最干净：便宜、双增益、**零负向**、不碰任何失败规则）。
- **长程**：Output 直连 perf（+0.1/点，无软帽）且是高层级首要瓶颈；Dignity 连晋升门+谈话。
- **长尾**：Output 超 CAP 才被钉（早期几乎不会）；每点 output 是**永久可靠**的 perf 贡献与晋升进度。
- **跨区间**：Output → perf → 晋升 perf 门（+ 远离 `consecutive_bad_performance`）；Dignity → 谈话 + 晋升门 + `dignity_crisis`。
  **ROI 最高的动作：同时推进绑定瓶颈(output) 与中枢态(dignity)，无任何副作用。**

### ⑧ 保留体力（不行动）　`no_action`（耗 0）
- **短程**：`{}` 零变化。
- **长程**：体力**直接消失、不累计**；48 月最多 48 点体力，每浪费 1 季最多丢 3 点潜在增益。
- **长尾**：不构成债务，但也不攒缓冲；在"本可埋雷/恢复"的季选择不行动，可能日后走入爆雷/健康死。
- **跨区间**：无（不碰任何态）。**仅在"所有门已达标且超 CAP / health>=7 恢复浪费"时才合理；否则被严格占优。**

---

## 3. 三句话总结

1. **捆绑瓶颈(output)+中枢态(dignity) 的 `准备汇报材料` 与 `人脉维护` 是每季默认首选**；`高强度工作` 是 output 主引擎但必须配 `处理历史埋雷` 与 `健康恢复` 兜底。
2. **最危险的不是单次注入，而是 `hidden_risk` 的静默累积（>=5 引爆，且首次就回写 6 月前 output）**；`skill/network/output` 的超 CAP 投入是另一种"看不见的浪费"。
3. **所有"软"收益（dignity/health/hidden_risk/perf）最终都汇聚到「半年谈话 → 评审 perf 门 → 晋升」这条跨区间链上**——这就是为什么事件选项是主战场、体力只用于评审窗前的精确补量。

---

## 4. ★ 比「高强度工作」更强的 output / skill 来源（主行动槽位，2026-09-25 解码）

**关键架构事实**（解码 `initialization_n_regular/main_event.data` + `events.py`）：
- 每季度有**两件独立的事**：`季度主行动选择`（`decision_type=main_action`，`max_selections=1`，**不耗体力**）与
  `季度体力行动分配`（`decision_type=energy_action`，预算 3 点）。二者不冲突、可同季叠加。
- 另有**月度剧情事件队列**（`long_chain`/`short_chain`，`monthly_event_limit` 控制每月条数）。
- 已确认（记忆）：属性增量约 **90% 来自剧情事件**，体力行动仅约 **10%**。
- ⇒ `高强度工作` 是**体力动作**（耗 2 体力）；`申请关键项目` 是**主行动**（免费槽位）。比较时不在同一预算池里。

### 4.1 主行动池（固定 9 选 1，无前置条件 ⇒ 每季必现，解码 main_event.data）

| 主行动 | status_updates | 对比「高强度工作」 |
|---|---|---|
| **申请关键项目** `apply_key_project` | **Output+2 / Skill+1 / Network+1** | 同 +2 Output，但**多送 +1 Skill +1 Network、零负向、不耗体力** → **严格占优** |
| **申请岗位轮岗** `apply_rotation` | **Skill+2 / Network+1** | 纯 skill 最强；对比体力动作 `技能学习`(+1 Skill, 耗2, −1 Health) 亦占优 |
| 建立导师关系 `build_mentorship` | Skill+1 / Network+2 | skill 次选 |
| 向领导汇报成果 `report_to_leader` | Output+1 / Network+1 / Dignity+1 | 干净 +1 Output |
| 主动争取资源 `seek_resources` | Output+1 / Network+1 | 干净 +1 Output |
| 主动曝光成果 `showcase_results` | Output+1 / Dignity+1 | 干净 +1 Output |

### 4.2 剧情事件里的顶级组合（递归扫描全 291 个含 output/skill 的 choice）

大量 `long_chain` 节点**同时**给 **+2 Output +2 Skill +1 Network +1 Dignity**（如
"评估后给出分阶段交付方案""用量化最坏情况评估作答""给出分阶段付款+ROI 模型""把确认机制+变更留痕固化到流程"等）。
这是 output/skill 的**真正主战场**——遇到即优先选；其代价通常是 `Health−1`，可用体力槽的 `健康恢复` 兜底。

### 4.3 结论

1. **Output**：`申请关键项目`（主行动）给**同样的 +2 Output**，还白送 +1 Skill +1 Network、零负向、不占体力预算
   → **严格优于高强度工作**。每季先把主行动槽占满，output 基础盘即稳。
2. **Skill**：`申请岗位轮岗`（主行动）+2 Skill 是纯 skill 最强；`申请关键项目` 顺带 +1 Skill。
   `高强度工作` 给 **0 Skill**；`技能学习`（体力）才 +1 且 −1 Health、耗 2 体力 → **主行动的 skill 来源全面占优**。
3. **高强度工作的真实定位**：唯一不可替代性是"可用 2 点体力在同季**叠一层**额外 +2 Output"
   （当主行动已选完、体力有富余、且能承受 Health−1/Dignity−1/HiddenRisk+1 时）。
   作为"主力 output 来源"它是最差选择之一。
4. **策略含义（2026-09-25 复核 v7 后修正）**：v7 `decision-policy` §2.1 **已把 `高强度工作` 标注"近乎不用"**，
   且 §三 主行动明确以 `申请关键项目`(+2O/+1S/+1N) 与 `申请岗位轮岗`(+2S/+1N) 为 output/skill 主来源、
   §2.3 注明"skill 主要来源是主行动与剧情、体力只补 O/N 与压风险"。
   **⇒ 本节 §4 的结论与 v7 实际做法高度一致**，并非 v7 的漏洞。
   唯一可商榷点是 `risk-guardian` 约束 5 的保守度（把 `hidden_risk` 控制在 ≤3 且对 ΔRisk≥+2 剧情选项"永远拒收"），
   而真实爆雷线在累积 5——详见 `analysis/v7_vs_conclusions.md` 对比。
