#!/usr/bin/env python3
"""
dispatch.py — 把优化后的编程代理提示词拆解成可执行子任务。

用法：
    python dispatch.py --file prompt_output.json
    python dispatch.py --json '{"prompt":"...","files_to_touch":[],...}'
    cat prompt_output.json | python dispatch.py

输出 JSON：
    {
        "tasks": [
            {
                "id": "task_1",
                "description": "任务简述",
                "file": "主要操作的文件路径",
                "model": "建议执行模型",
                "depends_on": [],
                "prompt": "给执行代理的精简提示词",
                "expected_output": "期望产出",
                "self_check": ["自检项1", "自检项2"]
            }
        ]
    }

默认模型：deepseek-v4-flash（可在环境变量 DISPATCH_MODEL 覆盖）。
dispatch 负责判断任务复杂度并决定是否需要拆解：
- 简单任务（单文件、无复杂关键词）直接生成单任务，不调用 LLM，毫秒级完成。
- 复杂任务才调用模型进行规划拆解。
可通过 DISPATCH_FORCE_PLAN=1 强制所有任务都走模型规划。
"""

import io
import json
import os
import re
import sys
from pathlib import Path


# ---------- 0. 配置 ----------

from ..core.config import get_base_url, get_api_key

DISPATCH_MODEL = os.environ.get("DISPATCH_MODEL", "deepseek-v4-flash")
DISPATCH_API_KEY = get_api_key("DISPATCH_API_KEY")
DISPATCH_BASE_URL = get_base_url("deepseek")
DISPATCH_FORCE_PLAN = os.environ.get("DISPATCH_FORCE_PLAN", "0") == "1"

# 触发强模型规划的关键词
_COMPLEX_HINTS = (
    "重构", "架构", "多文件", "跨文件", "拆分", "依赖", "复杂", "大型",
    "模块", "设计", "迁移", "整合", "解耦", "接口", "重构为", "拆分为",
    "refactor", "architecture", "multi-file", "cross-file", "split",
    "dependency", "complex", "large", "module", "design", "migrate",
    "integrate", "decouple", "interface"
)

# 常见基础工具，不构成任务复杂度
_GENERIC_TOOLS = {"python", "python 3.x", "python3", "re", "os", "json", "sys", "pathlib"}


# ---------- 1. 路由判断 ----------

def _is_simple_task(prompt_package: dict) -> bool:
    """判断是否为简单任务，可直接单任务执行而不调用强模型。"""
    files = prompt_package.get("files_to_touch", [])
    tools = prompt_package.get("tools_hint", [])
    prompt = prompt_package.get("prompt", "")

    # 多文件直接判定为复杂任务
    if len(files) > 1:
        return False

    # 过滤通用工具后，若仍有多个特定工具/库，认为不简单
    specific_tools = [t for t in tools if t.lower() not in _GENERIC_TOOLS]
    if len(specific_tools) > 1:
        return False

    # 提示词中出现复杂关键词，交给强模型规划
    lower_prompt = prompt.lower()
    for hint in _COMPLEX_HINTS:
        if hint.lower() in lower_prompt:
            return False
    return True


def _make_single_task(prompt_package: dict) -> dict:
    """为简单任务直接生成单任务结果。"""
    prompt = prompt_package.get("prompt", "")
    files = prompt_package.get("files_to_touch", [])
    tools = prompt_package.get("tools_hint", [])
    model_hint = prompt_package.get("model_hint", "")

    file = files[0] if files else ""
    # 简单任务默认交给轻量模型执行
    model = model_hint or "local-7b-coder"

    return {
        "tasks": [
            {
                "id": "task_1",
                "description": prompt.split("\n")[0][:60] or "执行提示词任务",
                "file": file,
                "model": model,
                "depends_on": [],
                "prompt": prompt,
                "expected_output": "按提示词完成指定修改或实现",
                "self_check": [
                    "功能按提示词正确实现",
                    "不引入无关改动",
                    "不影响其他文件功能",
                ] + ([f"正确使用工具/库：{', '.join(tools)}"] if tools else []),
            }
        ]
    }


# ---------- 2. LLM 调用 ----------

