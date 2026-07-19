# Skill: Memory Manager

## 用途
管理个人长期记忆：接收对话中的关键信息，维护「当前生效版本」，归档历史版本，查询时按版本衰减权重返回。

## 核心概念

- **记忆（Memory）**：一条结构化事实、偏好、决策或约定。
- **版本（Version）**：当同主题记忆发生变更时，旧版本进入 `archive/`，新版本进入 `current/`。
- **确认数（Confirmed Count）**：该条记忆被后续对话验证/引用的次数。
- **衰减权重（Decay Weight）**：历史版本只作为参考，权重随版本差距和确认数变化：
  - `decay = 1 / (version_gap + 1) * min(confirmed_count / 3, 1)`
  - 当前版本 `weight = 1.0`

## 记忆目录

```text
agent-toolkit/memory/
├── current/           # 当前生效记忆，按主题分文件
│   ├── preferences.md
│   ├── projects.md
│   └── workflow_rules.md
└── archive/           # 历史版本，按主题 + 版本号归档
    ├── preferences-v1.md
    ├── preferences-v2.md
    └── projects-v1.md
```

## 记忆格式

每条记忆统一 frontmatter：

```markdown
---
id: mem_20260704_001
topic: preferences
version: 3
confirmed_count: 2
created_at: 2026-07-04
superseded_by: mem_20260717_001
---

内容：用户偏好结构化回复，不要长篇大论。
```

## 允许的操作

| 操作 | 触发条件 | 输出 |
|------|----------|------|
| **read_current** | 每次开始新任务前 | 返回 `current/` 中相关主题的全部记忆 |
| **write** | 用户明确表达新偏好/约定/决策 | 追加到 `current/`；若同主题已存在则升版，旧版移 `archive/` |
| **confirm** | 某条记忆被实际验证有效 | 对应记忆 `confirmed_count + 1` |
| **query_history** | 用户问「我以前怎么说的」 | 返回该主题所有版本，标明 `version` 和 `decay_weight` |
| **archive** | 记忆被明确推翻或过期 | 移入 `archive/`，标注 `superseded_by` |

## 版本迭代规则

1. **同主题内容冲突** → 升版，旧版归档。
2. **同主题补充不冲突** → 追加到当前版本，不升版。
3. **推翻旧约定** → 升版 + 旧版 `superseded_by` 指向新版。
4. **不确定是否冲突** → 先新建草稿记忆，等用户确认后再合并。

## 查询规则

- 回答当前任务时，只使用 `current/` 中的记忆作为强约束。
- `archive/` 中的记忆只在以下情况引用：
  - 用户主动问历史。
  - 需要解释「为什么现在这样做」。
- 引用历史版本时，必须说明这是「旧版本参考，权重较低」。

## 自动记忆捕获

每次对话结束后，检查是否有以下类型信息需要写入记忆：

- 新偏好（如回复风格、工具选择）
- 新项目/目标
- 新工作流约定
- 重要决策或放弃的方案
- API Key / 路径等敏感信息 → **不写入记忆**，只提醒用户自己保管

只写**事实性、长期有效**的内容，不写临时任务细节。
