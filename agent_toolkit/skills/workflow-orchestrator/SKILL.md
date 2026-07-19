# Skill: Workflow Orchestrator

## 用途
任何用户请求进入本工具箱时的统一入口。先由最外层 `router` 判断请求类型，再决定进入哪条处理路径。

## 管线

### 顶层分流

```text
[raw_input] → router ──→ search  → 联网搜索 + 直接回答
            ├─→ chat   → 轻量模型直接回答
            ├─→ tool   → 调用对应工具
            └─→ programming → 进入编程代理七阶段管线
```

### 编程代理七阶段

```text
intake → refine → prompt_optimize → dispatch → execute → prune-check → accept → output
```

| 阶段 | 职责 | 能力要求 | 当前默认模型 | 原因 |
|------|------|----------|--------------|------|
| **router** | 最外层分流：判断请求是编程/搜索/聊天/工具 | 中：意图理解 + 分类 | **deepseek-v4-flash** | 只需一次调用，避免非编程任务进入完整管线 |
| **intake** | 接收原话，做基础清洗（去口语词、补全上下文、识别附件/路径） | 低：模式匹配 + 轻量理解 | **Python 规则** | 速度最快、零成本、稳定性高 |
| **refine** | 把原话转成结构化需求（目标、输入、输出、约束、验收标准） | 中：理解意图 + 结构化输出 | **deepseek-v4-flash** | 国内快、便宜、对结构化输出够用 |
| **prompt_optimize** | 把结构化需求转成给编程代理的精确提示词 | 中高：提示工程 + 领域知识 | **deepseek-v4-flash** | 速度优先，复杂 case 可换强模型 |
| **dispatch** | 判断任务复杂度并拆解成可执行子任务 | 中-高：理解 + 规划 | **deepseek-v4-flash / gpt-5.6-terra**；简单任务走规则路由 | 规划错误会导致整段失败；但简单任务不必每次都调强模型 |
| **execute** | 按规划执行任务，模型自己按验收标准自检 | 中：执行 + 自我纠错 | **deepseek-v4-flash / 本地 7B-14B coder** | 有明确 spec 后，弱模型足够；本地跑保护隐私和省钱 |
| **prune-check** | 验收前检查项目冗余，提出精简建议，但不改功能 | 中：项目理解 + 极简判断 | **deepseek-v4-flash / 规则扫描 + Agent 审查** | 防止过度工程，保持极简 |
| **accept** | 对照原始需求验收，判断结果是否合格 | **高**：判断质量、发现遗漏 | **deepseek-v4-pro / claude-3.5-sonnet / gpt-4o** | 最终闸门，必须可靠 |

## 模型选择原则

1. **规划与验收尽量用强模型，但 dispatch 有路由**：复杂/多文件任务才调强模型规划；简单单文件任务直接走规则路由，节省延迟和费用。
2. **验收必须强模型**：最终闸门决定方向和质量，不能降级。
3. **refine / prompt_optimize 用 v4-flash**：速度优先，够用即可；packyapi 的 5.6 系列虽然便宜但延迟太高，不用于速度敏感节点。
4. **dispatch 简单任务走规则路由**：单文件、无复杂关键词时直接生成单任务，不调用强模型。
5. **执行可降级**：只要 prompt 足够精确，7B 级别 coder 模型足够处理 80% 的局部修改。
6. **execute 执行 + 自检一体**：每个任务一次调用产出结果和自检报告，但最终仍需要 accept 强模型复核。
7. **intake 尽量不用 LLM**：先用规则/正则/脚本处理，搞不定再调用轻量模型。
8. **本地模型优先用于**：代码生成、敏感数据处理、高频小任务。
6. **联网/多模态只在需要时启用**：dispatch 阶段判断是否需要联网搜索或多模态理解，不要默认开启。
7. **prune-check 先规则扫描，再模型/人工审查**：脚本只输出候选，是否精简由 Agent/人判断，确保功能不变。

## 输出格式

每个阶段输出一个结构化文件到 `agent-toolkit/pipeline/runs/<run_id>/`：

```text
00_router.json       # { "route", "confidence", "reason", "response", "next", "parameters" }
01_intake.json       # { "raw": "...", "cleaned": "...", "attachments": [] }
02_refine.json       # { "goal", "inputs", "outputs", "constraints", "acceptance" }
03_prompt.json       # 优化后的编程代理提示词 + model_hint/files/tools
04_dispatch.json     # { "tasks": [{"id", "file", "model", "depends_on"}] }
05_execute.json      # { "results": [{"task_id", "status", "output", "self_check"}] }
06_prune_report.json # { "path": "...", "candidates": [...] }
07_accept.json       # { "passed": bool, "issues": [], "final_output": "" }
```

## 执行规则

- 一次只推进一个阶段，不要跳步。
- 每个阶段完成后用一句话汇报：阶段名 + 关键结论 + 下一步。
- 阶段内失败最多重试 1 次；阶段间失败则停止并等待人工审批。
- 执行阶段优先调用 `agent-toolkit/pipeline/` 里的脚本，不要直接改 skill。
