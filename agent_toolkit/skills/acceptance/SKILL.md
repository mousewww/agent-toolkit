# Skill: Acceptance（最终验收）

## 一句话定位

`acceptance.py` 是编程代理七阶段管线的**最后一道闸门**。它用强模型把 `execute` 产出的结果拉回用户原始需求面前，逐条核对，最终给出 **通过 / 不通过** 的判决。

```text
intake → refine → prompt_optimize → dispatch → execute → prune-check → accept → output
                                                          ↑
                                                    你刚刚补齐的节点
```

---

## 为什么需要 acceptance

`execute.py` 已经让模型自己做过一遍自检，但模型自检有盲区：

- 它可能觉得自己“按提示词实现了”，但漏掉了用户没写在任务 prompt 里、却写在原始需求里的约束。
- 它可能通过了自己的 `self_check`，但那些检查项本身不够完整。
- 多任务串联时，B 任务看到 A 任务的输出以为 OK，但 A 的输出其实偏离了原始目标。

所以七阶段设计把 **accept** 独立出来：

> execute 自检是第一道关 → accept 用强模型 + 原始需求做最终复核 → 必要时人工确认。

---

## 验收逻辑拆解

`acceptance.py` 内部只做三件事：

### 1. 收集证据

它把上游所有阶段的输出打包成一份“案卷”：

| 证据来源 | 作用 |
|---------|------|
| `refine` | 原始需求、验收标准、约束条件。这是判案的法条。 |
| `prompt` | 优化后的编程代理提示词，看任务目标有没有被转述偏。 |
| `dispatch` | 任务拆分、依赖关系、每个任务的 `expected_output` 和 `self_check`。 |
| `execute` | 每个任务的执行结果、自检报告、是否 `passed`。 |
| `prune_report`（可选） | 冗余检查报告，只作参考，不影响功能验收。 |
| 实际文件内容 | `dispatch.tasks` 里 `file` 字段指向的文件，如果存在就读取。这是落地的实物证据。 |

代码里对应 `_read_modified_files()` 和 `_build_user_prompt()`。

### 2. 交给强模型评审

把案卷发给强模型，附上一段严格的 system prompt：

- 逐条检查 `refine.acceptance` 和 `refine.constraints`。
- 检查 `execute.results` 中每个任务是否 `passed == true`。
- 检查任务输出是否满足对应任务的 `expected_output`。
- 检查实际文件内容是否符合原始需求。
- 有明显问题就判不通过，不要和稀泥。
- 只输出 JSON：`{passed, issues, final_output}`。

### 3. 输出判决

```json
{
  "passed": true,
  "issues": [],
  "final_output": "验收通过。所有任务均满足原始需求的验收标准。"
}
```

- `passed`：最终结论。
- `issues`：未通过或存疑时，列出具体问题。调用方可以据此决定返工、人工介入或终止。
- `final_output`：给人看的结论摘要，方便直接展示或写入日志。

---

## 输入格式详解

`acceptance.py` 接受一个 JSON。下面是每个字段的说明和示例。

```json
{
  "refine": {
    "goal": "给 agent-toolkit 增加最终验收节点 acceptance.py",
    "inputs": ["现有管线代码"],
    "outputs": ["pipeline/acceptance.py", "skills/acceptance/SKILL.md"],
    "constraints": ["保持极简低耦合", "与现有节点风格一致"],
    "acceptance": [
      "acceptance.py 能读取上游输出",
      "输出 passed/issues/final_output",
      "runner.py 串联 acceptance"
    ],
    "context": "补齐七阶段管线最后一个节点"
  },
  "prompt": {
    "prompt": "实现 acceptance.py 最终验收节点...",
    "model_hint": "deepseek-v4-pro",
    "files_to_touch": ["agent-toolkit/pipeline/acceptance.py"],
    "tools_hint": ["openai"]
  },
  "dispatch": {
    "tasks": [
      {
        "id": "task_1",
        "description": "实现 acceptance.py",
        "file": "agent-toolkit/pipeline/acceptance.py",
        "model": "deepseek-v4-flash",
        "depends_on": [],
        "prompt": "...",
        "expected_output": "完整的 acceptance.py 文件",
        "self_check": ["文件可编译", "支持 --file/--json/stdin"]
      }
    ]
  },
  "execute": {
    "results": [
      {
        "task_id": "task_1",
        "status": "success",
        "output": "已生成 acceptance.py ...",
        "file": "agent-toolkit/pipeline/acceptance.py",
        "self_check_report": "文件可编译，入口参数正常",
        "passed": true,
        "issues": [],
        "retries": 0
      }
    ]
  },
  "prune_report": {
    "path": "agent-toolkit",
    "candidates": []
  }
}
```

### 字段是否必填？

| 字段 | 是否必填 | 说明 |
|------|---------|------|
| `refine` | 建议填 | 没有原始需求，验收就失去标准。 |
| `refine.acceptance` | 强烈建议 | 这是验收的法条，为空时强模型只能凭感觉判。 |
| `prompt` | 可选 | 帮助强模型理解任务目标是如何被转述的。 |
| `dispatch` | 建议填 | 提供任务规划和 `expected_output`。 |
| `execute` | 建议填 | 提供执行结果和自检报告。 |
| `prune_report` | 可选 | 参考用，不直接影响 `passed`。 |

如果某些字段缺失，`acceptance.py` 仍然会把能拿到的东西传给模型，但结论可靠性会下降。

---

## 输出格式详解

