#!/usr/bin/env python3
"""
runner.py — 把编程代理管线串起来跑。

用法：
    python runner.py --file input.txt
    python runner.py --file input.txt --clarify          # 输出需求澄清清单
    python runner.py --file input.txt --clarify --interactive  # 交互式澄清后继续跑
    cat input.txt | python runner.py

输出：
    - 默认：accept 后的完整结果 JSON
    - --clarify：Markdown 需求澄清清单（不进入后续节点）
    - --clarify --interactive：交互问答后，把答案合并到 context 继续跑完整管线

环境变量：
    REFINE_API_KEY / OPENAI_API_KEY
    PROMPT_API_KEY / OPENAI_API_KEY
    DISPATCH_API_KEY / OPENAI_API_KEY
    EXECUTE_API_KEY / OPENAI_API_KEY
    ACCEPTANCE_API_KEY / OPENAI_API_KEY
    CLARIFY_API_KEY / OPENAI_API_KEY
"""

import io
import json
import os
import sys
from pathlib import Path

from .intake import clean as intake_clean
from .refine import refine
from .clarify import clarify, to_markdown
from .prompt_optimizer import optimize as prompt_optimize
from .dispatch import dispatch
from .execute import execute
from .acceptance import accept


def run_pipeline(
    raw_text: str,
    context: str = "",
    do_clarify: bool = False,
    interactive: bool = False,
    domain: str = "",
    domain_file: str = "",
) -> dict:
    """跑 intake → refine → [clarify] → prompt_optimizer → dispatch → execute → accept。"""
    # 1. intake（规则化，无模型）
    intake_result = intake_clean(raw_text, context, use_llm=False)

    # 2. refine（模型）
    refine_result = refine(intake_result["cleaned"], context)

    # 3. clarify（可选）
    if do_clarify:
        clarify_payload = {
            **refine_result,
            "cleaned": intake_result["cleaned"],
            "context": context,
            "attachments": intake_result.get("attachments", []),
        }
        clarify_result = clarify(
            clarify_payload,
            domain=domain,
            domain_file=domain_file,
            interactive=interactive,
        )

        # 非交互模式只输出清单，不继续
        if not interactive:
            return {
                "intake": intake_result,
                "refine": refine_result,
                "clarify": clarify_result,
                "mode": "clarify_checklist",
            }

        # 交互模式：把答案合并到上下文，继续跑
        answers = clarify_result.get("answers", {})
        if answers:
            answer_text = "\n".join(
                f"{qid}: {ans}" for qid, ans in answers.items() if ans.strip()
            )
            context = f"{context}\n\n【用户澄清】\n{answer_text}".strip()
            # 重新 refine，让结构化需求包含澄清后的信息
            refine_result = refine(intake_result["cleaned"], context)

    # 4. prompt_optimizer（模型）
    prompt_result = prompt_optimize(refine_result)

    # 5. dispatch（任务规划）
    dispatch_result = dispatch(prompt_result)

    # 6. execute（弱模型执行 + 自检）
    execute_result = execute(dispatch_result.get("tasks", []))

    # 7. acceptance（强模型最终验收）
    accept_result = accept({
        "intake": intake_result,
        "refine": refine_result,
        "prompt": prompt_result,
        "dispatch": dispatch_result,
        "execute": execute_result,
    })

    return {
        "intake": intake_result,
        "refine": refine_result,
        "clarify": clarify_result if do_clarify else None,
        "prompt": prompt_result,
        "dispatch": dispatch_result,
        "execute": execute_result,
        "accept": accept_result,
    }


def main() -> None:
    # Windows/Git Bash 强制 UTF-8
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    do_clarify = "--clarify" in args
    interactive = "--interactive" in args

    # 解析 --domain / --domain-file
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

    # 移除已识别的参数
    cleaned_args = [a for a in args if a not in ("--clarify", "--interactive")]
    for flag in ("--domain", "--domain-file"):
        if flag in cleaned_args:
            idx = cleaned_args.index(flag)
            cleaned_args = cleaned_args[:idx] + cleaned_args[idx + 2:]

    # 读取输入
    if len(cleaned_args) > 1 and cleaned_args[0] == "--file":
        raw = Path(cleaned_args[1]).read_text(encoding="utf-8")
    elif len(cleaned_args) == 1 and not cleaned_args[0].startswith("-"):
        raw = cleaned_args[0]
    else:
        raw = sys.stdin.read()

    result = run_pipeline(
        raw,
        do_clarify=do_clarify,
        interactive=interactive,
        domain=domain,
        domain_file=domain_file,
    )

    # clarify 检查清单模式单独输出 Markdown
    if do_clarify and not interactive:
        print(to_markdown(result["clarify"]))
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
