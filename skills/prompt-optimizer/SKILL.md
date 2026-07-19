---
name: prompt-optimizer
description: >
  接收 refine 输出的结构化需求，生成一份给编程代理的精确、可直接执行的提示词。
trigger: refine 节点完成后，运行此 skill 生成下游 execute 节点的输入提示词。
agent_created: true
---

# Prompt Optimizer — 提示词优化

## 作用

把结构化需求转成编程代理能直接执行的提示词。核心目标：**消除歧义、明确边界、给出验收标准**。

## 输入

refine 的输出 JSON：

```json
{
  "goal": "...",
  "inputs": [...],
  "outputs": [...],
  "constraints": [...],
  "acceptance": [...],
  "context": "..."
}
```

## 输出

```json
{
  "prompt": "给编程代理的完整 Markdown 提示词",
  "model_hint": "执行建议模型",
  "files_to_touch": ["可能涉及的文件路径"],
  "tools_hint": ["可能需要的工具/库/命令"]
}
```

## 执行方式

```bash
python agent-toolkit/pipeline/refine.py --file refine_output.json | \
  python agent-toolkit/pipeline/prompt_optimizer.py
```

## 模型选择

- **默认**：`deepseek-v4-flash`（速度优先，够用）。
- **复杂需求 fallback**：`gpt-5.6-terra` 或 `gpt-5.6-sol`（能力强但慢）。
- 环境变量：`PROMPT_MODEL`、`PROMPT_API_KEY`、`PROMPT_BASE_URL`。

## 规则

- 提示词里必须包含 goal、inputs、outputs、constraints、acceptance。
- 涉及修改代码时，必须要求编程代理先读文件再改。
- 不要输出解释，只输出 JSON。
