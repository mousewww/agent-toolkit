# Skill: Dispatch

## 用途
把 `prompt-optimizer` 生成的编程代理提示词，拆分成一组可独立执行、低耦合、带依赖顺序的子任务。

这是工作流中**强模型规划分工**的关键节点：规划错了，后面执行和验收都会跑偏，因此必须用推理能力足够的模型。

## 输入

`prompt-optimizer` 的输出：

```json
{
  "prompt": "给编程代理的完整提示词（Markdown）",
  "model_hint": "执行建议模型",
  "files_to_touch": ["可能涉及的文件路径"],
  "tools_hint": ["可能需要的工具、库或命令"]
}
```

## 输出

```json
{
  "tasks": [
    {
      "id": "task_1",
      "description": "一句话任务描述",
      "file": "主要操作的文件路径",
      "model": "建议执行模型",
      "depends_on": [],
      "prompt": "给执行代理的精简提示词",
      "expected_output": "该任务完成后应产出的结果",
      "self_check": ["自检项1", "自检项2"]
    }
  ]
}
```

## 规划原则

1. **一个任务一个文件或一个明确操作**：保持低耦合，不要把多个无关文件塞进同一个任务。
2. **依赖必须标明**：任务 B 需要任务 A 的结果，就用 `depends_on: ["task_A"]`。
3. **不要过度拆分**：如果提示词本身只改一个文件，直接输出一个任务即可。
4. **执行模型要降级**：规划用强模型，执行尽量用本地小模型或便宜模型。

## 模型选择

| 场景 | 推荐模型 | 原因 |
|------|----------|------|
| 默认规划 | **deepseek-v4-flash** | 国内快、便宜，对大多数规划任务够用 |
| 复杂跨文件架构 | gpt-5.6-terra / sol 或 claude-3.5-sonnet / gpt-4o | 长上下文和代码理解更强 |
| 测试阶段省钱 | deepseek-v4-flash | 已经是默认，不必降级 |
| 简单任务 | 规则路由，不调用 LLM | 毫秒级，零成本 |

## 环境变量

```bash
DISPATCH_API_KEY=sk-xxx            # 默认读取 OPENAI_API_KEY
DISPATCH_BASE_URL=https://api.deepseek.com/v1
DISPATCH_MODEL=deepseek-v4-flash   # 可覆盖为 gpt-5.6-terra 等
DISPATCH_FORCE_PLAN=1              # 强制所有任务都走模型规划（调试用）
```

## 用法

```bash
python agent-toolkit/pipeline/dispatch.py --file 03_prompt.json

# 或用 runner.py 直接跑完整管线
python agent-toolkit/pipeline/runner.py --file input.txt
```
