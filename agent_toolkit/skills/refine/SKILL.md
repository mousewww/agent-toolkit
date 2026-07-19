---
name: refine
description: >
  接收 intake 清洗后的文本，调用轻量模型提取结构化需求：
  目标、输入、输出、约束、验收标准、上下文。
trigger: intake 节点完成后，运行此 skill 把原话转成可执行的结构化需求。
agent_created: true
---

# Refine — 结构化需求

## 作用

把一句/一段干净的意图描述，拆成程序员能看懂的六要素：

- **goal**：核心目标，一句话。
- **inputs**：已有输入、附件、路径。
- **outputs**：期望产出。
- **constraints**：限制条件（不能做什么、必须用什么）。
- **acceptance**：验收标准（怎么算完成）。
- **context**：背景/上下文。

## 输入

intake 的输出 JSON：

```json
{
  "cleaned": "整理后的需求文本",
  "attachments": [...],
  "intent_hint": "implement | fix | explain | review | ask",
  "context": "可选上下文"
}
```

## 输出

```json
{
  "goal": "...",
  "inputs": ["..."],
  "outputs": ["..."],
  "constraints": ["..."],
  "acceptance": ["..."],
  "context": "..."
}
```

## 执行方式

```bash
python agent-toolkit/pipeline/refine.py --file intake_output.json
# 或
python agent-toolkit/pipeline/refine.py < intake_output.json
```

## 模型选择

- **默认**：`deepseek-v4-flash`（国内、快、便宜、够用）。
- **复杂需求 fallback**：`gpt-5.6-luna`（能力强，但 packyapi 延迟高）。
- 通过环境变量覆盖：
  - `REFINE_MODEL`
  - `REFINE_API_KEY` / `OPENAI_API_KEY`
  - `REFINE_BASE_URL`

## 规则

- 不补充原文没有的信息。
- 不脑补技术方案。
- 某项确实没有时，用空字符串或空数组。
- 只输出 JSON，不解释。
