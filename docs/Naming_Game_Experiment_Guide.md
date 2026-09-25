# LLM 命名博弈实验：研究假设、软件功能、操作步骤与原理

**审阅稿 v0.1** · 2026-09-24 · 对应软件版本：GitHub `Hector-Liu/AI-simulation-1st-edition`，commit `0c14187`

> **怎么审阅这份文档**
>
> - 标有 **【待确认】** 的地方需要你拍板。第 10 节把它们集中列成清单。
> - 标有 **【已实现】**、**【仅导出数据】**、**【未实现】** 的地方说明软件目前能做到哪一步。
> - 设计依据是已批准的 `docs/SPEC-naming-game-v1.0.md`。实现中做的具体取舍见 `docs/IMPLEMENTATION_NOTES.md`。两者和本文不一致时，以代码行为为准，并请指出来。

---

## 1. 研究问题

**核心问题：** 一群 LLM 智能体只通过局部、私有、两两之间的互动，能否形成群体层面的惯例（Lewis convention）？有没有任务奖励，会不会改变这个结果？

有两件事必须分开，因为它们的来源不同：

| | 含义 | 来源 | 是否算"涌现" |
|---|---|---|---|
| **趋同倾向** | 模型倾向于重复自己上次的选择，或模仿对方 | 主要来自预训练（上下文模仿） | **不算**。证明它存在是必要的，但它不是涌现的证据 |
| **哪个惯例胜出** | 最终胜出的标签和个体先验无关，并且不同种子得到不同结果（对称性破缺、路径依赖） | 由互动历史产生 | **这才是涌现的主张** |

软件**从不**设置"是否涌现"这类标记，也不让 LLM 做这个判断。所有指标都由程序计算，最后由研究者对照第 7.5 节的清单做结论。

---

## 2. 研究假设及其操作化

| 假设 | 内容 | 用什么检验 | 软件支持 |
|---|---|---|---|
| **H1**（Study A） | 有奖励、有记忆、随机配对时，群体状态的归一化熵明显低于无记忆基线，且多数种子达到共识阈值 | 每轮 `state_entropy_norm`；每次运行的 `consensus` 和 `T_consensus` | 【已实现】计算和比较作图。混合模型拟合【未实现】，需导出后在 R/Python 中做 |
| **H2**（Study B） | 没有奖励、只有自身互动记忆时，熵仍然低于无记忆基线（双侧检验：不收敛同样是可发表的结论） | 同上，对比 Study B 的关键格与先验基线格 | 同上 |
| **H3**（两个研究） | 伙伴暴露（`partner_count_H`）对下一次选择的预测力，超出标签先验、显示位置和自己上次选择 | 条件 logit：`U = β1·own_prev + β2·own_count_H + β3·partner_count_H + β4·log p0 + β5·position + β6·reward×partner_count_H` | 【仅导出数据】每次运行可下载 `choice-model.csv`，模型需在外部拟合 |
| **H4**（两个研究） | 不同种子的获胜标签分布，比"由先验预测的零模型"更分散。如果集中在先验最高的标签上，说明那是共享先验，不是涌现 | 获胜标签分布的熵、P(获胜标签 = argmax p0)，p 值来自零模型模拟 | 【部分实现】Results 页可按种子汇总获胜标签；规则型零模型可以跑。10,000 个种子的零分布模拟【未实现】 |
| **H5**（Study A 拓扑） | 星形网络通过中心节点收敛（中心化）；社区拓扑比随机配对更容易出现稳定的多惯例并存 | 按拓扑比较 `T_consensus` 和 `fragmentation` 率 | 【已实现】三种拓扑都能跑，指标都会计算 |

**集体偏差（collective bias）：** 如果某个标签在个体层面只是略受偏好，却在群体中被大幅放大，这属于集体偏差（Ashery 等 2025 的意义）。它会被报告出来，但不算"涌现失败"。

---

## 3. 实验设计

### 3.1 Study 0：先验校准（必须最先运行）

- **目的：** 测量模型在没有任何社会信息时，对每个标签的偏好 p0(label) 和对显示位置的偏好 p0(position)。
- **设置：** 20 个"孤立"智能体，每人做 20 次选择。没有伙伴，没有记忆，没有奖励。标签顺序每条提示词独立打乱。
- **闸门规则：** 满足以下任一条件时，该标签集会被**标记**：
  - 某个标签的 p0 > 0.25；
  - 与均匀分布的卡方检验 p < 0.01，且最大/最小频率之比 > 3。
- **标记后怎么办（D5）：** 先重新生成一次标签集。如果仍然有偏，就保留它，并把 log p0 作为协变量。软件不会在未提示的情况下继续。
- **软件：** 预设 "Study 0 · prior calibration"。运行结束后，Results 页会显示 p0 柱状图、闸门结果，以及可直接复制的 `p0_smoothed`（加 0.5 平滑）。把它粘贴到后续运行的 Advanced → Label prior p0，规则型零模型的首轮选择就会用上它。

