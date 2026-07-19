#!/usr/bin/env python3
"""
prompt_optimizer.py — 把结构化需求转成给编程代理的精确提示词。

用法：
    python prompt_optimizer.py --file refine_output.json
    python prompt_optimizer.py --json '{"goal":"...","inputs":[],"outputs":[],...}'
    cat refine_output.json | python prompt_optimizer.py

输出 JSON：
    {
        "prompt": "给编程代理的完整提示词（Markdown）",
        "model_hint": "执行建议模型",
        "files_to_touch": ["可能涉及的文件"],
        "tools_hint": ["可能需要用的工具/库"]
    }

默认模型：deepseek-v4-flash。
"""

import io
import json
import os
import re
import sys
from pathlib import Path


# ---------- 0. 配置 ----------

from ..core.config import get_base_url, get_api_key

PROMPT_MODEL = os.environ.get("PROMPT_MODEL", "deepseek-v4-flash")
PROMPT_API_KEY = get_api_key("PROMPT_API_KEY")
PROMPT_BASE_URL = get_base_url("deepseek")


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not PROMPT_API_KEY:
        raise RuntimeError("未设置 PROMPT_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=PROMPT_API_KEY, base_url=PROMPT_BASE_URL)
    resp = client.chat.completions.create(
        model=PROMPT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=2048,
    )
    return resp.choices[0].message.content.strip()


# ---------- 2. 提示词生成 ----------

SYSTEM_PROMPT = """你是一名 Prompt Engineer。请根据用户提供的结构化需求，生成一份给编程代理的精确提示词。

要求：
1. 提示词必须直接可用，不要包含废话、解释或寒暄。
2. 明确目标、输入、输出、约束、验收标准。
3. 给出具体文件路径和操作步骤，不要只给思路。
4. 如果需求涉及修改现有代码，要求编程代理先读相关文件再改。
5. 只输出 JSON，不要 Markdown 外的任何内容。

输出 JSON 格式：
{
  "prompt": "给编程代理的完整提示词，用 Markdown，分点清晰",
  "model_hint": "执行这一步建议用什么级别的模型（例如 local-7b / gpt-4o-mini / claude-3.5-sonnet）",
  "files_to_touch": ["可能涉及的文件路径"],
  "tools_hint": ["可能需要的工具、库或命令"]
}"""


def _extract_json(text: str) -> dict:
    """从 LLM 输出里提取 JSON。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法解析 JSON: {text[:200]!r}")


def _fill_defaults(data: dict) -> dict:
    return {
        "prompt": data.get("prompt", ""),
        "model_hint": data.get("model_hint", "deepseek-v4-flash"),
        "files_to_touch": data.get("files_to_touch", []) if isinstance(data.get("files_to_touch"), list) else [],
        "tools_hint": data.get("tools_hint", []) if isinstance(data.get("tools_hint"), list) else [],
    }


def optimize(requirements: dict) -> dict:
    """把结构化需求转成编程代理提示词。"""
    if not requirements or not requirements.get("goal"):
        return _fill_defaults({"prompt": "需求为空，无法生成提示词。"})

    user_prompt = f"结构化需求：\n```json\n{json.dumps(requirements, ensure_ascii=False, indent=2)}\n```\n\n请生成编程代理提示词。"
    raw_output = _call_llm(SYSTEM_PROMPT, user_prompt)
    data = _extract_json(raw_output)
    return _fill_defaults(data)


# ---------- 3. 入口 ----------

def main() -> None:
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

    result = optimize(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
