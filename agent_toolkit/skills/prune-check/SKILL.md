---
name: prune-check
description: >
  功能模块验收前的固定步骤：检查当前项目结构和文件是否存在冗余，
  提出精简修改建议，但必须在不改变功能的前提下进行。
trigger: execute 节点完成、进入 acceptance 验收之前，必须运行此 skill 做一次冗余精简检查。
agent_created: true
---

# Prune Check — 冗余精简检查

## 作用

在功能模块验收前，强制检查一遍项目，找出可以精简或删除的冗余项：**只减不改功能**。

## 检查范围

1. **空目录 / 空文件**：无内容即可删除。
2. **缓存/依赖目录**：如 `__pycache__`、`.pytest_cache`、`node_modules` 等可重建目录。
3. **调试/临时文件**：文件名含 `debug`、`test`、`tmp`、`old`、`backup`、`draft`、`demo` 等。
4. **重复文件**：同名文件出现在多处，判断是否可以合并。
5. **过度工程**：单个文件职责是否过多、是否存在用不到的抽象/配置。
6. **临时测试产物**：运行测试后遗留的输出文件、日志等。

## 执行方式

先运行扫描脚本拿候选列表：

```bash
python agent-toolkit/pipeline/prune_check.py --path ./agent-toolkit --output prune_report.json
```

然后人工/Agent 审查 `prune_report.json`，确认每一项：

- 是否确实冗余？
- 删除/精简后是否影响功能？
- 如果不确定，保留，不要猜。

## 输出

```json
{
  "path": "扫描路径",
  "candidates": [
    {"type": "empty_dir", "path": "...", "reason": "..."},
    {"type": "cache_dir", "path": "...", "reason": "..."}
  ]
}
```

## 原则

- **功能不变**：任何精简都不能改变模块的对外行为。
- **保守删除**：不确定就保留，宁可多一个文件也不要误删。
- **只做建议**：脚本只输出候选，不自动删除文件。
- **极简优先**：同一功能如果可以用更少文件实现，提出合并方案。

## 在管线中的位置

```text
intake → refine → prompt_optimizer → dispatch → execute → prune-check → acceptance
```

execute 完成后、acceptance 之前，必须先做 prune-check。