### 3.2 Study A：有奖励的局部命名博弈

固定设置：`reward = local_match`，`feedback = numeric_score`（记忆中显示得分），`memory = own_interactions_only`，`content = own_and_partner`。

| 因素 | 水平 |
|---|---|
| 拓扑 | random_dyad（随机配对）、star（星形）、community（社区） |
| 记忆长度 H | 1、5、10 |
| 种子数 | (random, H = 5) 为 30 个，其余每格 10 个。种子嵌套在标签集中，均匀分配 |
| 可选：坚定少数派 | 达到共识后（或第 50 轮仍未收敛时）加入，比例 5 % 和 15 %。建议 N = 48 |

### 3.3 Study B：无任务奖励（核心 2×2 与对照）

核心 2×2：随机配对，H = 5，每格 30 个种子。

| | 无记忆 | 有记忆（自己 + 伙伴的选择） |
|---|---|---|
| **无奖励** | 先验基线 | **关键格：会不会自发收敛？** |
| **有奖励** | **焦点（focal-point）对照**：只靠共享先验能协调到什么程度 | 与 Study A（random, H = 5）共用 |

对照组：

| 对照 | 设置 | 用途 | 软件 |
|---|---|---|---|
| **B+1** | 无奖励，记忆里只显示自己过去的选择 | 分离"自我坚持"。预期个体会锁定，但群体收敛不应超过基线 | 【已实现】预设 "B+1 · own choices only" |
| **B+2** | 有奖励，记忆里只显示自己的选择和得分 | 只有强化信号，看不到伙伴的标签 | 【已实现】预设 "B+2 · own choices + points" |
| **B+3** | 回放另一次运行中的伙伴标签（yoked） | 切断"群体行为 → 所见内容"的反馈回路 | 【未实现】配置校验会直接拒绝 |

规则：无奖励臂的反馈**只能**是 `choices_only`。带"相同 / 不同"标记的反馈属于稳健性因素，不能作为无奖励臂。软件要求勾选 `robustness_cell` 才允许使用它。

### 3.4 计算零模型（不调用 LLM）

零模型和 LLM 运行使用**完全相同**的调度器、记忆缓冲区和指标。唯一区别是由规则代替模型做选择：

| 策略 | 规则 |
|---|---|
| `prior_sample` | 每次独立按 p0 抽样 |
| `voter(q)` | 以概率 q 复制上一个伙伴的标签，否则重复自己的上次选择。首轮按 p0 抽样 |
| `majority_H` | 选择记忆中出现最多的伙伴标签，也就是经典的命名博弈规则。平局时，若自己上次的选择在平局标签中就选它，否则按 p0 加权抽样。记忆为空时按 p0 抽样 |
| `scripted_fixed` | 永远选择指定标签（坚定少数派使用） |

规则策略只能读取 LLM 在提示词中能看到的信息。例如在 own_only 条件下，它们看不到伙伴的标签。

**已验证：** `majority_H`（N = 24，H = 5，100 轮）在 1000 个种子中 100 % 达到共识。这个结果已写成回归测试。

### 3.5 时间轴

- `round` 指一次调度步骤。
- `t_pc` 指人均累计互动次数。随机配对和社区拓扑下 t_pc = round。星形拓扑每轮只有一对：中心节点 t_pc = round，叶节点约为 round / (N − 1)。
- 跨拓扑比较必须用 t_pc。Results 页的比较图可以切换横轴。
- **D2：** 星形条件保持和其他条件相同的轮数，另加一个按 t_pc 放大轮数的稳健格。软件不会自动放大，需要手动把 `n_rounds` 调大。

### 3.6 预实验与预注册流程

1. 对所有标签集运行 Study 0。
2. 为所有格运行零模型。
3. LLM 预实验：每个核心格 2 个种子，`n_rounds = 300`，记录各格的 T_consensus 或平台期。
4. 确定正式运行的轮数：`n_rounds = max(3 × 平台期 t_pc 中位数, 100)`，被比较的各格使用同一个值。
5. 冻结模板、标签集、配置 schema 和分析脚本，然后预注册。
6. 正式运行。预实验数据**不能**与正式数据合并。

---

## 4. 软件架构与原理

### 4.1 为什么不用 Concordia

旧的 Concordia 构建器会破坏 brief 里的不变量：

- 观察内容由 Game Master 的 LLM 根据全局记忆改写，无法排除信息泄漏；
- 智能体提示词前面固定加了一段角色扮演指令，包含 "social science experiment"；
- 无法精确控制和记录发给模型的提示词；
- 无法设定随机种子；
- 每次行动要调用 4–5 次 LLM。

因此新软件是一个**独立的协议引擎**。每次选择只调用一次模型，只发一条 user 消息，没有 system prompt，发送的文本逐字记录。

### 4.2 一轮之内发生什么（系统自动执行）

