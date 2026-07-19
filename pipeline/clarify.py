#!/usr/bin/env python3
"""
clarify.py — 需求澄清节点。

在 refine 之后、prompt_optimize 之前插入，主动发现需求中的模糊点、
缺失约束和隐式假设，避免下游Agent返工浪费token。

用法：
    # 检查清单模式（默认）：输出 JSON/Markdown 清单
    python clarify.py --file refine_output.json
    python clarify.py --json '{"cleaned":"...","context":"..."}'

    # 交互模式：命令行逐条提问并收集答案
    python clarify.py --file refine_output.json --interactive

    # 使用领域模板（当前支持 aliexpress）
    python clarify.py --file refine_output.json --domain aliexpress

输出 JSON：
    {
        "status": "needs_clarification" | "complete",
        "questions": [
            {"id": "q1", "question": "...", "why": "...", "category": "...", "priority": "must"}
        ],
        "assumptions": [
            {"id": "a1", "assumption": "...", "risk": "...", "verify": "..."}
        ],
        "missing": ["..."],
        "summary": "...",
        "answers": {}           # 交互模式下用户回答
    }

环境变量：
    CLARIFY_API_KEY / OPENAI_API_KEY
    CLARIFY_MODEL（默认 deepseek-v4-flash）
"""

import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------- 0. 配置 ----------

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import get_base_url, get_api_key

CLARIFY_MODEL = os.environ.get("CLARIFY_MODEL", "deepseek-v4-flash")
CLARIFY_API_KEY = get_api_key("CLARIFY_API_KEY")
CLARIFY_BASE_URL = get_base_url("deepseek")

SKILLS_DIR = Path(__file__).parent.parent / "skills" / "clarify"


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not CLARIFY_API_KEY:
        raise RuntimeError("未设置 CLARIFY_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=CLARIFY_API_KEY, base_url=CLARIFY_BASE_URL)
    resp = client.chat.completions.create(
        model=CLARIFY_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=2048,
    )
    return resp.choices[0].message.content.strip()


# ---------- 2. JSON 解析 ----------

def _extract_json(text: str) -> dict:
    """兼容完整 JSON、```json 代码块、文本中第一个 {}。"""
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

    # 暴力提取第一个完整对象
    start = text.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"无法从 LLM 输出解析 JSON: {text[:200]!r}")


# ---------- 3. Prompt 组装 ----------

BASE_SYSTEM_PROMPT = """你是一名资深项目经理（PM）。你的任务是在开发开工前，
对用户需求进行一次严格的澄清审查，找出所有模糊点、缺失约束和隐式假设。

审查维度：
1. 目标边界：用户到底想解决什么问题？范围是否明确？
2. 输入数据：需要哪些数据来源？格式、数量、获取方式是否明确？
3. 输出交付：期望产出是什么？文件、API、界面、还是可执行脚本？
4. 环境与平台：操作系统、浏览器、账号体系、IP/指纹环境？
5. 流程与异常：正常流程是什么？异常情况（登录失败、验证码、网络超时、页面变动）如何处理？
6. 质量与验收：怎样算"能用"？怎样算"好用"？有量化指标吗？
7. 安全与合规：是否涉及账号安全、平台风控、隐私数据、商业协议？

输出格式（严格 JSON）：
{
  "status": "needs_clarification" | "complete",
  "questions": [
    {
      "id": "q1",
      "question": "具体问题，用户能直接回答",
      "why": "为什么这个问题会影响实现",
      "category": "目标/输入/输出/环境/流程/异常/验收/安全",
      "priority": "must | should | nice"
    }
  ],
  "assumptions": [
    {
      "id": "a1",
      "assumption": "你做出的假设",
      "risk": "假设错误的风险",
      "verify": "如何验证或确认"
    }
  ],
  "missing": ["缺失的关键信息或资源"],
  "summary": "对当前需求完整度的总体判断，控制在100字以内"
}

判断 status 的规则：
- 如果存在任何 must 级别问题，或关键假设无法验证，status 必须为 "needs_clarification"。
- 只有当目标、输入、输出、环境、验收都明确，且没有高风险假设时，status 才能为 "complete"。

只输出 JSON，不要解释。"""


def _load_domain_prompt(domain: str, domain_file: str = "") -> str:
    """加载领域特定 prompt 附加内容。

    支持两种方式：
    1. --domain <name>：从 agent-toolkit/skills/clarify/<name>-prompt.md 加载
    2. --domain-file <path>：从任意项目路径加载（推荐项目隔离）
    """
    path = ""
    if domain_file:
        path = domain_file
    elif domain:
        path = str(SKILLS_DIR / f"{domain}-prompt.md")

    if path and Path(path).exists():
        return "\n\n【领域特定审查要点】\n" + Path(path).read_text(encoding="utf-8")
    return ""


def _build_user_payload(payload: dict, domain: str = "", domain_file: str = "") -> str:
    """把 intake/refine 输出统一转成用户提示。"""
    parts = []

    # 如果已有结构化需求，优先使用
    if payload.get("goal"):
        parts.append("【核心目标】\n" + payload.get("goal", ""))
        if payload.get("inputs"):
            parts.append("【已有输入】\n" + "\n".join(f"- {x}" for x in payload.get("inputs", [])))
        if payload.get("outputs"):
            parts.append("【期望输出】\n" + "\n".join(f"- {x}" for x in payload.get("outputs", [])))
        if payload.get("constraints"):
            parts.append("【约束条件】\n" + "\n".join(f"- {x}" for x in payload.get("constraints", [])))
        if payload.get("acceptance"):
            parts.append("【验收标准】\n" + "\n".join(f"- {x}" for x in payload.get("acceptance", [])))
    else:
        # 否则直接用 cleaned 文本
        parts.append("【用户原话】\n" + payload.get("cleaned", ""))

    if payload.get("context"):
        parts.append("【背景上下文】\n" + payload.get("context", ""))

    if payload.get("attachments"):
        parts.append("【附件/路径】\n" + "\n".join(f"- {a.get('type')}: {a.get('value')}" for a in payload.get("attachments", [])))

    user_text = "\n\n".join(parts)
    user_text += _load_domain_prompt(domain, domain_file)
    return user_text


