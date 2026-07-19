#!/usr/bin/env python3
"""
acceptance.py — 最终验收节点。

对照原始需求（refine 输出）验收 execute 结果，必要时读取实际修改的文件内容，
由强模型判断整个任务是否合格。

用法：
    python acceptance.py --file pipeline_state.json
    python acceptance.py --json '{"refine":{...},"execute":{...}}'
    cat pipeline_state.json | python acceptance.py

输入 JSON（可只提供关键字段）：
    {
        "refine": { "goal", "inputs", "outputs", "constraints", "acceptance", "context" },
        "prompt": { "prompt", "model_hint", "files_to_touch", "tools_hint" },
        "dispatch": { "tasks": [...] },
        "execute": { "results": [...] },
        "prune_report": { ... }   // 可选
    }

输出 JSON：
    {
        "passed": true,
        "issues": [],
        "final_output": "验收结论摘要"
    }

环境变量：
    ACCEPTANCE_API_KEY / OPENAI_API_KEY
    ACCEPTANCE_MODEL（默认 deepseek-v4-pro，可覆盖为 gpt-5.6-terra / claude-3.5-sonnet 等）
    HEADROOM_PROXY_URL
"""

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

from ..core.config import get_base_url, get_api_key


# ---------- 0. 配置 ----------

ACCEPTANCE_MODEL = os.environ.get("ACCEPTANCE_MODEL", "deepseek-v4-pro")
ACCEPTANCE_API_KEY = get_api_key("ACCEPTANCE_API_KEY")
ACCEPTANCE_BASE_URL = get_base_url("deepseek")


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str, model: str, max_tokens: int = 2048) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not ACCEPTANCE_API_KEY:
        raise RuntimeError("未设置 ACCEPTANCE_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=ACCEPTANCE_API_KEY, base_url=ACCEPTANCE_BASE_URL)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _extract_json(text: str) -> dict:
    """从 LLM 输出里提取 JSON，兼容代码块、截断、尾部噪声。"""
    text = text.strip()
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

    for match in re.finditer(r'\{', text):
        start = match.start()
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"无法解析 JSON: {text[:300]!r}")


# ---------- 2. 文件读取 ----------

def _read_modified_files(tasks: list) -> dict[str, str]:
    """读取 dispatch 任务中涉及且实际存在的文件内容，供验收参考。"""
    contents: dict[str, str] = {}
    seen: set[str] = set()
    for task in tasks:
        file_path = task.get("file", "")
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)
        p = Path(file_path)
        if p.exists() and p.is_file():
            try:
                contents[file_path] = p.read_text(encoding="utf-8")
            except Exception as e:
                contents[file_path] = f"<读取失败: {e}>"
    return contents


# ---------- 3. 验收逻辑 ----------

SYSTEM_PROMPT = """你是一名严格的验收评审。请对照用户原始需求和执行结果，判断任务是否真正完成。

验收规则：
1. 逐条检查原始需求中的 `acceptance`（验收标准）和 `constraints`（约束）。
2. 检查 `execute.results` 中每个任务是否 `passed == true`；未通过的任务直接视为不合格。
3. 检查任务输出是否满足对应任务的 `expected_output`。
4. 检查实际修改的文件内容是否符合原始需求，是否存在遗漏、错误、无关改动。
5. 如果提供了 `prune_report`，只作为参考，不影响功能验收结论。
6. 结论必须诚实：有明显问题就判不通过，不要为了表面和谐而通过。
7. 只输出 JSON，不要 Markdown 代码块外的任何内容。

输出 JSON 格式：
{
  "passed": true,
  "issues": ["如果未通过或存疑，列出具体问题"],
  "final_output": "用一句话到一段话总结验收结论，说明是否通过及原因"
}"""


def _build_user_prompt(payload: dict, file_contents: dict[str, str]) -> str:
    """把上游各阶段输出组装成给验收模型的 user prompt。"""
    refine = payload.get("refine", {})
    prompt = payload.get("prompt", {})
    dispatch = payload.get("dispatch", {})
    execute = payload.get("execute", {})
    prune_report = payload.get("prune_report", {})

    parts = [
        "## 原始需求（refine 输出）",
        json.dumps(refine, ensure_ascii=False, indent=2),
        "",
        "## 编程代理提示词（prompt_optimizer 输出）",
        json.dumps(prompt, ensure_ascii=False, indent=2),
        "",
        "## 任务规划（dispatch 输出）",
        json.dumps(dispatch, ensure_ascii=False, indent=2),
        "",
        "## 执行结果（execute 输出）",
        json.dumps(execute, ensure_ascii=False, indent=2),
    ]

    if file_contents:
        parts.extend([
            "",
            "## 实际修改的文件内容",
            json.dumps(file_contents, ensure_ascii=False, indent=2),
        ])

    if prune_report:
        parts.extend([
            "",
            "## 冗余检查报告（prune_check 输出，仅供参考）",
            json.dumps(prune_report, ensure_ascii=False, indent=2),
        ])

    parts.append("\n请输出验收 JSON。")
    return "\n".join(parts)


def _fill_defaults(data: dict) -> dict:
    """确保输出格式稳定。"""
    return {
        "passed": bool(data.get("passed", False)),
        "issues": data.get("issues", []) if isinstance(data.get("issues"), list) else [],
        "final_output": data.get("final_output", ""),
    }


def accept(payload: dict, model: str = "") -> dict:
    """执行最终验收，返回 {passed, issues, final_output}。"""
    if not payload:
        return _fill_defaults({
            "passed": False,
            "issues": ["输入为空，无法验收"],
            "final_output": "未收到上游管线输出，验收失败。",
        })

    tasks = payload.get("dispatch", {}).get("tasks", [])
    file_contents = _read_modified_files(tasks)

    user_prompt = _build_user_prompt(payload, file_contents)
    model = model or ACCEPTANCE_MODEL

    raw_output = _call_llm(SYSTEM_PROMPT, user_prompt, model)
    data = _extract_json(raw_output)
    return _fill_defaults(data)


# ---------- 4. 入口 ----------

def main() -> None:
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="最终验收 execute 结果")
    parser.add_argument("--file", help="包含上游各阶段输出的 JSON 文件")
    parser.add_argument("--json", help="包含上游各阶段输出的 JSON 字符串")
    parser.add_argument("--model", help="覆盖验收模型（默认读取 ACCEPTANCE_MODEL）")
    args = parser.parse_args()

    if args.file:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    elif args.json:
        payload = json.loads(args.json)
    else:
        payload = json.loads(sys.stdin.read())

    result = accept(payload, model=args.model or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
