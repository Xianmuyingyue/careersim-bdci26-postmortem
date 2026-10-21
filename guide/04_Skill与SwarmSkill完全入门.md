# 04 · Skill 与 Swarm Skill 完全入门（小白版）

> 本文回答两个问题：**① 一个 Skill 物理上到底由哪些文件组成？② Swarm Skill 又是什么？**
> 所有结论均来自一手材料：`agentskills.io` 官方标准、Swarm Skills 规范论文（arXiv:2605.10052v2）、以及 JiuwenSwarm 0.2.4b3 安装包内的官方 `swarmskill-creator` 技能与其校验脚本。

---

## 零、先记住两句话

1. **Skill = 一个文件夹，里面至少有一个 `SKILL.md`。** 没有代码、没有编译、没有注册表——就是文件夹。Agent 通过读文件来"学会"这项能力。
2. **Swarm Skill = Skill 的一个"多角色团队"扩展。** 物理上就是把 SKILL.md 加上 4 个约定文件（roles/、workflow.md、bind.md、dependencies.yaml），用来描述"谁和谁怎么协作"。它对普通 Agent 向后兼容——不认识的就当普通 Skill 用。

---

## 一、第一层：普通 Skill（单 Agent 技能）

### 1.1 物理形态：一个文件夹

官方的目录规范（来源：agentskills.io）：

```
my-skill/
├── SKILL.md          # 【必选】元数据 + 指令，唯一的强制文件
├── scripts/          # 【可选】可执行代码
├── references/       # 【可选】参考文档
├── assets/           # 【可选】模板、素材
└── ...               # 【可选】任何其他文件或子目录
```

**关键点：只有 `SKILL.md` 是必选的。** 其余目录都是"需要时才加"。一个只有 `SKILL.md` 的 20 行技能，是完全合法、可以发布、可以参赛的 Skill。

### 1.2 SKILL.md 由两个部分组成

```markdown
---
name: my-skill                    ← 第 1 部分：YAML frontmatter（给程序读）
description: 一句话说明做什么、什么时候用
---

# My Skill                        ← 第 2 部分：Markdown 正文（给模型读）

## 何时使用
## 处理规则
## 输出格式
```

| 部分 | 谁来读 | 作用 |
| --- | --- | --- |
| **frontmatter**（`---` 之间的 YAML） | **框架代码**（机械解析） | 决定这个技能"什么时候被想起来" |
| **正文**（Markdown） | **模型**（语义理解） | 决定这个技能"具体怎么做" |

**frontmatter 里最重要的就是 `name` 和 `description`：**
- `name`：技能标识，通常与文件夹名一致（kebab-case）
- `description`：**这是触发器**。框架只把这一行注入模型上下文，模型据此判断"当前任务要不要用这个技能"

> 本赛题的实际校验规则（`career_sim_runner/skill_contract.py`）比通用标准更简单：只要求 `SKILL.md` **以 `---` 开头、有闭合 `---`、frontmatter 是合法 YAML、且 `name` 与 `description` 非空**。就这四条。

### 1.3 最小可用示例（真实存在，来自仓库单元测试）

```markdown
---
name: dummy-skill
description: Fixture skill used in unit tests.
---

Dummy content
```

**三行 frontmatter + 一行正文，就是一个合法 Skill。** 这就是"物理层面"的全部门槛。

### 1.4 为什么只有几句话也能工作？——渐进式披露（Progressive Disclosure）

技能不是一次性全塞进上下文，而是分三层按需加载：

| 阶段 | 何时 | 加载什么 | 上下文成本 |
| --- | --- | --- | --- |
| **① 发现 Discovery** | Agent 启动时 | 只加载**所有技能**的 `name` + `description` | 极低（每个技能几十到一百多字符） |
| **② 激活 Activation** | 任务匹配某个技能的 description | 读入该技能**完整的 SKILL.md 正文** | 中等 |
| **③ 执行 Execution** | 按正文指示做事时 | 按需运行 `scripts/`、读取 `references/` | 按需 |

**这就是为什么正文可以写得很长而不怕浪费**——它只在真正用到时才进上下文。也解释了为什么 `description` 必须写得准：写错了技能永远不会被激活。