```
第 t 轮开始
 ├─ ① 判断坚定少数派是否在本轮加入（只在启用时）
 ├─ ② 配对：按拓扑生成本轮的配对，随机数只取决于 (seed, 轮次)
 ├─ ③ 为本轮所有参与者生成提示词：只读取每个智能体自己的记忆，标签顺序逐条打乱
 │     └─ 每条提示词都做禁用词检查，命中则整个运行立即停止（fail-closed）
 ├─ ④ 并发调用模型（最多 max_concurrency 个）。规则型智能体直接按规则选择
 │     └─ 严格解析输出；无效就用同一条提示词重试 1 次；仍无效则该配对作废
 ├─ ⑤ commit_dyad：给配对的双方各追加一条记录，更新各自的得分（其他人一律不变）
 ├─ ⑥ 写入分析数据：calls.jsonl、interactions.csv、population.csv
 └─ ⑦ 计算本轮群体指标（只写入分析数据，绝不返回给智能体）
```

所有提示词都在任何一个选择产生**之前**生成完。所以一个人的提示词里不可能出现伙伴本轮的选择（同时性），这一点有测试验证。

### 4.3 不变量及其保证方式

| 不变量 | 代码层面怎么保证 | 验证它的测试（SPEC §8） |
|---|---|---|
| 智能体只记得自己参与的互动 | 唯一的记忆写入函数是 `commit_dyad()` | 1 记忆隔离；14b 单一写入者（静态检查） |
| 提示词中没有其他配对的信息，也没有群体统计 | 唯一的提示词构造函数 `build_agent_prompt()` 只读取智能体自己的缓冲区 | 2 提示词审计；3 无全局统计 |
| 没有诱导性词语 | 模板中不含这些词；另外发送前逐条检查 | 3、3b、3c（检查到泄漏会中止运行） |
| 奖励开关干净 | 无奖励时 points / score / reward 等词会被拦截 | 4 奖励开关 |
| 标签顺序每条提示词独立随机 | 每条提示词单独打乱顺序 | 5 顺序随机化（二项分布检验） |
| 可复现 | 随机数按 (seed, 用途, 轮次[, 智能体]) 派生 | 6 重放；12 续跑 |
| 两条奖励臂只差奖励文本 | 两臂共用同一个交互段落 | 9 两臂对称（逐字对比） |
| 中心节点没有特殊提示词 | 所有智能体使用同一个模板 | 11 中心节点中立 |
| 智能体读不到分析数据 | `agents.py` 和 `prompts.py` 不导入 `store` / `metrics` | 14 存储隔离 |

目前共有 55 项自动测试，全部离线（mock 模型）运行，全部通过。按规定，任何付费运行之前都必须先通过这些测试。

### 4.4 提示词模板（v1，逐字）

基础模板：

```
You are participant {agent_id}.
A situation is labeled {stimulus_id}.
{interaction_block}{payoff_block}Choose exactly one label from this list:
{shuffled_labels}

Reply with only the label.

Your own recent interactions, if any:
{own_buffer_or_none}
```

交互段落。**两条奖励臂都有**；只有 Study 0 的孤立条件没有：

```
You are paired with another participant, who chooses from the same list at the same time.
After both choices are submitted, each of you is shown the other's choice.
```

奖励段落，**只出现在有奖励臂**。第五行只在显示累计得分时出现：

```
Scoring rule for this pairing only:
If you and the other participant choose the same label, you receive {match_payoff} points.
If you choose different labels, you receive {mismatch_payoff} points.
Your objective is to maximize your own points across pairings.
Your cumulative points so far: {total}
```

记忆行的格式（只显示相对顺序 "Latest interaction"、"2 interactions ago"…，不显示绝对轮次）：

| 条件 | 格式 |
|---|---|
| 自己 + 伙伴，只显示选择 | `- Latest interaction: you chose Laba; the other participant chose Zago.` |
| 自己 + 伙伴，显示得分 | `… the other participant chose Zago; you received -50 points.` |
| 自己 + 伙伴，相同 / 不同（稳健性） | `… the other participant chose Zago (different labels).` |
| 只显示自己 | `- Latest interaction: you chose Laba.` |
| 只显示自己 + 得分 | `- Latest interaction: you chose Laba; you received 100 points.` |

附录 A 给出了各条件实际生成的完整提示词。

**【待确认 1】own_only 对照的提示词自相矛盾。** 为了让两条奖励臂只差奖励文本，交互段落是共用的，其中写着 "each of you is shown the other's choice"。但在 own_only 条件下，伙伴的选择从不显示，所以智能体读到的是一个没有兑现的承诺。可选方案：

- (a) 保持现状，把它作为已知局限报告；
- (b) 给 own_only 条件单独写一个交互段落，例如 "You are paired with another participant, who chooses from the same list at the same time."（去掉第二句）。

方案 (b) 在 own_only 条件内部仍然保持两臂对称，但 own_only 与 own_and_partner 之间会多出一处文本差异。

### 4.5 标签

