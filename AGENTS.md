# Agent Toolkit — Agent 编码指南

本文件面向 AI 编码 Agent。阅读者应当被当作完全不了解本项目的新成员。

## 1. 项目概述

`agent-toolkit` 是一个**个人 Agent 工具箱**，用于把用户的自然语言请求转换为可执行、可验收的编程任务结果。

核心设计原则：

- **一个文件一个功能**：不要为了低耦合强行拆分。
- **一个 skill 一个职责**：`skills/` 下的每个目录只描述一个工作流节点。
- **数据、逻辑、配置分离**：配置集中在 `core/config.py`，业务逻辑在 `pipeline/`。
- **工作流七阶段固定**：`intake → refine → clarify → prompt_optimize → dispatch → execute → prune-check → accept`。
- **最外层有 `router` 分流**：先按请求类型分流为 `programming / search / chat / tool`，非编程任务不进入完整管线。
- **dispatch 自带路由**：简单任务（单文件、无复杂关键词）直接生成单任务，不调用强模型规划。
- **记忆带版本和衰减**：旧版本只参考、不主导当前决策（当前处于设计阶段，见 `memory/`）。

项目语言：**中文**（注释、文档、提交信息、LLM 提示词均使用中文）。

## 2. 技术栈

- **Python 3.x**：唯一运行时语言。
- **openai**：唯一的 Python 依赖（`pip install openai`），用于调用 OpenAI 兼容接口。
- **DeepSeek API**：默认 provider，默认模型为 `deepseek-v4-flash`。
- **DuckDuckGo Instant Answer API**：免费、无需 key，用于 `search` 路由的简单联网搜索。
- **Headroom**（可选）：本地上下文压缩代理，可节省 LLM token。

> 注意：项目**没有** `requirements.txt`、`pyproject.toml`、`setup.py` 等包管理文件。唯一的外部依赖是 `openai`；Headroom 仅在需要时单独安装。

## 3. 目录结构与模块划分

```text
agent-toolkit/
├── core/                      # 配置、数据库、日志、版本（当前只有配置）
│   └── config.py              # 统一 API 配置 + Headroom 支持
├── memory/                    # 长期记忆（current + archive + 衰减权重）
│   └── logs/                  # 按日期命名的 Markdown 记忆日志
├── pipeline/                  # 处理管线脚本（核心逻辑）
│   ├── router.py              # 最外层路由：programming / search / chat / tool
│   ├── intake.py              # 节点1：原话清洗（规则化，不走 LLM）
│   ├── refine.py              # 节点2：结构化需求
│   ├── prompt_optimizer.py    # 节点3：提示词优化
│   ├── dispatch.py            # 节点4：任务规划（含简单任务规则路由）
│   ├── execute.py             # 节点5：弱模型执行 + 自检 + 返工
│   ├── prune_check.py         # 节点6：冗余精简检查
│   └── runner.py              # 前五节点串联入口
├── scripts/                   # 辅助脚本
│   ├── start_headroom.sh      # 启动 Headroom 代理（macOS/Linux/Git Bash）
│   └── start_headroom.bat     # 启动 Headroom 代理（Windows CMD）
├── skills/                    # Agent 注入式 skill 说明文档
│   ├── router/                # 最外层路由 skill
│   ├── intake/                # 原话清洗 skill
│   ├── refine/                # 结构化需求 skill
│   ├── prompt-optimizer/      # 提示词优化 skill
│   ├── dispatch/              # 任务规划 skill
│   ├── execute/               # 执行任务 skill
│   ├── prune-check/           # 冗余检查 skill
│   ├── workflow-orchestrator/ # 工作流总览
│   ├── memory-manager/        # 记忆管理 skill
│   └── headroom/              # Headroom 集成说明
├── tests/                     # 测试与诊断脚本
│   └── test_apis.py           # 测试 API 端点和模型延迟
└── README.md                  # 项目主文档
```

### 模块职责