# ---------- 4. 交互式问答 ----------

def _interactive_ask(questions: list[dict]) -> dict[str, str]:
    """命令行逐条提问，返回 {qid: answer}。"""
    answers: dict[str, str] = {}
    if not questions:
        return answers

    print("\n=== 需求澄清 ===", file=sys.stderr)
    print("请回答以下问题，直接按回车表示跳过/不确定。\n", file=sys.stderr)

    for q in questions:
        qid = q.get("id", "")
        question = q.get("question", "")
        why = q.get("why", "")
        priority = q.get("priority", "must")
        prefix = "[必须]" if priority == "must" else "[建议]" if priority == "should" else "[可选]"

        print(f"{prefix} {question}", file=sys.stderr)
        if why:
            print(f"    原因：{why}", file=sys.stderr)

        try:
            answer = input("你的回答: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        answers[qid] = answer
        print(file=sys.stderr)

    return answers


# ---------- 5. 主流程 ----------

def _fill_defaults(data: dict) -> dict:
    return {
        "status": data.get("status", "needs_clarification"),
        "questions": data.get("questions", []),
        "assumptions": data.get("assumptions", []),
        "missing": data.get("missing", []),
        "summary": data.get("summary", ""),
        "answers": data.get("answers", {}),
    }


def clarify(
    payload: dict,
    domain: str = "",
    domain_file: str = "",
    interactive: bool = False,
) -> dict[str, Any]:
    """对需求进行澄清审查。"""
    user_prompt = _build_user_payload(payload, domain, domain_file)
    if not user_prompt.strip():
        return _fill_defaults({
            "status": "needs_clarification",
            "summary": "输入为空，无法澄清。",
            "missing": ["用户输入或已清洗的需求文本"],
        })

    system_prompt = BASE_SYSTEM_PROMPT + _load_domain_prompt(domain, domain_file)
    raw_output = _call_llm(system_prompt, user_prompt)
    data = _extract_json(raw_output)
    result = _fill_defaults(data)
    result["domain"] = domain or (Path(domain_file).stem if domain_file else "")
    result["domain_file"] = domain_file

    if interactive:
        result["answers"] = _interactive_ask(result.get("questions", []))

    return result


def to_markdown(result: dict) -> str:
    """把 clarify 结果转成可人工填写的 Markdown 清单。"""
    lines = ["# 需求澄清清单", ""]
    lines.append(f"**整体判断**: {result.get('status', 'unknown')} — {result.get('summary', '')}")
    lines.append("")

    if result.get("missing"):
        lines.append("## 缺失信息")
        for item in result["missing"]:
            lines.append(f"- [ ] {item}")
        lines.append("")

    if result.get("questions"):
        lines.append("## 待澄清问题")
        for q in result["questions"]:
            priority = q.get("priority", "must")
            lines.append(f"### {q.get('id', '')} [{priority}] {q.get('question', '')}")
            if q.get("why"):
                lines.append(f"- **原因**: {q.get('why')}")
            lines.append(f"- **分类**: {q.get('category', '')}")
            lines.append(f"- **回答**: _______________")
            lines.append("")

    if result.get("assumptions"):
        lines.append("## 当前假设与风险")
        for a in result["assumptions"]:
            lines.append(f"### {a.get('id', '')} {a.get('assumption', '')}")
            if a.get("risk"):
                lines.append(f"- **风险**: {a.get('risk')}")
            if a.get("verify"):
                lines.append(f"- **验证方式**: {a.get('verify')}")
            lines.append("")

    return "\n".join(lines)


# ---------- 6. 入口 ----------

def main() -> None:
    # Windows/Git Bash 强制 UTF-8
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    interactive = "--interactive" in args
    markdown = "--markdown" in args
    domain = ""
    domain_file = ""

    if "--domain" in args:
        idx = args.index("--domain")
        if idx + 1 < len(args):
            domain = args[idx + 1]

    if "--domain-file" in args:
        idx = args.index("--domain-file")
        if idx + 1 < len(args):
            domain_file = args[idx + 1]

    # 移除已识别的参数，剩下的按原有逻辑处理
    cleaned_args = [a for a in args if a not in ("--interactive", "--markdown")]
    for flag in ("--domain", "--domain-file"):
        if flag in cleaned_args:
            idx = cleaned_args.index(flag)
            cleaned_args = cleaned_args[:idx] + cleaned_args[idx + 2:]

    # 读取输入
    if len(cleaned_args) > 1 and cleaned_args[0] == "--file":
        payload = json.loads(Path(cleaned_args[1]).read_text(encoding="utf-8"))
    elif len(cleaned_args) > 1 and cleaned_args[0] == "--json":
        payload = json.loads(cleaned_args[1])
    elif len(cleaned_args) == 1 and not cleaned_args[0].startswith("-"):
        # 兼容直接传字符串，但 Windows 下不推荐
        payload = {"cleaned": cleaned_args[0]}
    else:
        payload = json.loads(sys.stdin.read())

    result = clarify(payload, domain=domain, domain_file=domain_file, interactive=interactive)

    if markdown:
        print(to_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