- 三组冻结的标签集，每组 10 个 CVCV 形式的无意义词，三组互不重叠：
  - L1：Laba Zago Gibo Kepe Niru Mune Neba Vapa Pubi Soru
  - L2：Limi Kife Fiza Bipe Sefe Mava Pulo Vago Ziru Poko
  - L3：Tuzu Vodo Nufe Dipa Gimu Fete Situ Tero Varo Vifi
- 过滤规则：
  - 不是英文词、常见人名或品牌；
  - 不包含禁用词子串；
  - 两两编辑距离 ≥ 2，前两个字母各不相同；
  - 不含字母顺序串（如 d-e-f），不是叠音（如 Baba）。
- 标签集在所有种子之间**固定不变**，这是"哪个标签胜出"能跨种子比较的前提（SPEC R4）。显示顺序则每条提示词重新打乱。
- **【待确认 2】** 过滤只查了英文词表，没有查其他语言。例如 *Soru* 在土耳其语里是"问题"的意思。预注册前请人工检查三组标签。

### 4.6 禁用词检查：原理

研究要回答的是惯例能否**仅凭两两互动**产生。以下三类词会让这个结论失效：

1. **暗示目标的词**：agree、coordinate、cooperate、consensus、converge、align、success、fail、common language。模型等于被告知"应该趋同"，结果就变成了服从指令。
2. **泄露群体信息的词**：majority、most、popular、winning、the group、everyone、population、other participants，以及任何"数字 + agents / participants / %"。智能体会得知全局状态，这违背了"只有局部信息"的前提。
3. **无奖励臂里的激励词**：points、score、reward、payoff、win、lose。出现它们就等于给无奖励臂偷偷加了激励，2×2 对比随之失效。

模板本身已经避开了这些词。自动检查是一道**保险**，防的是以后改模板、出现新的配置组合或渲染数据时意外混入这些词。检查结果写进每次运行的 `leakage_report.json`，作为 SPEC §7.6 第 6 条的审计证据。

**局限：** 词表只能拦字面匹配，拦不住语义上的暗示。例如交互段落本身就在暗示"对方的选择很重要"，这是命名博弈本身决定的，无法去掉。它的影响由 own_only 对照和零模型来界定。

### 4.7 解析与无效输出

- 解析时只去掉首尾空白、一层引号或反引号、一个句末句号，然后不区分大小写，必须与**恰好一个**标签完全相同。
- 下列输出都算无效：带解释的句子、两个标签、空输出、不在标签池中的词、Markdown 加粗（如 `**Laba**`）。系统**从不**把无效输出映射到最接近的标签。
- 输出无效时，用同一条提示词重试一次（记为 attempt 2）。仍然无效，该配对**作废**：不写入双方的记忆，也不计分；原始文本照样保存。
- 标记与排除（D3）：一次运行中，重试后仍无效的比例超过 2 % 会被标记，超过 5 % 应当排除。
- **实测：** Haiku 冒烟测试共 37 次调用，其中 1 次首答是一段分析文字，重试后正常作答，最终无效率为 0。

### 4.8 坚定少数派

- **加入时机：** 共识窗口第一次达成后的下一轮，或到达 `start_round`（默认 50），取先到者。也可以设置为固定轮次加入。
- **固定标签：** 前 20 轮中使用次数最少的标签（标签池中的每个标签都参与计数），平局随机决定。
- **成员：** 随机抽取 round(frac × N) 个智能体。他们改为规则型（`scripted_fixed`），不再调用模型，但提示词仍会生成并记录。对其他智能体来说，他们和普通智能体没有区别。
- **指标：** 同时报告包含和排除少数派的两个版本。
- 星形拓扑不能与少数派同时使用。

### 4.9 随机性与可复现性

- 每一次随机抽取都来自 `SeedSequence(seed, spawn_key = (用途, 轮次[, 智能体]))`，用途分为配对、顺序、少数派、平局和策略五类。
- 所以相同的种子加相同的配置，会得到相同的配对、标签顺序、少数派分配和规则型选择，与调用的完成先后无关。
- 中断后续跑的结果，与不中断运行完全一致。这些都有测试验证。
- LLM 自身的输出仍然是随机的（温度 > 0）。每次调用都会记录生效的温度和模型版本。
- `config_hash` 不包括 `run_id` 和备注，所以同一设计、同一种子的运行共享同一个 hash。

---

## 5. 操作步骤：你来做的 vs 系统自动完成的

### 5.1 总流程