| 模块 | 职责 | 当前状态 |
|------|------|----------|
| `pipeline/router.py` | 最外层分流，直接处理 search/chat， programming 进入 runner | 已完成 |
| `pipeline/intake.py` | 规则化去口语词、提取附件（路径/URL/代码块） | 已完成 |
| `pipeline/refine.py` | 输出 `goal/inputs/outputs/constraints/acceptance/context` | 已完成 |
| `pipeline/clarify.py` | 开工前澄清需求：问题、假设、缺失信息 | 已完成 |
| `pipeline/prompt_optimizer.py` | 把结构化需求转成编程代理可用 prompt | 已完成 |
| `pipeline/dispatch.py` | 复杂任务拆解，简单任务走规则路由 | 已完成 |
| `pipeline/execute.py` | 拓扑排序、任务隔离、自检、返工、可选并行、备份写文件 | 已完成 |
| `pipeline/prune_check.py` | 扫描空目录/缓存/重复名/临时文件，只输出候选不删除 | 已完成 |
| `pipeline/runner.py` | 串联 intake → refine → clarify → prompt_optimizer → dispatch → execute → accept | 已完成 |
| `pipeline/acceptance.py` | 强模型对照原始需求验收 execute 结果 | 已完成 |
| `memory/memory.py` | 版本化记忆系统 | **待实现** |
| `workers/tasks/` | 24h 自动化任务框架 | **待实现** |
| `core/db.py` / `core/logger.py` | 数据库、运行日志持久化 | **待实现** |

## 4. 运行时架构

### 4.1 顶层分流

```text
[raw_input] → router ──→ search  → DuckDuckGo 联网搜索 + v4-flash 总结
            ├─→ chat   → v4-flash 直接回答
            ├─→ tool   → 调用对应工具（待扩展）
            └─→ programming → 进入编程代理七阶段管线
```

### 4.2 编程代理七阶段管线

```text
intake → refine → clarify → prompt_optimize → dispatch → execute → prune-check → accept → output
```

| 阶段 | 职责 | 默认模型/实现 | 说明 |
|------|------|---------------|------|
| **router** | 请求分类 | `deepseek-v4-flash` | 一次调用，避免非编程任务进入完整管线 |
| **intake** | 原话清洗 | Python 规则 | 速度最快、零成本；可选 `INTAKE_MODEL` 做语义级整理 |
| **refine** | 结构化需求 | `deepseek-v4-flash` | 输出 goal/inputs/outputs/constraints/acceptance |
| **clarify** | 需求澄清 | `deepseek-v4-flash` | 发现模糊点、缺失约束、隐式假设；支持项目独立领域模板 |
| **prompt_optimize** | 提示词优化 | `deepseek-v4-flash` | 输出编程代理 prompt + model_hint + files + tools |
| **dispatch** | 任务规划 | `deepseek-v4-flash` / 规则路由 | 简单任务直接生成单任务，复杂任务才调模型 |
| **execute** | 任务执行 | `deepseek-v4-flash` / 本地模型 | 拓扑排序、自检、返工 2 次、可选并行 |
| **prune-check** | 冗余检查 | Python 规则扫描 | 只输出候选，不自动删除 |
| **accept** | 最终验收 | 强模型（如 `deepseek-v4-pro` / `claude-3.5-sonnet`） | **尚未实现** |

### 4.3 模型选择原则

1. **规划与验收尽量用强模型，但 dispatch 有路由**：复杂/多文件任务才调强模型规划；简单单文件任务直接走规则路由。
2. **验收必须强模型**：最终闸门决定方向和质量，不能降级。
3. **refine / prompt_optimize 用 v4-flash**：速度优先，够用即可。
4. **dispatch 简单任务走规则路由**：单文件、无复杂关键词时直接生成单任务，不调用强模型。
5. **执行可降级**：只要 prompt 足够精确，7B 级别 coder 模型足够处理 80% 的局部修改。
6. **intake 尽量不用 LLM**：先用规则/正则/脚本处理，搞不定再调用轻量模型。
7. **联网/多模态只在需要时启用**：由 dispatch 阶段判断是否需要联网搜索或多模态理解。
8. **prune-check 先规则扫描，再模型/人工审查**：脚本只输出候选，是否精简由 Agent/人判断。

## 5. 环境变量与配置

所有 API 配置集中在 `core/config.py`。base URL 读取优先级：

