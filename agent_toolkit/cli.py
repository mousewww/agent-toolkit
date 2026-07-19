#!/usr/bin/env python3
"""
CLI 入口 — agent-toolkit / atk 命令行工具。

用法：
    agent-toolkit --help
    agent-toolkit route --raw "今天北京天气怎样"
    agent-toolkit run --file input.txt
    agent-toolkit run --file input.txt --clarify
    agent-toolkit prune --path . --output prune_report.json
"""

import argparse
import io
import json
import sys
from pathlib import Path


def _setup_encoding():
    """Windows/Git Bash 强制 UTF-8。"""
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _read_input(args) -> str:
    """从 --file、--raw 或 stdin 读取输入。"""
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.raw:
        return args.raw
    return sys.stdin.read()


def cmd_route(args):
    """路由命令：判断请求类型并直接回答 search/chat。"""
    from .pipeline.router import route

    raw = _read_input(args)
    result = route(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_run(args):
    """运行命令：跑完整七阶段管线。"""
    from .pipeline.runner import run_pipeline

    raw = _read_input(args)
    result = run_pipeline(
        raw,
        do_clarify=args.clarify,
        interactive=args.interactive,
        domain=args.domain or "",
        domain_file=args.domain_file or "",
    )

    if args.clarify and not args.interactive:
        from .pipeline.clarify import to_markdown
        print(to_markdown(result["clarify"]))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_prune(args):
    """精简检查命令：扫描冗余文件。"""
    from .pipeline.prune_check import scan

    path = Path(args.path)
    candidates = scan(path)
    result = {"path": str(path.resolve()), "candidates": candidates}

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"报告已保存: {args.output}")
    else:
        print(text)


def main():
    _setup_encoding()

    parser = argparse.ArgumentParser(
        prog="agent-toolkit",
        description="Agent Toolkit — 七阶段 Agent 管线 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # route
    route_parser = subparsers.add_parser("route", help="请求路由分类")
    route_parser.add_argument("--file", help="输入文件路径")
    route_parser.add_argument("--raw", help="直接输入文本")
    route_parser.set_defaults(func=cmd_route)

    # run
    run_parser = subparsers.add_parser("run", help="跑完整管线")
    run_parser.add_argument("--file", help="输入文件路径")
    run_parser.add_argument("--raw", help="直接输入文本")
    run_parser.add_argument("--clarify", action="store_true", help="输出需求澄清清单")
    run_parser.add_argument("--interactive", action="store_true", help="交互式澄清")
    run_parser.add_argument("--domain", help="领域模板名")
    run_parser.add_argument("--domain-file", help="领域模板文件路径")
    run_parser.set_defaults(func=cmd_run)

    # prune
    prune_parser = subparsers.add_parser("prune", help="冗余文件扫描")
    prune_parser.add_argument("--path", default=".", help="扫描路径")
    prune_parser.add_argument("--output", default="prune_report.json", help="输出报告路径")
    prune_parser.set_defaults(func=cmd_prune)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