| 阶段 | 你的操作 | 系统自动完成 |
|---|---|---|
| **启动** | 在访达中双击 `一键启动.command` | 首次运行时安装 Python 环境；从旧项目导入 Anthropic 密钥；启动服务；打开浏览器 `http://127.0.0.1:8765`；如果已经在运行，直接打开页面 |
| **① Setup：选条件** | 点一个预设卡片 | 填好该条件的全部参数；推导 Experiment ID；显示一句话的设计摘要 |
| **② 人数与轮数** | 按需修改人数、轮数、种子、标签集、配对方式 | 显示标签集包含的标签；只在需要时显示拓扑参数 |
| **③ 记忆** | 开关记忆，选择记录内容和 H | 孤立条件下自动关闭记忆 |
| **④ 奖励** | 选择有无奖励、得分值和记忆记录中包含的内容 | 自动禁用不合法的选项（例如无奖励时不能显示得分） |
| **⑤ 选择者** | 选 Claude 模型 / 离线 mock / 规则型零模型；选具体模型和温度 | 对不接受温度的模型禁用温度输入框，并在界面说明原因 |
| **高级选项** | （可选）p0、坚定少数派、稳健性因素、其他提供方、备注 | —— |
| **核对** | 查看右侧的 Review & run 面板和提示词预览（本条件 / 另一奖励臂 / 有记忆示例） | 实时校验，错误显示在对应字段下方；估算调用次数、token 数和费用；显示模型相关警告 |
| **离线测试** | 点 "Test offline (mock)" | 用 mock 模型跑完整流程（最多 20 轮，不联网，不保存），报告泄漏检查结果 |
| **正式运行** | 付费运行需先勾选费用确认，再点 "Start run" | 未确认费用时拒绝运行；在后台运行；按轮写入数据 |
| **② Monitor** | 查看实时曲线；可以点 "Stop run" 停止 | 推送每轮的熵、众数份额、切换率、无效率 |
| **③ Results** | 打开某次运行；勾选多次运行做比较；下载数据；中断的运行可以点 "Resume" 续跑 | 计算运行级指标；逐轮配对视图；生成各种下载文件 |
| **API & Models** | 保存密钥；选择默认 Claude 模型；点 "Test" 测试某个模型 | 密钥只写入本机 `.env`；测试时只发送一次极小的请求 |
| **批量运行（命令行）** | `python -m naming_game.cli matrix spec.json` | 展开析因设计，估算总费用，询问确认，依次运行；中断后可以续跑 |

### 5.2 Setup 页的预设

| 分组 | 预设 | 对应的设计格 |
|---|---|---|
| 主实验 | Study B · key cell | 无奖励，有记忆（自己 + 伙伴），H = 5，随机配对 |
| | Study B · prior baseline | 无奖励，无记忆 |
| | Study A · rewarded | 有奖励，有记忆，H = 5，记忆中显示得分 |
| | Focal-point control | 有奖励，无记忆 |
| 对照与拓扑 | B+1 · own choices only | 无奖励，只显示自己的选择 |
| | B+2 · own choices + points | 有奖励，只显示自己的选择和得分 |
| | Study A · star | 有奖励，星形 |
| | Study A · communities | 有奖励，两个社区，p_within = 0.9 |
| 校准与零模型 | Study 0 · prior calibration | 20 个孤立智能体 × 20 轮 |
| | Null · majority_H / Null · voter(q) | 规则型，不调用模型 |
| 快速检查 | Smoke test (real API) | 12 人 × 3 轮，使用默认 Claude 模型，约 $0.01 |
| | Offline demo | mock 模型，模仿伙伴，免费 |

默认值：N = 24，300 轮（预实验值），种子 0，标签集 L1。选完预设后，按设计要求修改种子和标签集。

### 5.3 系统预设、不在界面上调整的参数

以下参数固定在代码或配置默认值里。改动它们等于改变实验方案，所以没有放在界面上：

| 参数 | 值 | 依据 |
|---|---|---|
| 提示词模板 | v1（第 4.4 节），带版本号和哈希 | SPEC §5.5 |
| 禁用词表 | 第 4.6 节 | SPEC §5.6 |
| 解析重试 | 1 次；API 失败最多重试 5 次，间隔从 2 秒起指数增长 | SPEC §5.2 |
| 无效率阈值 | 2 % 标记 / 5 % 排除 | D3 |
| 共识定义 | 众数份额 ≥ 0.9，连续 W = max(10, 5 % × 轮数) 轮 | D8 |
| 碎片化定义 | 最后 20 % 的轮次中，至少 2 个标签的平均份额 ≥ 0.3 | SPEC §7.2 |
| 情境编号 | 只有一个情境 `s0`（`n_stimuli = 1`） | 首批研究的范围 |
| 模型输出上限 | 16 tokens。推理无法关闭的模型为 2048 tokens，effort = low | 输出只是一个标签 |
| 智能体编号 | a00、a01… 在整个运行中保持不变 | D7（有稳健性开关） |
| 伙伴身份 | 从不显示，始终称为 "the other participant" | brief |

---

## 6. 参数参考