1. `HEADROOM_PROXY_URL`（全局代理，推荐）
2. `<PROVIDER>_BASE_URL`（如 `DEEPSEEK_BASE_URL`）
3. `OPENAI_BASE_URL` / `OPENAI_API_BASE`
4. 默认值（`https://api.deepseek.com/v1`）

常用环境变量：

```bash
# 全局代理（可选）
export HEADROOM_PROXY_URL="http://localhost:8787/v1"

# 各节点 API key（未设置时 fallback 到 OPENAI_API_KEY）
export OPENAI_API_KEY="sk-xxx"
export ROUTER_API_KEY="sk-xxx"
export REFINE_API_KEY="sk-xxx"
export CLARIFY_API_KEY="sk-xxx"
export PROMPT_API_KEY="sk-xxx"
export DISPATCH_API_KEY="sk-xxx"
export EXECUTE_API_KEY="sk-xxx"

# 各节点模型覆盖（可选）
export ROUTER_MODEL="deepseek-v4-flash"
export REFINE_MODEL="deepseek-v4-flash"
export CLARIFY_MODEL="deepseek-v4-flash"
export PROMPT_MODEL="deepseek-v4-flash"
export DISPATCH_MODEL="deepseek-v4-flash"
export EXECUTE_MODEL=""               # 覆盖所有任务中的 model 字段

# dispatch 强制走模型规划（调试用）
export DISPATCH_FORCE_PLAN=1
```

## 6. 常用命令

### 安装依赖

```bash
pip install openai
```

### 启动 Headroom（可选）

```bash
# macOS / Linux / Git Bash
./agent-toolkit/scripts/start_headroom.sh 8787

# Windows CMD
agent-toolkit\scripts\start_headroom.bat 8787
```

然后设置 `HEADROOM_PROXY_URL=http://localhost:8787/v1`。

### 单个节点调试

```bash
# 最外层路由
python agent-toolkit/pipeline/router.py --raw "今天北京天气怎样"
python agent-toolkit/pipeline/router.py --file input.txt

# intake
python agent-toolkit/pipeline/intake.py --file input.txt

# refine
python agent-toolkit/pipeline/intake.py --file input.txt | python agent-toolkit/pipeline/refine.py

# prompt_optimizer
python agent-toolkit/pipeline/intake.py --file input.txt | \
  python agent-toolkit/pipeline/refine.py | \
  python agent-toolkit/pipeline/prompt_optimizer.py

# dispatch
python agent-toolkit/pipeline/prompt_optimizer.py --file refine_output.json | \
  python agent-toolkit/pipeline/dispatch.py

# execute（只生成结果，不写文件）
python agent-toolkit/pipeline/dispatch.py --file prompt_output.json | \
  python agent-toolkit/pipeline/execute.py

# execute（实际写文件，自动备份 .execute.bak）
python agent-toolkit/pipeline/dispatch.py --file prompt_output.json | \
  python agent-toolkit/pipeline/execute.py --apply

# execute（同层级任务并行）
python agent-toolkit/pipeline/execute.py --file dispatch.json --apply --parallel

# prune-check
python agent-toolkit/pipeline/prune_check.py --path agent-toolkit --output prune_report.json
```

### 完整管线（runner）

```bash
export REFINE_API_KEY=...
export CLARIFY_API_KEY=...
export PROMPT_API_KEY=...
export DISPATCH_API_KEY=...
export EXECUTE_API_KEY=...

python agent-toolkit/pipeline/runner.py --file input.txt

# 先跑需求澄清（输出 Markdown 清单，不阻塞）
python agent-toolkit/pipeline/runner.py \
  --file active/aliexpress/input.txt \
  --clarify \
  --domain-file active/aliexpress/clarify-prompt.md
```

> `runner.py` 默认只生成结果，不实际写文件。如需写文件，目前请单独调用 `execute.py --apply`。

### API 可用性测试

```bash
python agent-toolkit/tests/test_apis.py deepseek https://api.deepseek.com/v1 $KEY deepseek-v4-flash
python agent-toolkit/tests/test_apis.py packy https://api-slb.packyapi.com/v1 $KEY gpt-5.6-luna
```

