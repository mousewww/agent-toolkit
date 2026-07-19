---
name: intake
description: >
  接收用户原话，捋顺语句、去除口语填充和冗余表达，保留原意，
  并提取附件（路径/URL/代码块）。作为工作流第一个节点运行。
trigger: 用户表达需求、任务或想法时，先运行此 skill 把原话清洗成可直接下游处理的结构化输入。
agent_created: true
---

# Intake — 原话清洗

## 作用

把用户的口语化、重复、发散表达，整理成一句/一段干净、完整、可执行意图清晰的文本。

**只做三件事：**
1. 去冗余：删填充词（嗯、那个、就是、然后、我觉得……）。
2. 保原意：不增删事实，不脑补需求。
3. 提附件：把路径、URL、代码块单独列出来。

## 输入

- 用户原话（字符串）
- 可选：上下文记忆 / 当前任务主题

## 输出

```json
{
  "raw": "原始输入",
  "cleaned": "整理后的文本",
  "attachments": [
    {"type": "path", "value": "C:/Users/.../file.py"},
    {"type": "url", "value": "https://..."},
    {"type": "code", "value": "print('hello')"}
  ],
  "intent_hint": "implement | fix | explain | review | ask"
}
```

## 执行方式

```bash
# 推荐：从文件读，Windows 中文最稳
python agent-toolkit/pipeline/intake.py --file raw.txt

# 或 stdin（确保 UTF-8）
python agent-toolkit/pipeline/intake.py < raw.txt

# 命令行传参在 Windows Git Bash 下容易乱码，不推荐
python agent-toolkit/pipeline/intake.py "你说的原话"
```

## 规则

- 不回答用户问题，只清洗输入。
- 不补充任何用户没提到的信息。
- 遇到歧义不要猜测，原样保留并在 `intent_hint` 标 `ask`。
- 路径中的反斜杠统一保留原样，下游自己处理。
