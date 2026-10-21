# Submission: career-sim-agent

面向 CCF BDCI 2026【华为 openJiuwen】职场长程生存与晋升挑战的参赛交付件。

## 运行模式

`manifest.json` 中 `mode` 为 `agent`（单 Agent 模式，挂载任务规划 / 子代理编排 / 技能演进能力，记忆按需读写）。

> 如需多 Agent 协同参谋，可改为 `team`（Leader 统筹拆解，Teammate 按角色并行）。注意 `team` 模式下 Token 开销显著上升，而资源效能是评分维度之一。

## 技能编排

| 顺序 | 技能 | 职责 |
| --- | --- | --- |
| 1 | `situation-awareness` | 每个 `observe` 之后，把原始状态/事件/日志整理成结构化局势快照，并计算「距下一窗口月份数」「各红线余量」 |
| 2 | `risk-guardian` | 依据快照给出本回合的**硬约束**（不可违反）与**降级动作**（已接近红线时的补救） |
| 3 | `decision-policy` | 在硬约束下选择季度体力行动、季度主行动、月度剧情选项，并维护长期晋升路线 |

调用原则：**先知局（1）→ 再设限（2）→ 后决策（3）**。禁止跳过风险校验直接决策。

## 快速验证

```bash
# 在仓库根目录
uv run python -m career_sim_runner validate --submission solution
```

## 目录结构

```
solution/
  manifest.json
  README.md
  design/
    skills_design.md      # 技能设计说明（专家评审依据）
    decision_report.md    # 决策报告（专家评审依据）
  skills/
    situation-awareness/SKILL.md
    risk-guardian/SKILL.md
    decision-policy/SKILL.md
```