### 1.5 安装后，技能物理上落在哪里？

以本赛题为例，`make play` 时 runner 会做这些事（源码：`career_sim_runner/install.py`）：

1. **清空**实例的技能工作区、todo、历史、会话、团队、记忆目录
2. 把 `solution/skills/<每个技能>/` **整个目录复制**到 JiuwenSwarm 的技能目录：
   ```
   ~/.jiuwenswarm-instances/career_emu/agent/workspace/skills/<技能名>/
   ```
3. 写 `skills_state.json` 注册这些技能（标记 `source: project`、`enabled: true`）
4. 渲染 `IDENTITY.md`（把技能列表 + 你 `manifest.json` 里的 `instruction` 填进模板），写到：
   ```
   ~/.jiuwenswarm-instances/career_emu/agent/workspace/IDENTITY.md
   ```
   > 注释原文：*"The content persists in the system prompt on every model call via ContextAssembleRail, surviving context compression."* —— 也就是说 **IDENTITY.md 每轮都在 system prompt 里，不会被上下文压缩丢掉**。

**所以"提交技能"本质上就是提交一个文件夹，框架会把它复制到工作区并注册。**

### 1.6 JiuwenSwarm 自带 19 个技能，可以直接拿来"读范文"

安装包里就有现成例子（`jiuwenswarm/resources/agent/workspace/skills/`）：

| 技能 | 文件数 | 体积 | 特点 |
| --- | --- | --- | --- |
| `skill-creator` | 18 | 280 KB | 教你怎么造技能；用 `agents/`、`scripts/`、`assets/`、`references/`、`eval-viewer/` |
| `ppt-creation` | 95 | 4.4 MB | 重资产型技能：`base/`、`components/`、`references/`（含图片）、`scripts/` |
| `swarmskill-creator` | 13 | 220 KB | **造 Swarm Skill 的官方技能**，附模板与校验脚本 |

**目录命名惯例统计**（19 个技能中）：`scripts/` 出现 9 次、`references/`（或 `reference/`）出现 6 次、`templates/`、`assets/`、`agents/`、`config/`、`components/` 各若干。

> 这就是"经验法则"：**`scripts/` 放代码，`references/` 放长文档，`assets/` 放素材，`templates/` 放骨架文件。** 没有强制规定，纯粹是社区惯例。

---

## 二、第二层：Swarm Skill

### 2.1 它是什么

**Swarm Skill = 在 Anthropic Skills 标准上做"多 Agent 语义扩展"的可移植规范。**

来源：openJiuwen 团队与中国人民大学高瓴人工智能学院的规范论文 *《Swarm Skills: A Portable, Self-Evolving Multi-Agent System Specification for Coordination Engineering》*（就是官方给你的那份 PDF）。

**它想解决的问题：** 单 Agent 技能已经是可分发资产了，但**多 Agent 的协作协议**还锁在各框架内部（CrewAI 的 Python 模板、MetaGPT 的 SOP、AutoGen 的 GroupChat 配置）——换个框架就得重写，而且协作经验用完就丢。

**它的解法：** 把"谁和谁、按什么依赖、受什么约束地协作"这件事，**从运行时代码里抽出来，写成纯 Markdown 的可分发资产**。规范原文原话：

> *"a description format, not a runtime"*（这是一种描述格式，不是运行时）

### 2.2 物理结构：五件套 + 1 个自动生成文件

```
my-team-swarm/
├── SKILL.md            # 【必选】入口：frontmatter 声明多 Agent 语义 + 正文总览
├── roles/              # 【必选】每个角色一个文件，如 roles/reviewer.md
│   ├── <id-1>.md
│   └── <id-2>.md
├── workflow.md         # 【必选】Mermaid 流程图 + 分步协议 + 质量门
├── bind.md             # 【必选】资源预算 + 行为约束 + 失败处理
├── dependencies.yaml   # 【必选】外部技能与工具清单
└── evolutions.json     # 【运行时自动追加】自演进经验记录
```

**前 5 个是作者必须写的，第 6 个是系统运行时自动往里追加的。**

