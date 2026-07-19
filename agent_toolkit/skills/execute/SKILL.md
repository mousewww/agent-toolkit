# Skill: Execute

## 用途
按 `dispatch` 拆解出的任务列表，逐个调用弱模型执行任务，并**让模型自己按验收标准自检**。最终返回每个任务的执行结果和自检报告，供 `accept` 阶段复核。

## 输入

`dispatch` 的输出：

```json
{
  "tasks": [
    {
      "id": "task_1",
      "description": "...",
      "file": "...",
      "model": "local-7b-coder",
      "depends_on": [],
      "prompt": "给执行代理的精简提示词",
      "expected_output": "期望产出",
      "self_check": ["自检项1", "自检项2"]
    }
  ]
}
```

## 输出

```json
{
  "results": [
    {
      "task_id": "task_1",
      "status": "success | failed | skipped",
      "output": "模型生成的执行结果/代码/分析",
      "self_check_report": "自检说明",
      "passed": true,
      "issues": []
    }
  ]
}
```

## 执行规则

1. **按依赖顺序执行**：根据 `depends_on` 拓扑排序，前置任务结果会注入到后续任务的上下文中。
2. **一次调用完成执行 + 自检**：模型先执行任务，再按 `self_check` 清单检查自己，输出统一 JSON。
3. **任务隔离**：每个任务只操作自己的 `file`。写文件前自动备份到 `<file>.execute.bak`，失败时自动恢复。
4. **默认不实际写文件**：不加 `--apply` 时只生成结果；加 `--apply` 时才真正修改文件。
5. **返工机制**：自检不通过自动返工，最多 `max-retries` 次（默认 2 次）。仍失败则抛出异常，由上层强模型诊断。
6. **弱模型即可**：任务 prompt 已经被 `prompt_optimizer` 和 `dispatch` 写得很清楚，用 `deepseek-v4-flash` 甚至本地 7B/14B coder 都够用。

## 模型选择

| 场景 | 推荐模型 | 原因 |
|------|----------|------|
| 默认 | **deepseek-v4-flash** | 国内快、便宜、代码任务够用 |
| 简单代码修改 | 本地 7B/14B coder | 省钱、保护隐私 |
| 调试 / 复杂逻辑 | deepseek-v4-flash / gpt-4o-mini | 需要一点推理能力 |

可以通过 `EXECUTE_MODEL` 环境变量覆盖所有任务的模型（调试用）。

## 环境变量

```bash
EXECUTE_API_KEY=sk-xxx            # 默认读取 OPENAI_API_KEY
EXECUTE_MODEL=deepseek-v4-flash   # 可覆盖任务中的 model
HEADROOM_PROXY_URL=http://localhost:8787/v1  # 可选，走 Headroom 压缩
```

## 用法

```bash
# 只生成结果，不写文件
python agent-toolkit/pipeline/dispatch.py --file prompt_output.json | \
  python agent-toolkit/pipeline/execute.py

# 实际写文件（会自动备份）
python agent-toolkit/pipeline/dispatch.py --file prompt_output.json | \
  python agent-toolkit/pipeline/execute.py --apply

# 自定义返工次数
python agent-toolkit/pipeline/execute.py --file dispatch_output.json --apply --max-retries 2

# 同层级任务并行（默认串行）
python agent-toolkit/pipeline/execute.py --file dispatch_output.json --parallel
```

## 拓扑排序与并行

`execute.py` 会先按 `depends_on` 把任务分层：

```text
Level 0: task_1, task_2   ← 无依赖，可并行
Level 1: task_3           ← 依赖 task_1，必须等 Level 0 完成
Level 2: task_4, task_5   ← 依赖 task_3，可并行
```

- 默认**串行**：最安全，避免文件竞争和调试混乱。
- 加 `--parallel`：同层级任务并发执行，适合大量独立任务时省时间。

## 为什么自检还不够

模型自检会有盲区（比如没意识到自己的代码有边界情况、测试用例覆盖不全）。所以 `execute.py` 的自检只是第一道关卡，最终还需要 `accept.py` 用强模型对照原始需求再验收一遍。

```text
execute 自检  →  accept 强模型复核  →  人工确认（可选）
```