| 字段 | 含义 | 默认值 | 可选值 / 约束 | 界面位置 |
|---|---|---|---|---|
| `experiment_id` | 研究类别 | 自动推导 | 孤立 → prior_calibration；规则型 → null_model；有奖励 → rewarded_naming；其余 → no_reward_convergence | 右侧面板（只读） |
| `seed` | 随机种子 | 0 | ≥ 0 | 第 2 步 |
| `label_set_id` | 标签集 | L1 | L1 / L2 / L3 | 第 2 步 |
| `n_agents` | 人数 | 24 | 12 / 24 / 48；20 只用于校准；随机配对和社区拓扑要求偶数 | 第 2 步 |
| `n_rounds` | 轮数 | 300 | ≥ 1 | 第 2 步 |
| `pairing` | 配对方式 | random_dyad | random_dyad / community / star / isolated（isolated 只用于校准） | 第 2 步 |
| `n_blocks`、`p_within` | 社区数、社区内配对概率 | 2、0.9 | p_within ∈ (0, 1] | 第 2 步（社区） |
| `hub_id` | 中心节点 | a00 | 必须是有效的智能体编号 | 第 2 步（星形） |
| `memory_mode` | 记忆开关 | 开 | 关闭时 H 必须留空，反馈只能是 choices_only | 第 3 步 |
| `memory_content` | 记录内容 | own_and_partner | own_only 为对照 | 第 3 步 |
| `memory_horizon_H` | 记忆长度 | 5 | ≥ 1（H = 0 不合法，要关闭记忆请用开关） | 第 3 步 |
| `memory_order` | 记录顺序 | 最新在前 | 最旧在前为稳健性（D6） | 高级 |
| `reward_mode` | 奖励 | none | local_match | 第 4 步 |
| `payoff` | 相同 / 不同时的得分 | 100 / −50 | 只在有奖励时有效 | 第 4 步 |
| `feedback_mode` | 记忆记录中包含什么 | choices_only | numeric_score 只能在有奖励时用；match_indicator 需要勾选 robustness_cell，且不能与 own_only 同时使用 | 第 4 步 |
| `show_cumulative_points` | 是否显示累计得分 | 是 | 只能在 numeric_score 下使用 | 第 4 步 |
| `policy_default` | 选择者 | llm | llm / majority_H / voter / prior_sample | 第 5 步 |
| `q` | voter 复制概率 | 0.5 | [0, 1] | 第 5 步 |
| `model` | 提供方、模型、温度、输出上限 | Haiku 4.5，温度用提供方默认值，16 | 温度必须 > 0 | 第 5 步、高级 |
| `p0` | 标签先验 | 均匀 | 每个标签一个值，总和为 1 | 高级 |
| `committed_minority` | 坚定少数派 | 关闭 | frac ∈ (0, 0.5)，round(frac × N) ≥ 1 | 高级 |
| `show_own_agent_id` | 是否显示 "You are participant aXX" | 是 | 稳健性（D7） | 高级 |
| `max_concurrency` | 并发调用数 | 24 | ≥ 1 | 高级 |
| `notes` | 备注 | —— | 只存档，不进入提示词，也不参与 hash | 高级 |

---

## 7. 输出数据与指标

### 7.1 每次运行保存的文件

所有文件都在 `logs/experiments/{experiment_id}/{run_id}/` 下：

| 文件 | 内容 |
|---|---|
| `config.json` | 完整配置和 config_hash |
| `manifest.json` | 模板哈希、标签集哈希、git commit、软件包版本、模型版本、生效的采样参数、运行状态 |
| `calls.jsonl` | 每次模型调用一行：完整提示词、发送的消息、原始输出、解析结果、token 数、延迟、生效温度 |
| `interactions.csv` | 每个配对中每个参与者一行，字段见 SPEC §6 |
| `population.csv` | 每轮一行，分别计算"本轮选择""群体状态""排除少数派后的群体状态"三个版本 |
| `summary.json` | 运行级结果 |
| `leakage_report.json` | 泄漏检查结果（passed / hits） |
| `events.jsonl` | 坚定少数派加入等事件 |

**Results → Downloads** 提供：

- 可读的文本记录，每行形如 `a00 (Gibo) × a09 (Vapa) → different labels`，每轮末尾附群体状态；
- 带完整提示词的文本记录；
- 每对一行的 CSV；
- H3 用的 `choice-model.csv`；
- 全部原始文件的 zip。

示例见附录 B。

### 7.2 群体指标（每轮计算）

- **群体状态：** s_i(t) 是智能体 i 最近一次的有效选择，p_k(t) 是选择标签 k 的智能体比例。
- **熵：** H = −Σ p_k log₂ p_k；归一化熵 = H / log₂ K（K = 标签数）。
- **众数份额** = max_k p_k（平局时按字母顺序取第一个）；另外记录使用中的标签种数。
- **切换率：** 本轮有有效选择、且之前有过有效选择的智能体中，本轮选择与上次不同的比例。
- 另记本轮无效率和作废率。

### 7.3 运行级结果

- **共识：** 满足 §5.3 的定义即为达成。T_consensus 是第一个满足条件的窗口的起始轮，同时给出轮次和 t_pc 两种表示。
- **碎片化：** 见 §5.3。
- **最终获胜标签及其份额：** 最后 20 % 的轮次中平均份额最高的标签。
- **其他：** 最后 20 % 的轮次中使用过的标签种数、平均切换率、无效率、作废率、是否需要标记或排除。