> 例外：**"纯脚本 SwarmFlow"形态**只需要 `SKILL.md` + `scripts/workflow.py`（把所有提示词和编排逻辑写进那个 Python 脚本），这是给"我要可执行编排"而不是"我要角色规范文档"的场景准备的。

### 2.3 SKILL.md 的 frontmatter 多了什么

在普通 Skill 的 `name` / `description` 之上，Swarm Skill 的 frontmatter 扩展了多 Agent 语义：

```yaml
---
name: my-team-swarm                # 必须等于目录名
description: |                     # 3 行结构：WHAT / WHEN / NOT，≤500 字符为目标
  3-role adversarial PR review (Reviewer + Critic + Architect) that surfaces inter-role conflicts instead of papering over them.
  Use when reviewing a pull request that needs independent multi-perspective scrutiny.
  Do NOT use for trivial single-file lint fixes.
version: "0.1"                     # 必填
kind: swarm-skill                  # ★ 判别器：框架据此识别"这是 Swarm Skill"
roles:                             # ★ 角色数组（至少 1 个）
  - id: reviewer                   # 角色 id，必须与 roles/reviewer.md 文件名一致
    kind: ai_agent                 # ai_agent 或 human_agent
    purpose: 逐行审查代码正确性与边界条件          # ≤150 字符硬上限
    skills: [code-review]          # 该角色需要的技能
    tools: [git]                   # 该角色需要的工具
  - id: critic
    kind: ai_agent
    purpose: 专门寻找论据漏洞与过度自信的结论
    skills: []
    tools: []
---
```

**框架代码只解析 frontmatter 里的这些元数据来"编排环境"；正文和其余文件交给模型按需读取。**

**校验器实际强制的规则**（源码：`swarmskill-creator/scripts/validate_swarmskill.py`）：

