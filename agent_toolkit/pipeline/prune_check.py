#!/usr/bin/env python3
"""
prune_check.py — 扫描项目冗余候选，只做检查，不删除。

用法：
    python prune_check.py --path ./agent-toolkit
    python prune_check.py --path ./agent-toolkit --output report.json

输出 JSON：
    {
      "path": "扫描路径",
      "candidates": [
        {"type": "empty_dir", "path": "...", "reason": "..."},
        {"type": "cache_dir", "path": "...", "reason": "..."},
        {"type": "duplicate_name", "path": "...", "reason": "..."},
        {"type": "debug_file", "path": "...", "reason": "..."}
      ]
    }

规则：只标候选，不自动删。最终是否精简由人工/Agent 判断。
"""

import io
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".git"}
# 注意：不含 "test"，避免误伤正规测试文件
DEBUG_PATTERNS = {"debug", "tmp", "temp", "old", "backup", "bak", "draft", "demo"}
IGNORED_DUP_NAMES = {"SKILL.md", "README.md", "__init__.py", ".gitignore", "LICENSE", "pyproject.toml", "setup.py"}


def scan(path: Path) -> list[dict]:
    """扫描冗余候选。"""
    candidates = []
    name_map = defaultdict(list)

    if not path.exists():
        return [{"type": "error", "path": str(path), "reason": "路径不存在"}]

    for root, dirs, files in os.walk(path):
        root_path = Path(root)

        # 先记录缓存/VCS 目录本身，再跳过内部扫描
        for d in dirs:
            if d in CACHE_DIRS or d == ".git":
                candidates.append({
                    "type": "cache_dir",
                    "path": str(root_path / d),
                    "reason": "缓存/依赖目录，可清理后重建",
                })

        # 跳过缓存/VCS 目录的内部扫描
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS and d != ".git"]

        # 空目录
        if not dirs and not files:
            candidates.append({
                "type": "empty_dir",
                "path": str(root_path),
                "reason": "空目录，无子文件",
            })
            continue

        for f in files:
            fp = root_path / f
            name_lower = f.lower()
            stem = fp.stem.lower()
            suffix = fp.suffix.lower()

            # 收集同名文件（不同目录）
            name_map[f].append(str(fp))

            # 调试/临时文件
            if any(p in stem for p in DEBUG_PATTERNS):
                candidates.append({
                    "type": "debug_file",
                    "path": str(fp),
                    "reason": f"文件名含调试/临时标记: {stem}",
                })

            # 空文件
            if fp.stat().st_size == 0:
                candidates.append({
                    "type": "empty_file",
                    "path": str(fp),
                    "reason": "空文件",
                })

    # 重复 basenames（仅不同路径，排除常见结构性文件）
    for name, paths in name_map.items():
        if name in IGNORED_DUP_NAMES:
            continue
        if len(paths) > 1:
            for p in paths:
                candidates.append({
                    "type": "duplicate_name",
                    "path": p,
                    "reason": f"同名文件出现在 {len(paths)} 处: {paths}",
                })

    return candidates


def main() -> None:
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    target = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--path" else Path(".")
    output = Path(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[3] == "--output" else None

    candidates = scan(target)
    report = {"path": str(target.resolve()), "candidates": candidates}

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.write_text(text, encoding="utf-8")
        print(f"报告已保存: {output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
