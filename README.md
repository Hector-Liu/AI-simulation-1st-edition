# Naming Game Simulator（AI simulation 2nd）

这是一个研究用的 LLM 多智能体**命名博弈（naming game）**模拟器，用来检验：只靠局部、私有、两两之间的互动，一群 LLM 智能体能否形成群体层面的惯例（Lewis convention）；有奖励和没有奖励两种条件下，结果是否不同。

它脱胎于旧项目 `concordia-sim-builder`（Google DeepMind Concordia 的网页封装），但**完全不依赖 Concordia**。Concordia 的 Game Master 会用 LLM 改写观察内容，会给智能体加上固定的角色扮演指令，也无法精确控制提示词或设定随机种子。这些都会破坏实验不变量（见 `docs/SPEC-naming-game-v1.0.md` §4.1）。本程序是一个独立的协议引擎：每次模型调用只发一条 user 消息，发送的文本被逐字记录。

## 一键启动

1. 在访达里双击 **`一键启动.command`**。第一次运行会自动安装 Python 环境，大约 1–2 分钟。
2. 浏览器会自动打开 `http://127.0.0.1:8765`。
3. 用完关掉终端窗口即可停止。

API 密钥：启动脚本会自动从旧项目 `../concordia-sim-builder/.env` 复制 `ANTHROPIC_API_KEY` 到本项目的 `.env`。`.env` 只保存在本机，已写入 `.gitignore`，不会上传。也可以在网页的「API 密钥」页填写。

在终端里启动：`./start.sh`（macOS/Linux）。

## 网页里能做什么（界面为英文）

| 页面 | 功能 |
|---|---|
| **1 · Setup** | 分 5 步设置：① 选一个实验条件预设（Study A/B 各格、对照组、Study 0 校准、null 模型、冒烟测试）；② 人数、轮数、种子、标签集、配对方式；③ 记忆；④ 奖励；⑤ 由谁做选择（Claude 模型 / 离线 mock / 规则型 null 模型）。不可能的组合会被直接禁用，出错时错误显示在对应字段下方。右侧 **Review & run** 面板显示一句话的设计摘要、校验结果、费用估算、两条奖励臂的提示词预览；付费运行必须先勾选费用确认 |
| **2 · Monitor** | 实时显示熵、众数份额、切换率、无效率；可随时停止 |
| **3 · Results** | 运行列表；多选后叠加曲线，并按种子汇总获胜标签（H4）。运行详情分四个标签页：Overview、**Interactions by round**（逐轮查看谁和谁配对、各自选了什么）、Model calls（完整提示词和原始输出）、**Downloads** |
| **API & Models** | API 密钥；**切换默认 Claude 模型**（列出价格、能否设温度、是否有隐藏推理），每个模型都有 Test 按钮（一次极小的真实调用） |

### 下载内容（Results → Downloads）

| 文件 | 内容 |
|---|---|
| Readable transcript (.txt) | 逐轮记录：`a03 (Laba) × a17 (Zago) → different labels`，每轮末尾附群体状态 |
| Transcript with full prompts (.txt) | 在上面的基础上加入每个智能体收到的完整提示词和原始回答 |
| Interaction table (.csv) | 每个配对每轮一行：轮次、双方、各自选择、是否相同、得分、原始输出 |
| Choice-model data (.csv) | H3 条件 logit 用的长格式数据 |
| All raw data (.zip) | 这次运行的全部原始文件 |

### 为什么每条提示词都要做禁用词检查

研究要回答的是：惯例能否**仅凭两两互动**产生。如果提示词里出现 *agree / coordinate / consensus / majority / most / the group* 这类词，模型等于被告知"要趋同"，或者拿到了群体层面的信息；无奖励臂里如果出现 *points / score / win*，等于偷偷加入了激励。无论哪种，结果都只能说明模型在服从指令，而不是出现了涌现。模板本身已经避开了这些词；自动检查是一道保险，防的是日后改模板、新增配置组合或渲染数据时意外混入这些词。一旦命中就停止运行，检查结果写进 `leakage_report.json`，作为 SPEC §7.6 第 6 条"泄漏审计通过"的证据。

## 实验不变量（代码层面保证，测试层面验证）

- 智能体只有**私有**的环形缓冲区，只记录自己参与过的互动。唯一的记忆写入函数是 `commit_dyad()`。
- 提示词里**绝不出现**群体统计或其他配对的信息。唯一的提示词构造函数是 `build_agent_prompt()`，发送前每条提示词都要过 denylist 和正则检查，一旦命中就中止运行（fail-closed）。
- 一轮之内的所有提示词都在任何选择产生**之前**构造完（保证同时性）。标签顺序每条提示词独立打乱。
- 有奖励和无奖励两条臂的提示词**只**相差 payoff 段和记录后缀。
- 解析器严格，不做模糊匹配。无效输出会用同一提示词重试一次；仍无效则该配对作废（void），不写入记忆，原始文本照样保存。
- 由 LLM 判断"是否涌现"是不允许的，所有指标都由程序计算。

## 数据输出

每次运行的数据在 `logs/experiments/{experiment_id}/{run_id}/`：

| 文件 | 内容 |
|---|---|
| `config.json`, `manifest.json` | 配置、config_hash、模板和标签集哈希、git commit、包版本、模型版本、实际生效的采样参数 |
| `calls.jsonl` | 每次模型调用一行：完整提示词、provider messages、原始输出、解析结果、tokens、延迟 |
| `interactions.csv` | 每个参与者每个配对一行（SPEC §6 的全部字段） |
| `population.csv` | 每轮一行：本轮选择 / 群体状态 / 去掉少数派后的状态，各自的熵、众数、份额 |
| `summary.json`, `leakage_report.json` | 运行级结果（§7.2），泄漏检查结果 |

## 测试

```bash
venv/bin/python -m pytest tests -q
```

共 55 项测试，覆盖 SPEC §8 的验收测试 1–15 和 Web API，全部离线运行（mock 模型）。按 SPEC 的规定，任何付费运行之前这些测试都必须通过。

## 命令行（批量实验用）

```bash
venv/bin/python -m naming_game.cli validate config.json      # 校验 + 费用估算 + 提示词
venv/bin/python -m naming_game.cli dry-run config.json       # mock 全流程
venv/bin/python -m naming_game.cli run config.json           # 单次运行（付费前会询问）
venv/bin/python -m naming_game.cli matrix spec.json          # 析因矩阵，估算费用后运行
venv/bin/python -m naming_game.cli resume RUN_ID
```

示例配置在 `examples/`。

## 文档

- `docs/SPEC-naming-game-v1.0.md`：已批准的实验设计规格
- `docs/brief-original.md`：最初的实现 brief
- `docs/IMPLEMENTATION_NOTES.md`：实现时做的选择、已验证的内容、尚未实现的部分（**预注册前请务必阅读**）

## 来源说明

提供方层和日志约定参考了 [concordia-sim-builder](https://github.com/ngstcf/concordia-sim-builder)（Apache-2.0），代码为重新编写。实验设计来自 Ashery, Aiello & Baronchelli (2025) 的命名博弈范式，以及本项目的 SPEC。
