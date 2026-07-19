# Skill: Headroom 集成

## 用途
通过 [Headroom](https://github.com/chopratejas/headroom) 本地代理压缩 LLM 上下文，让 `agent-toolkit` 所有节点的 API 调用自动省 token。

## 工作原理

```text
pipeline/refine.py ──┐
pipeline/prompt_optimizer.py ──┼──> Headroom proxy (本地) ──> DeepSeek / OpenAI API
pipeline/dispatch.py ──┤              (自动压缩上下文)
pipeline/router.py ────┘
```

- **零侵入**：不需要改 pipeline 脚本逻辑，只需改 `HEADROOM_PROXY_URL` 环境变量。
- **全局生效**：所有使用 `core.config.get_base_url()` 的节点自动走代理。
- **可叠加**：配合 router（避免非编程任务进管线）+ dispatch（简单任务不规划），实现多层节省。

## 安装

```bash
pip install headroom
```

## 启动

### Windows

```bat
agent-toolkit\scripts\start_headroom.bat 8787
```

### macOS / Linux / Git Bash

```bash
./agent-toolkit/scripts/start_headroom.sh 8787
```

## 使用

启动 Headroom 后，设置环境变量：

```bash
export HEADROOM_PROXY_URL="http://localhost:8787/v1"
export ROUTER_API_KEY="sk-xxx"
export REFINE_API_KEY="sk-xxx"
export PROMPT_API_KEY="sk-xxx"
export DISPATCH_API_KEY="sk-xxx"

python agent-toolkit/pipeline/runner.py --file input.txt
```

## 配置优先级

`core/config.py` 中 base URL 的读取优先级：

1. `HEADROOM_PROXY_URL`（推荐，一劳永逸）
2. `DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL`（按 provider 覆盖）
3. 默认值（`https://api.deepseek.com/v1`）

## 关闭 Headroom

直接unset环境变量即可：

```bash
unset HEADROOM_PROXY_URL
```

## 注意事项

1. Headroom 首次运行需要下载压缩模型（约 500MB）。
2. 需要 Headroom 进程常驻后台。
3. 某些需要原文精读的场景（法律/合同审查）可临时关闭。