def _call_llm(system: str, user: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not DISPATCH_API_KEY:
        raise RuntimeError("未设置 DISPATCH_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=DISPATCH_API_KEY, base_url=DISPATCH_BASE_URL)
    resp = client.chat.completions.create(
        model=DISPATCH_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    return resp.choices[0].message.content.strip()


# ---------- 2. 任务拆解 ----------

SYSTEM_PROMPT = """你是一个任务规划器。输入是一份给编程代理的提示词，请把它拆分为可独立执行的子任务列表，输出 JSON。

规则：
1. 每个子任务只负责一个文件或一个明确操作。
2. 用 depends_on 标明任务之间的依赖顺序。
3. 单文件、单目标的提示词只输出一个任务；多文件、多步骤才拆分。
4. 不要解释，只输出 JSON。

必须严格输出以下 JSON 格式：
{
  "tasks": [
    {
      "id": "task_1",
      "description": "一句话描述任务",
      "file": "要操作的文件路径，没有则空字符串",
      "model": "建议执行模型，例如 local-7b-coder / deepseek-v4-flash / gpt-4o-mini",
      "depends_on": [],
      "prompt": "给执行代理的精简提示词",
      "expected_output": "任务完成后应产出的结果",
      "self_check": ["自检项1", "自检项2"]
    }
  ]
}

注意：一定要输出 tasks 数组，且至少包含一个任务。"""


def _extract_json(text: str) -> dict:
    """从 LLM 输出里提取 JSON，尽量兼容尾部噪声、代码块、截断等情况。"""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("LLM 输出为空")

    # 1. 完整字符串解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2. 尝试 ```json ... ``` 代码块
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 尝试从文本中提取第一个完整的 JSON 对象或数组
    # 先找 { ... } 匹配
    for match in re.finditer(r'\{', cleaned):
        start = match.start()
        for end in range(len(cleaned), start, -1):
            snippet = cleaned[start:end]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue

    # 再找 [ ... ] 匹配
    for match in re.finditer(r'\[', cleaned):
        start = match.start()
        for end in range(len(cleaned), start, -1):
            snippet = cleaned[start:end]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"无法解析 JSON: {cleaned[:300]!r}")


def _fill_defaults(data: dict) -> dict:
    """确保输出格式稳定。"""
    tasks = data.get("tasks", []) if isinstance(data.get("tasks"), list) else []
    normalized = []
    for t in tasks:
        normalized.append({
            "id": t.get("id", f"task_{len(normalized)+1}"),
            "description": t.get("description", ""),
            "file": t.get("file", ""),
            "model": t.get("model", "deepseek-v4-flash"),
            "depends_on": t.get("depends_on", []) if isinstance(t.get("depends_on"), list) else [],
            "prompt": t.get("prompt", ""),
            "expected_output": t.get("expected_output", ""),
            "self_check": t.get("self_check", []) if isinstance(t.get("self_check"), list) else [],
        })
    return {"tasks": normalized}


def dispatch(prompt_package: dict) -> dict:
    """把 prompt_optimizer 的输出拆成任务列表。"""
    prompt = prompt_package.get("prompt", "")
    if not prompt:
        return _fill_defaults({})

    # 路由：简单任务直接走单任务，不调用强模型；除非强制规划
    if not DISPATCH_FORCE_PLAN and _is_simple_task(prompt_package):
        return _fill_defaults(_make_single_task(prompt_package))

    files = prompt_package.get("files_to_touch", [])
    tools = prompt_package.get("tools_hint", [])
    model_hint = prompt_package.get("model_hint", "")

    user_prompt = f"""编程代理提示词：
{prompt}

建议模型：{model_hint or '未指定'}
可能涉及的文件：{json.dumps(files, ensure_ascii=False)}
可能需要的工具/库：{json.dumps(tools, ensure_ascii=False)}

请拆解为可执行子任务，输出 JSON。"""

    raw_output = _call_llm(SYSTEM_PROMPT, user_prompt)
    data = _extract_json(raw_output)
    return _fill_defaults(data)


# ---------- 3. 入口 ----------

def main() -> None:
    # Windows/Git Bash 强制 UTF-8
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        payload = json.loads(sys.argv[2])
    else:
        payload = json.loads(sys.stdin.read())

    result = dispatch(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