```json
{
  "passed": false,
  "issues": [
    "task_1 的 self_check_report 声称通过，但 output 中未体现对 constraints 中 '与现有节点风格一致' 的遵循。",
    "实际文件 agent-toolkit/pipeline/acceptance.py 缺少对 Windows 编码的处理，与 intake/refine 等节点风格不一致。"
  ],
  "final_output": "验收未通过。execute 自检通过，但强模型复核发现实际文件未满足风格一致性约束，需要返工。"
}
```

### 调用方如何处理输出

```python
accept_result = accept(pipeline_state)

if accept_result["passed"]:
    # 可以进入下一阶段：通知用户、提交代码、写日志等
    print(accept_result["final_output"])
else:
    # 未通过：把 issues 回传给 dispatch 或人工
    for issue in accept_result["issues"]:
        print(f"问题：{issue}")
    # 可选：让 dispatch 重新规划，或终止流程等待人工
```

---

## 模型选择

`acceptance.py` 默认使用 `deepseek-v4-pro`，因为工作流技能明确规定：**最终验收必须强模型**。

| 场景 | 推荐模型 | 设置方式 |
|------|---------|---------|
| 默认 | `deepseek-v4-pro` | 不设置 `ACCEPTANCE_MODEL` |
| 成本敏感 / 用户偏好 | `gpt-5.6-terra` | `export ACCEPTANCE_MODEL=gpt-5.6-terra` |
| 高质量代码审查 | `claude-3.5-sonnet` / `gpt-4o` | `export ACCEPTANCE_MODEL=claude-3.5-sonnet` |
| 调试 / 快速跑通 | `deepseek-v4-flash` | `export ACCEPTANCE_MODEL=deepseek-v4-flash` |

> 注意：用 `deepseek-v4-flash` 做验收会削弱闸门作用，只建议在本地调试或非关键任务时使用。

---

## 环境变量

```bash
# 必须：API key（任一即可）
export ACCEPTANCE_API_KEY="sk-xxx"
# 或者复用 OPENAI_API_KEY
export OPENAI_API_KEY="sk-xxx"

# 可选：覆盖模型
export ACCEPTANCE_MODEL="deepseek-v4-pro"

# 可选：走 Headroom 压缩上下文
export HEADROOM_PROXY_URL="http://localhost:8787/v1"
```

---

## 用法示例

### 1. 从文件读入完整管线状态

```bash
python agent-toolkit/pipeline/acceptance.py --file pipeline_state.json
```

### 2. 从 stdin 读入

```bash
python agent-toolkit/pipeline/execute.py --file dispatch.json | \
  python agent-toolkit/pipeline/acceptance.py
```

### 3. 覆盖验收模型

```bash
python agent-toolkit/pipeline/acceptance.py --file pipeline_state.json \
  --model gpt-5.6-terra
```

### 4. 在 runner 中一键跑完整管线

```bash
export REFINE_API_KEY="sk-xxx"
export PROMPT_API_KEY="sk-xxx"
export DISPATCH_API_KEY="sk-xxx"
export EXECUTE_API_KEY="sk-xxx"
export ACCEPTANCE_API_KEY="sk-xxx"

python agent-toolkit/pipeline/runner.py --file input.txt
```

输出 JSON 会包含 `"accept"` 字段。

---

## 与 execute 自检的关系

```text
        ┌─────────────────┐
        │   dispatch      │  任务规划
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │    execute      │  弱模型执行 + 自检
        │  （第一道关）    │
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │    accept       │  强模型对照原始需求复核
        │  （第二道关）    │
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  人工确认（可选） │
        └─────────────────┘
```

- `execute` 关注的是**任务有没有按 prompt 完成**。
- `accept` 关注的是**这些结果加起来是否满足用户原始需求**。

两者视角不同，不能互相替代。

---

## 常见问题

### Q1: 为什么 accept 不自动修复问题？

 acceptance 的职责是**判决**，不是**修改**。如果让它顺手修，就会变成另一个 execute，失去独立复核的意义。发现问题后，通常有两种处理方式：

1. 把 `issues` 回传给 `dispatch`，让它重新规划子任务。
2. 终止流程，把问题和当前状态交给人工或更强的模型诊断。

### Q2: 文件读不到怎么办？

`_read_modified_files()` 只读取存在的文件。如果 `file` 指向的文件不存在，它不会报错，只是不传内容给模型。模型会根据已有信息（如 `execute.output`）做判断。

### Q3: 验收太贵，能不能省掉？

对于极其简单、单文件、低风险的任务，可以跳过 `accept`，直接以 `execute` 自检为终点。但这需要调用方显式决定，不建议默认跳过。acceptance 的 cost 通常远低于一次错误返工。

### Q4: 输出 JSON 解析失败怎么办？

`acceptance.py` 内置了 `_extract_json()`，会尝试：

1. 直接解析完整 JSON。
2. 解析 ` ```json ... ``` ` 代码块。
3. 从文本中暴力提取第一个完整 `{ ... }`。

如果还是失败，会抛出异常。此时说明强模型没有遵守 system prompt 的只输出 JSON 要求，需要检查模型版本或增加 prompt 约束。

---

## 调试技巧

如果你怀疑验收结论有问题，可以先把 `_build_user_prompt()` 生成的完整 prompt 打出来看看：

```python
from acceptance import _read_modified_files, _build_user_prompt

payload = json.loads(Path("pipeline_state.json").read_text(encoding="utf-8"))
file_contents = _read_modified_files(payload.get("dispatch", {}).get("tasks", []))
print(_build_user_prompt(payload, file_contents))
```

检查传给模型的案卷是否完整、原始需求是否被正确保留。
