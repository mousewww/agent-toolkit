# clarify — 需求澄清节点

## 职责

在 `refine` 之后、`prompt_optimize` 之前插入，由模型扮演 PM 角色，主动发现需求中的：

- 模糊目标与范围蔓延
- 缺失的关键输入/约束
- 隐式假设及其风险
- 验收标准是否可量化

目标：一次性把需求约束清楚，减少下游 Agent 返工和 token 浪费。

## 使用方式

### 1. 命令行

```bash
# 检查清单模式（默认输出 JSON）
python agent-toolkit/pipeline/clarify.py --file refine_output.json

# 输出 Markdown 清单（方便复制到文档/备忘录）
python agent-toolkit/pipeline/clarify.py --file refine_output.json --markdown

# 交互模式：命令行逐条提问并收集答案
python agent-toolkit/pipeline/clarify.py --file refine_output.json --interactive

# 使用 agent-toolkit 内置领域模板（如果存在）
python agent-toolkit/pipeline/clarify.py --file refine_output.json --domain aliexpress

# 使用项目独立目录里的领域模板（推荐，项目隔离）
python agent-toolkit/pipeline/clarify.py \
  --file refine_output.json \
  --domain-file agent-workspace/project/aliexpress/clarify-prompt.md
```

### 2. 管线串联

```bash
python agent-toolkit/pipeline/intake.py --file input.txt | \
  python agent-toolkit/pipeline/refine.py | \
  python agent-toolkit/pipeline/clarify.py \
    --domain-file agent-workspace/project/aliexpress/clarify-prompt.md \
    --markdown
```

### 3. runner 集成

```bash
# 默认通用澄清
python agent-toolkit/pipeline/runner.py --file input.txt --clarify

# 使用项目独立的领域 prompt
python agent-toolkit/pipeline/runner.py \
  --file input.txt \
  --clarify \
  --domain-file agent-workspace/project/aliexpress/clarify-prompt.md
```

`--clarify` 默认输出 Markdown 清单到 stdout，不会阻塞等待用户输入。
如需交互式问答，单独调用 `clarify.py --interactive` 或 `runner.py --clarify --interactive`。

> **项目隔离建议**：不要把项目特定的领域 prompt 放进 `agent-toolkit/skills/clarify/`。
> 通用 skill 只放公共模板；每个真实项目的 prompt 放在 `agent-workspace/project/<项目>/` 下，
> 通过 `--domain-file` 引用。

## 输入

支持两种输入：

1. `refine.py` 的输出（推荐）：包含 `goal/inputs/outputs/constraints/acceptance/context`
2. `intake.py` 的输出：包含 `cleaned/context/attachments`

## 输出 JSON 结构

```json
{
  "status": "needs_clarification" | "complete",
  "questions": [
    {
      "id": "q1",
      "question": "具体问题，用户能直接回答",
      "why": "为什么这个问题会影响实现",
      "category": "目标/输入/输出/环境/流程/异常/验收/安全",
      "priority": "must | should | nice"
    }
  ],
  "assumptions": [
    {
      "id": "a1",
      "assumption": "当前假设",
      "risk": "假设错误的风险",
      "verify": "如何验证"
    }
  ],
  "missing": ["缺失的关键信息"],
  "summary": "总体判断",
  "domain": "aliexpress",
  "answers": {}   // 交互模式下填充
}
```

## 环境变量

```bash
export CLARIFY_API_KEY="sk-xxx"   # 未设置时 fallback 到 OPENAI_API_KEY
export CLARIFY_MODEL="deepseek-v4-flash"
```

## 设计原则

- **宁可多问，不要盲做**：status 为 `needs_clarification` 时，必须先把问题回答完再进入下游。
- **领域模板可扩展**：在 `skills/clarify/<domain>-prompt.md` 添加新领域审查要点，命令行用 `--domain <domain>` 调用。
- **默认不阻塞**：`runner.py` 中 `--clarify` 输出清单供人工查看；交互模式需显式 `--interactive`。