| 类别 | 规则 |
| --- | --- |
| 结构 | 5 个文件必须齐全；`roles/<id>.md` 必须与 `roles[].id` 一一对应；不能有孤儿角色文件 |
| frontmatter | `name` / `description` / `version` / `kind` / `roles` 都存在；`kind` 必须等于 `swarm-skill`；`name` 必须等于目录名 |
| roles[] | 每项必须有 `id`、`kind`（`ai_agent`/`human_agent`）、`purpose`（**≤150 字符硬上限**） |
| 正文段落 | SKILL.md 正文必须有 `## Workflow` + `## Roles` + `## Files` |
| roles/*.md | 每个角色文件必须有 5 个段落，且 `## Identity` 的第一行必须是 **`> *"一句话座右铭"*`** 格式 |
| workflow.md | 必须有 `## Overview` + `## Detailed Steps` + `## Acceptance Criteria`，且至少含一个 mermaid 代码块 |
| bind.md | 必须有 `## Resource Constraints` + `## Behavioral Constraints` + `## Failure Handling` |
| 跨文件一致性 | SKILL.md 里每个 `roles[].skills` / `roles[].tools` 都必须在 `dependencies.yaml` 里出现 |

> ⚠️ **一处文档与实现的差异**：规范论文里提到 frontmatter 有一个 `teammate mode` 字段（build / plan 模式）。但在 JiuwenSwarm 0.2.4b3 实际安装的校验脚本中，**强制字段是 `name` / `description` / `version` / `kind` / `roles`，并未校验 `teammate_mode`**。以实际校验脚本为准。

### 2.4 三个设计巧思（理解它们就理解了 Swarm Skill 的价值）

**巧思一：优雅降级（Graceful Degradation）**
因为底层 Anthropic 标准允许 `additionalProperties: true`，**不支持多 Agent 的宿主 Agent 遇到 Swarm Skill 不会报错**——它会忽略 `kind` 和 `roles[]`，把它当成普通单 Agent 技能，顺序地把各个角色跑一遍。所以 Swarm Skill 是**向后兼容**的。

**巧思二：零适配器部署（Zero-Adapter Deployment）**
整个协作协议只用 Markdown + 通用格式表达，唯一的结构化元数据就是 frontmatter。部署方式就是"把文件夹复制到宿主的 skills/ 目录"，不需要翻译层。**唯一的前提是宿主支持"递归读文件"和"派生子 Agent"这两个原生能力。**

**巧思三：自演进语义内建（evolutions.json）**
这是理论上最特别的一点：**规范把"自我改进"写成了格式的义务**。每次跑完，系统把遇到的协作摩擦（角色职责重叠、往返冗余、任务顺序不当）蒸馏成一条 Evolution Record 追加到 `evolutions.json`：

```json
{
  "id": "evo_20260430_001",
  "context": "Budget Reviewer 在从数字审计切换到创意写作时出现上下文切换与延迟。",
  "change_directive": {
    "target_files": ["roles/copywriter.md", "workflow.md"],
    "action": "SPLIT_ROLE",
    "content": "新建专职『文案专家』角色负责社媒分享，并让文案与最终预算审核并行。"
  },
  "metrics": { "effectiveness_score": 0.5, "utilization_rate": 0.0, "freshness_decay": 1.0 }
}
```

三条打分指标：
- **Effectiveness (E)** — 这条补丁的实际效果（用 Beta(1,1) 先验做贝叶斯平滑）
- **Utilization (U)** — 补丁被采纳率；Leader 老是无视某条指令，U 就衰减
- **Freshness (F)** — 时间衰减（论文举例半衰期 90 天），让陈旧优化自然淘汰

分数 **S = wE·E + wU·U + wF·F**，低于阈值就沉底被忽略。记录积累到一定量（论文举例 ≥10 条）会触发三种治理动作：
- **SIMPLIFY** — 剪枝/合并/改写进化记录
- **REBUILD** — 把补丁沉淀回 SKILL.md 正文，然后清空 evolutions.json
- **ROLLBACK** — REBUILD 搞砸了可以回滚到任意历史版本

**关键：`evolutions.json` 是运行时产物，你交包时不需要手写它。**

---

## 三、两者对比

| 维度 | 普通 Skill | Swarm Skill |
| --- | --- | --- |
| **必选文件** | `SKILL.md`（1 个） | `SKILL.md` + `roles/` + `workflow.md` + `bind.md` + `dependencies.yaml`（5 件套） |
| **frontmatter 关键字段** | `name`、`description` | 上述 + `version`、**`kind: swarm-skill`**、**`roles[]`** |
| **表达什么** | 一个 Agent 怎么做一件事 | 多个 Agent 怎么分工协作 |
| **核心文件** | SKILL.md 正文 | `workflow.md`（流程图 + 质量门） |
| **自演进载体** | 无（靠宿主通用机制） | `evolutions.json`（规范内建的进化经验） |
| **在赛题里怎么启用** | `manifest.json` 里 `mode: "agent"` | `manifest.json` 里 `mode: "team"` |
| **Token / 时间成本** | 低 | 显著更高（多角色来回通信） |
| **官方作者工具** | `skill-creator` | `swarmskill-creator`（含模板 + 校验脚本） |

> ⚠️ **注意区分**：`manifest.json` 的 `mode`（赛题层面决定 Agent 用单角色还是团队运行）与 Swarm Skill 的 `kind`（技能文件层面的类型标记）是**两个不同层次**的概念。赛题用 `mode: "team"` 启用团队协作模式；而 Swarm Skill 是把协作协议写成可分发文件的格式。

---

## 四、本赛题该选哪个？——给你的决策建议

### 官方立场

赛题原文：*"如需多 Agent 协同参谋，可关注 Swarm Skill 标准"* —— 措辞是**"如需"**，即**可选，非必需**。

### 客观对比

| 方案 | 优势 | 代价 | 适合情形 |
| --- | --- | --- | --- |
| **普通 Skill + `mode: "agent"`** | Token 省、延迟低、上下文单一、调试简单 | 单点推理深度有限 | **推荐起点**。本赛题每回合信息量小（1 个事件 + 2–4 个选项）但回合极多，串行决策性价比高 |
| **Swarm Skill + `mode: "team"`** | 可做"红队/蓝队"对抗式审议；角色隔离避免单一视角盲区 | Token 与耗时可翻数倍；**而"资源效能"是评分维度之一** | 风险判断需要多视角对抗时；且你已把单 Agent 基线做实 |

### 我的建议（三阶段）

1. **先用普通 Skill + `mode: agent` 把基线做扎实**——三份正交技能（局势感知 / 风险控制 / 决策策略）已经足够，这是性价比最高的路径。
2. **如果基线已经能稳满 48 个月并把职级推到 L4–L5**，再考虑是否升级到 Swarm Skill 做多角色。
3. **只有当你确认"多角色带来的分数提升 > Token 成本带来的资源效能损失"时，才切换到 `mode: "team"`。** 官方规范里也明确写了 Stage 0 的判断标准：*"Swarm Skill 只在三种情况下才正当——对抗性盲区、可并行分解、带硬质量门的专业流水线。否则应推荐单 Agent 技能。不要因为新鲜而造它。"*

### 关于自演进的现实提醒

`evolutions.json` 的自演进机制**在本赛题中价值有限**：单次提交只跑一局（竞赛模式下 `new_game` 只能调一次），48 个月的进化次数不足以积累有意义的补丁。真正决定成绩的仍是**你手写的策略质量**。

---

## 五、常见误解纠正

| 误解 | 事实 |
| --- | --- |
| "Skill 要写代码才能生效" | 不需要。只有一个 `SKILL.md` 也是完整 Skills。代码（`scripts/`）是可选增强 |
| "Skill 是一个 API 或服务" | 不是。它就是一个文件夹，Agent 靠**读文件**学会技能 |
| "正文越长越好" | 正文只在被激活时加载，但**每个技能的 description 每轮都占上下文**，所以要精炼 |
| "Swarm Skill 是另一种技能格式，不能混用" | 它可以和普通 Skill 混在同一包内。本赛题提交包允许 `skills/` 下同时存在两者 |
| "交了 Swarm Skill 就一定跑多 Agent" | 是否跑多 Agent 由**宿主 Agent 能力 + `manifest.json` 的 `mode`** 决定；不支持的宿主会优雅降级成单 Agent |
| "`evolutions.json` 要我手写" | 不用，那是运行时产物 |

---

## 六、你现在需要决策的点

1. **路线选择**：先做**单 Agent（`mode: agent`）**，还是直接上 **Swarm Skill（`mode: team`）**？
   → 建议：**先单 Agent**。理由见第四节。
2. **技能颗粒度**：保持现有的 3 个正交技能，还是拆得更细（例如把"局势感知"拆成"状态读取"+"红线计算"）？
   → 建议：**保持 3 个**。每个 SKILL.md 每轮都会载入 description，拆太细会持续占用上下文。
3. **要不要给技能配 `scripts/`**？
   → 建议：**本赛题不需要**。策略是纯规则推理，没有需要反复执行的确定性计算。加脚本反而增加复杂度和被误判的风险。

---

## 附：一手材料索引

| 材料 | 位置 |
| --- | --- |
| Agent Skills 官方标准 | https://agentskills.io |
| Swarm Skills 规范论文（14 页全文） | `官方资料/Swarm-Skill标准-2605.10052v2.pdf`，纯文本版 `官方资料/swarm-skill.txt` |
| 普通 Skill 官方作者工具（含 18 个文件范例） | `官方资料/pkg/jws/jiuwenswarm/resources/agent/workspace/skills/skill-creator/` |
| **Swarm Skill 官方作者工具 + 模板 + 校验脚本** | `官方资料/pkg/jws/jiuwenswarm/resources/agent/workspace/skills/swarmskill-creator/` |
| Skill 最小合法示例 | `CareerSim-BDCI26/tests/fixtures/solution/skills/dummy-skill/SKILL.md` |
| 本赛题的 Skill 校验规则 | `CareerSim-BDCI26/career_sim_runner/skill_contract.py` |
| 技能安装逻辑（复制到哪、注册到哪） | `CareerSim-BDCI26/career_sim_runner/install.py` |
| 19 个内置技能实物范例 | `官方资料/pkg/jws/jiuwenswarm/resources/agent/workspace/skills/` |
| Swarm Skill 社区市场 | https://swarmskills.openjiuwen.com/ |