## 7. 代码风格与开发约定

### 7.1 文件组织

- 每个 `pipeline/*.py` 文件对应一个工作流节点，职责单一。
- 每个 `skills/<node>/SKILL.md` 文档对应该节点的 Agent 使用说明。
- `core/config.py` 是唯一的集中配置入口，各节点通过 `sys.path.insert` 引入。

### 7.2 编码规范

- 使用 Python 3 类型注解（`list[dict[str, str]]`、`dict[str, Any]` 等）。
- 函数/模块 docstring 使用中文，说明用途、输入、输出。
- 节点脚本统一支持三种输入方式：`--file`、`--json`、stdin。
- 所有节点输出统一为 `json.dumps(..., ensure_ascii=False, indent=2)`。
- Windows/Git Bash 环境下必须处理 stdin/stdout 编码：

```python
if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
```

### 7.3 JSON 解析容错

LLM 输出可能包含 Markdown 代码块、截断或尾部噪声。所有节点都应使用 `_extract_json()` 函数兼容以下情况：

1. 完整 JSON 字符串
2. ` ```json ... ``` ` 代码块
3. 从文本中暴力提取第一个完整 `{ ... }` 或 `[ ... ]`

### 7.4 错误处理

- 缺少依赖时给出明确安装提示： `"请先安装 openai: pip install openai"`。
- 缺少 API key 时给出明确环境变量提示。
- execute 阶段返工 2 次仍失败则抛出异常，由上层强模型诊断。

### 7.5 安全与风险

- `execute.py --apply` 会实际写文件，写之前自动备份到 `<file>.execute.bak`。
- 备份在任务成功并通过自检后自动清理；失败时自动恢复。
- `prune_check.py` **只输出候选，不自动删除任何文件**。
- 所有 LLM 调用默认走外部 API，敏感数据可考虑本地模型或关闭 Headroom。

## 8. 测试策略

当前测试覆盖较薄：

- `tests/test_apis.py`：手动测试 API 端点可用性与延迟，不是自动化单元测试。
- 没有 pytest/unittest 套件，也没有 CI。

### 建议的测试方式

1. **API 连通性**：运行 `tests/test_apis.py` 验证 key、base_url、模型名是否正确。
2. **节点端到端**：准备一个 `input.txt`，依次跑通 `router → runner` 或单个节点，检查 JSON 输出格式。
3. **execute 写文件**：先用 `--apply` 在小文件上测试，确认 `.execute.bak` 备份和恢复机制正常。
4. **prune-check**：在副本目录上运行，确认不会误删文件。

## 9. 部署与运行

本项目是本地脚本集合，**没有打包、容器化或远程部署流程**。

运行方式：

1. 克隆/拉取代码。
2. `pip install openai`。
3. 配置环境变量（至少 `OPENAI_API_KEY`）。
4. 可选：安装并启动 Headroom。
5. 通过 `pipeline/router.py` 或 `pipeline/runner.py` 调用。

## 10. 当前限制与下一步

### 已知限制

- 没有依赖清单文件（`requirements.txt` / `pyproject.toml`）。
- 没有自动化测试框架。
- `execute.py --apply` 目前只能由 `execute.py` 直接调用，`runner.py` 还不支持 `--apply` 开关。
- `acceptance.py` 尚未实现，最终验收依赖人工或后续强模型节点。
- `memory/memory.py` 和 `workers/tasks/` 尚未实现。

### 高优先级待办

1. 设计 `memory/memory.py` 版本化记忆系统（current + archive + 衰减权重）。
2. 搭建 `workers/tasks/` 24h 自动化任务框架。
3. 为 `runner.py` 添加 `--apply` 开关，允许在完整管线中实际写文件。
4. 补充 `requirements.txt` 和基础 pytest 单元测试。

## 11. 参考资料

- `README.md`：项目主文档，含每个节点的详细用法示例。
- `skills/workflow-orchestrator/SKILL.md`：完整七阶段管线说明。
- `skills/<node>/SKILL.md`：各节点 Agent 使用说明。
- `memory/logs/2026-07-18.md`：项目关键决策与偏好记录。