### 7.4 H3 数据（choice-model.csv）

每行对应"一次选择 × 一个候选标签"，字段包括：

- `chosen`：是否选了该标签；
- `own_prev`：该标签是不是自己上一次的有效选择；
- `own_count_H`：本条提示词显示的记录中，自己选该标签的次数；
- `partner_count_H`：本条提示词显示的记录中，伙伴选该标签的次数；
- `log_p0`：该标签的先验对数概率；
- `position`：该标签在本条提示词中的显示位置。

暴露变量**只统计本条提示词中实际显示的记录**。own_only 条件下 partner_count_H 恒为 0。

**【待确认 3】** `own_prev` 目前按智能体的**全部**历史计算。在无记忆条件下，智能体其实看不到自己的上一次选择。它应该在无记忆条件下设为 0 或缺失，还是保留原样作为"惯性"的度量？

### 7.5 判断涌现的清单（由研究者判断，每个研究一次）

1. 相对无记忆基线，熵有下降，且下降幅度超出 `prior_sample` 零模型。
2. 获胜标签的分布比"由先验预测的零模型"更分散。
3. 控制 β1、β2、β4、β5 之后，β3 > 0。
4. Study A：报告稳定的多惯例并存比例。局部成功不等于全局共识。
5. own_only 对照没有重现群体收敛。
6. 纳入分析的运行 100 % 通过泄漏检查，且无效率低于阈值。

---

## 8. 模型选择与成本

| 模型 | 输入 / 输出（每百万 token） | 温度 | 隐藏推理 | 适合做什么 |
|---|---|---|---|---|
| Claude Haiku 4.5 | $1 / $5 | 可设置 | 无 | 预实验。目前的默认模型 |
| Claude Sonnet 4.6 | $3 / $15 | 可设置 | 无 | 中型模型，可设温度 |
| Claude Sonnet 5 | $2 / $10 | 固定为默认值 | 引擎会关闭推理 | 中型模型，但温度不可控 |
| Claude Opus 4.6 / 4.7 / 4.8 / 5 | $5 / $25 | 4.6 可设，其余固定 | 无，或由引擎关闭 | 大型模型 |
| Claude Opus 5.5 / Fable 5.1 | $4 / $20、$10 / $50 | 固定 | **无法关闭**（会被标记） | 不建议用于正式格 |

- **实测：** Haiku 4.5 每次调用平均约 155 个输入 token，延迟约 0.7 秒。
- **单次运行估算：** 24 人 × 300 轮 = 7,200 次调用。用 Haiku，无奖励格约 $1.4，有奖励格约 $2.1（提示词更长）。
- **SPEC 完整矩阵估算：** 200 次运行，约 124 万次调用。

| 模型 | 估算总费用 |
|---|---|
| Haiku 4.5 | ≈ $300 |
| Sonnet 5 | ≈ $600 |
| Sonnet 4.6 | ≈ $900 |

- 预实验很可能会大幅减少 `n_rounds`，费用也会相应下降。
- **运行时长：** 轮与轮之间是顺序执行的。300 轮随机配对约需 5–8 分钟。
- **【待确认 4（D9）】** 正式格使用哪个模型，以及用哪个第二模型家族做重复验证？选择会影响温度是否可控。按照 D4，温度应当大于 0，并且作为稳健性因素。

---

## 9. 效度威胁与已知局限

- **单一模型种群：** 所有智能体共享同一个先验，协调会因此更容易。需要至少两个模型家族来推广结论。
- **"听从指令"作为隐性目标：** 即使没有奖励，"选一个标签"加上"能看到伙伴的历史"本身就是一种需求线索。它的影响由 own_only 对照和零模型来界定。
- **提供方的非确定性与静默更新：** 每次调用都记录模型版本；建议交错运行各格，不要按格依次运行。
- **无意义标签仍有语音偏好：** 用先验校准和 log p0 协变量处理。
- **构念范围：** 无意义标签上的惯例只是最小形式的制度（Lewis convention）。要推广到更丰富的制度，需要后续的自然语言研究，例如 Ashford Valley。
- **mock 模型只用于测试：** 它的输出不能作为数据。

---

## 10. 需要你审阅或决定的事项

