#!/usr/bin/env python3
"""
refine.py — 把 intake 清洗后的原话转成结构化需求。

用法：
    python refine.py --file intake_output.json
    python refine.py --json '{"cleaned":"...","context":"..."}'
    cat intake_output.json | python refine.py

输出 JSON：
    {
        "goal": "核心目标（一句话）",
        "inputs": ["已有输入/附件"],
        "outputs": ["期望产出"],
        "constraints": ["限制条件"],
        "acceptance": ["验收标准"],
        "context": "保留的上下文/背景"
    }

默认模型：deepseek-v4-flash（可在环境变量 REFINE_MODEL 覆盖）。
"""

import io
import json
import os
import re
import sys
from pathlib import Path


# ---------- 0. 配置 ----------

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import get_base_url, get_api_key

REFINE_MODEL = os.environ.get("REFINE_MODEL", "deepseek-v4-flash")
REFINE_API_KEY = get_api_key("REFINE_API_KEY")
REFINE_BASE_URL = get_base_url("deepseek")


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not REFINE_API_KEY:
        raise RuntimeError("未设置 REFINE_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=REFINE_API_KEY, base_url=REFINE_BASE_URL)
    resp = client.chat.completions.create(
        model=REFINE_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    return resp.choices[0].message.content.strip()


# ---------- 2. 结构化需求提取 ----------

SYSTEM_PROMPT = """你是一名需求分析师。请把用户整理后的需求描述，转换成下面的结构化 JSON。

要求：
1. 不补充原文没有的信息。
2. 不修改原意。
3. 如果某一项确实没有，用空字符串或空数组，不要猜测。
4. 用户提到的质量要求（如"更精简"、"保留原意"、"不要报错"）必须放入 acceptance。
5. 只输出 JSON，不要解释。

输出格式：
{
  "goal": "核心目标，一句话说明要做什么",
  "inputs": ["输入1", "输入2"],
  "outputs": ["输出1", "输出2"],
  "constraints": ["约束1", "约束2"],
  "acceptance": ["验收标准1", "验收标准2"],
  "context": "相关背景或上下文"
}"""


def _extract_json(text: str) -> dict:
    """从 LLM 输出里提取 JSON，兼容 ```json 代码块。"""
    # 先尝试整个字符串解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试 ```json ... ``` 代码块
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出解析 JSON: {text[:200]!r}")


def _fill_defaults(data: dict) -> dict:
    """确保必要字段存在。"""
    return {
        "goal": data.get("goal", ""),
        "inputs": data.get("inputs", []) if isinstance(data.get("inputs"), list) else [data.get("inputs", "")],
        "outputs": data.get("outputs", []) if isinstance(data.get("outputs"), list) else [data.get("outputs", "")],
        "constraints": data.get("constraints", []) if isinstance(data.get("constraints"), list) else [data.get("constraints", "")],
        "acceptance": data.get("acceptance", []) if isinstance(data.get("acceptance"), list) else [data.get("acceptance", "")],
        "context": data.get("context", ""),
    }


def refine(cleaned: str, context: str = "") -> dict:
    """把清洗后的文本转成结构化需求。"""
    if not cleaned:
        return _fill_defaults({})

    user_prompt = f"上下文：{context}\n\n需求描述：{cleaned}\n\n请输出结构化 JSON。"
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

    # 读取输入
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        payload = json.loads(sys.argv[2])
    else:
        payload = json.loads(sys.stdin.read())

    cleaned = payload.get("cleaned", "")
    context = payload.get("context", "")

    result = refine(cleaned, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