| # | 事项 | 我的建议 |
|---|---|---|
| 1 | own_only 条件下，交互段落里 "each of you is shown the other's choice" 的承诺没有兑现（§4.4） | 改为方案 (b)，给 own_only 单独写交互段落，并在方法部分说明 |
| 2 | 标签只按英文词表过滤过（§4.5） | 人工检查一遍，必要时换掉个别标签（例如 Soru） |
| 3 | `own_prev` 在无记忆条件下的定义（§7.4） | 分成两个变量导出：`own_prev_visible` 和 `own_prev_history` |
| 4 | 正式格的模型（D9）（§8） | 在预实验前决定；Haiku 4.5 或 Sonnet 4.6 可以控制温度 |
| 5 | 正式运行的 `n_rounds` | 按 §3.6 由预实验决定 |
| 6 | 实现中的取舍（`IMPLEMENTATION_NOTES.md`）：校准允许 N = 20；无效率按重试后计算；majority_H 平局规则；少数派加入时机；众数平局取字母序 | 请确认，或者指出需要改的地方 |
| 7 | 尚未实现：10,000 种子的向量化零模型（H4 零分布）、条件 logit 与混合模型拟合、B+3 yoked 对照、多情境、混合模型种群、Anthropic Batch API（便宜 50 %） | 在预注册前补上 H4 零模型；统计拟合可以在 R 里做 |

---

## 附录 A：各条件实际生成的提示词（软件原样输出，记忆内容为示例）

**Study B 关键格**（无奖励，自己 + 伙伴，H = 5）：

```
You are participant a00.
A situation is labeled s0.
You are paired with another participant, who chooses from the same list at the same time.
After both choices are submitted, each of you is shown the other's choice.

Choose exactly one label from this list:
- Gibo
- Pubi
- Soru
- Laba
- Zago
- Mune
- Neba
- Vapa
- Kepe
- Niru

Reply with only the label.

Your own recent interactions, if any:
- Latest interaction: you chose Niru; the other participant chose Kepe.
- 2 interactions ago: you chose Kepe; the other participant chose Kepe.
- 3 interactions ago: you chose Gibo; the other participant chose Vapa.
- 4 interactions ago: you chose Zago; the other participant chose Zago.
- 5 interactions ago: you chose Laba; the other participant chose Zago.
```

**Study A**（有奖励，显示得分）。和上面相比只多了奖励段落和记忆行末尾的得分：

```
You are participant a00.
A situation is labeled s0.
You are paired with another participant, who chooses from the same list at the same time.
After both choices are submitted, each of you is shown the other's choice.

Scoring rule for this pairing only:
If you and the other participant choose the same label, you receive 100 points.
If you choose different labels, you receive -50 points.
Your objective is to maximize your own points across pairings.
Your cumulative points so far: 50

Choose exactly one label from this list:
- Gibo
- (… same list, shuffled independently …)

Reply with only the label.

Your own recent interactions, if any:
- Latest interaction: you chose Niru; the other participant chose Kepe; you received -50 points.
- 2 interactions ago: you chose Kepe; the other participant chose Kepe; you received 100 points.
- (…)
```

**B+1**（只显示自己）。注意交互段落与记忆内容之间的矛盾，见待确认 1：

```
(… same header and interaction block …)

Your own recent interactions, if any:
- Latest interaction: you chose Niru.
- 2 interactions ago: you chose Kepe.
- (…)
```

**Study 0**（孤立，没有交互段落）：

```
You are participant a00.
A situation is labeled s0.
Choose exactly one label from this list:
- Gibo
- (…)

Reply with only the label.

Your own recent interactions, if any:
None.
```

## 附录 B：交互记录示例（Haiku 冒烟测试，12 人 × 3 轮）

这不是研究数据，只用于展示格式：

```
── Round 0 ────────────────────────────────────────
  a00 (Gibo) × a09 (Vapa) → different labels
  a10 (Gibo) × a11 (Niru) → different labels
  a05 (Kepe) × a07 (Gibo) → different labels
  a01 (Soru) × a06 (Niru) → different labels
  a02 (Gibo) × a03 (Gibo) → same label
  a04 (Vapa) × a08 (Zago) → different labels
  population state after this round: most common label Gibo (0.42 of agents)
```

## 附录 C：常用命令

```
./start.sh                                               # 等同于双击 一键启动.command
venv/bin/python -m pytest tests -q                       # 55 项测试，付费运行前必须通过
venv/bin/python -m naming_game.cli validate config.json  # 校验 + 费用估算 + 提示词
venv/bin/python -m naming_game.cli dry-run config.json   # 离线完整流程
venv/bin/python -m naming_game.cli run config.json       # 单次运行（付费前询问）
venv/bin/python -m naming_game.cli matrix spec.json      # 析因矩阵（估算后确认）
venv/bin/python -m naming_game.cli resume RUN_ID         # 续跑
```

## 参考文献

- Ashery, A. F., Aiello, L. M., & Baronchelli, A. (2025). Emergent social conventions and collective bias in LLM populations. *Science Advances*.
- Lewis, D. (1969). *Convention: A Philosophical Study*. Harvard University Press.
- Baronchelli, A. et al. (2006). Sharp transition towards shared vocabularies in multi-agent systems. *Journal of Statistical Mechanics*.
- Centola, D. et al. (2018). Experimental evidence for tipping points in social convention. *Science*.
- Piatti, G. et al. (2024). Cooperate or Collapse: Emergence of sustainable cooperation in a society of LLM agents. *NeurIPS*.
