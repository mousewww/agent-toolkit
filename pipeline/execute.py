#!/usr/bin/env python3
"""
execute.py — 按 dispatch 的任务列表，由弱模型执行任务并自检。

用法：
    python execute.py --file dispatch_output.json
    python execute.py --file dispatch_output.json --apply
    cat dispatch_output.json | python execute.py --apply --max-retries 2

输出 JSON：
    {
        "results": [
            {
                "task_id": "task_1",
                "status": "success | failed | skipped",
                "output": "执行结果摘要",
                "file": "修改的文件路径",
                "self_check_report": "自检说明",
                "passed": true,
                "issues": [],
                "retries": 0
            }
        ]
    }

执行规则：
- 按 depends_on 拓扑排序，依赖先执行。
- 每个任务在一个隔离上下文中运行：只操作自己的 file，失败可重放。
- 加 --apply 才会实际写文件；写之前自动备份到 <file>.execute.bak。
- 自检不通过则返工，最多返工 max-retries 次（默认 2 次）。
- 返工后仍失败，抛出异常，由上层强模型诊断。

环境变量：
    EXECUTE_API_KEY / OPENAI_API_KEY
    EXECUTE_MODEL（覆盖所有任务的模型，调试用）
    HEADROOM_PROXY_URL
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import get_base_url, get_api_key


# ---------- 0. 配置 ----------

EXECUTE_MODEL = os.environ.get("EXECUTE_MODEL", "")
EXECUTE_API_KEY = get_api_key("EXECUTE_API_KEY")
EXECUTE_BASE_URL = get_base_url("deepseek")


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str, model: str, max_tokens: int = 2048) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not EXECUTE_API_KEY:
        raise RuntimeError("未设置 EXECUTE_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=EXECUTE_API_KEY, base_url=EXECUTE_BASE_URL)
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
    """从 LLM 输出里提取 JSON。"""
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


# ---------- 2. 拓扑排序与分层 ----------

def _topo_levels(tasks: list) -> list:
    """
    按 depends_on 做拓扑分层。
    返回 [[level0_tasks], [level1_tasks], ...]，同层任务无互相依赖，可并行。
    """
    task_map = {t["id"]: t for t in tasks}
    in_degree = {t["id"]: 0 for t in tasks}
    edges = {t["id"]: [] for t in tasks}

    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep in task_map:
                edges[dep].append(t["id"])
                in_degree[t["id"]] += 1
            else:
                # 依赖的任务不存在，视为失败
                raise ValueError(f"任务 {t['id']} 依赖 {dep}，但 {dep} 不存在")

    levels = []
    remaining = dict(in_degree)

    while remaining:
        # 找出当前入度为 0 的任务
        current_level_ids = [tid for tid, deg in remaining.items() if deg == 0]
        if not current_level_ids:
            # 有环
            raise ValueError("任务依赖存在循环，无法拓扑排序")

        levels.append([task_map[tid] for tid in current_level_ids])

        # 移除当前层任务，更新入度
        for tid in current_level_ids:
            del remaining[tid]
            for next_id in edges[tid]:
                if next_id in remaining:
                    remaining[next_id] -= 1

    return levels


# ---------- 3. 文件隔离与备份 ----------

def _backup_file(file_path: str) -> str:
    """备份文件，返回备份路径。"""
    src = Path(file_path)
    if not src.exists():
        return ""
    bak = Path(f"{file_path}.execute.bak")
    shutil.copy2(src, bak)
    return str(bak)


def _restore_file(file_path: str, bak_path: str) -> None:
    """从备份恢复文件。"""
    if not bak_path:
        return
    shutil.copy2(bak_path, file_path)


def _cleanup_backup(bak_path: str) -> None:
    """清理备份文件。"""
    if bak_path and Path(bak_path).exists():
        Path(bak_path).unlink()


def _apply_output_to_file(file_path: str, output: str) -> None:
    """把模型输出中的代码块写到目标文件。"""
    if not file_path:
        return

    # 优先提取 ```python ... ``` 或 ``` ... ``` 代码块
    m = re.search(r'```(?:\w+)?\s*\n([\s\S]*?)\n```', output)
    if m:
        content = m.group(1)
    else:
        # 没有代码块，把整个输出写进去（可能是文本文件）
        content = output

    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(content, encoding="utf-8")


# ---------- 4. 任务执行 ----------

EXECUTE_PROMPT = """你是一名执行代理。请根据任务提示词完成工作，然后按自检清单检查自己的输出。

要求：
1. 认真完成任务，给出具体可执行的结果（代码、命令、分析等）。
2. 如果任务涉及修改文件，请在输出中用 ```python ... ``` 或 ``` ... ``` 代码块包含完整的新文件内容。
3. 按自检清单逐项检查，诚实说明是否通过。
4. 只输出 JSON，不要 Markdown 代码块外的任何内容。

输出 JSON 格式：
{
  "output": "任务执行结果摘要，或完整文件内容",
  "self_check_report": "自检说明：通过/未通过，原因",
  "passed": true,
  "issues": ["如果未通过，列出问题"]
}"""


def _resolve_model(task_model: str) -> str:
    """决定实际使用的模型。非当前 provider 支持的模型 fallback 到 deepseek-v4-flash。"""
    if EXECUTE_MODEL:
        return EXECUTE_MODEL
    if not task_model:
        return "deepseek-v4-flash"
    task_model_lower = task_model.lower()
    # local 模型、unknown、空字符串 fallback
    if task_model_lower.startswith("local-") or task_model_lower in ("unknown", ""):
        return "deepseek-v4-flash"
    # 当前默认 provider（deepseek）只支持这两个模型
    supported = ("deepseek-v4-flash", "deepseek-v4-pro")
    if task_model_lower not in supported:
        return "deepseek-v4-flash"
    return task_model


def _execute_once(task: dict, previous_outputs: dict) -> dict:
    """执行一次任务，返回解析后的结果。"""
    task_id = task.get("id", "unknown")
    prompt = task.get("prompt", "")
    expected = task.get("expected_output", "")
    self_check = task.get("self_check", [])
    model = _resolve_model(task.get("model", ""))

    if not prompt:
        return {
            "output": "任务 prompt 为空",
            "self_check_report": "未执行",
            "passed": False,
            "issues": ["prompt 为空"],
        }

    context = ""
    if previous_outputs:
        context = "前置任务结果：\n" + json.dumps(previous_outputs, ensure_ascii=False, indent=2) + "\n\n"

    user_prompt = f"""{context}任务提示词：
{prompt}

期望输出：
{expected}

自检清单：
{chr(10).join(f'- {item}' for item in self_check)}

请输出 JSON。"""

    raw_output = _call_llm(EXECUTE_PROMPT, user_prompt, model)
    return _extract_json(raw_output)


def _execute_task(task: dict, previous_outputs: dict, apply: bool, max_retries: int) -> dict:
    """执行单个任务，支持返工。"""
    task_id = task.get("id", "unknown")
    file_path = task.get("file", "")
    retries = 0
    bak_path = ""

    # 如果要修改现有文件但该文件不存在，提前报错
    if apply and file_path and Path(file_path).exists() and not Path(file_path).is_file():
        raise RuntimeError(f"任务 {task_id} 的目标路径 {file_path} 不是文件")

    if apply and file_path and Path(file_path).exists():
        bak_path = _backup_file(file_path)

    local_outputs = dict(previous_outputs)

    while retries <= max_retries:
        try:
            data = _execute_once(task, local_outputs)
            output = data.get("output", "")
            passed = bool(data.get("passed", False))
            issues = data.get("issues", []) if isinstance(data.get("issues"), list) else []

            if apply and file_path and passed:
                _apply_output_to_file(file_path, output)

            if passed:
                _cleanup_backup(bak_path)
                return {
                    "task_id": task_id,
                    "status": "success",
                    "output": output,
                    "file": file_path,
                    "self_check_report": data.get("self_check_report", ""),
                    "passed": True,
                    "issues": [],
                    "retries": retries,
                }

            # 未通过，需要返工
            retries += 1
            if retries <= max_retries:
                if apply and file_path:
                    _restore_file(file_path, bak_path)
                # 把失败原因注入上下文，提醒模型
                local_outputs[f"{task_id}_retry_{retries}"] = {
                    "failed_output": output,
                    "issues": issues,
                }
                continue
            else:
                # 超过最大返工次数，抛异常让上层强模型诊断
                _restore_file(file_path, bak_path)
                _cleanup_backup(bak_path)
                raise RuntimeError(
                    f"任务 {task_id} 执行失败，已返工 {max_retries} 次仍未通过。"
                    f"自检报告：{data.get('self_check_report', '')}"
                    f"问题：{issues}"
                )

        except Exception as e:
            if apply and file_path:
                _restore_file(file_path, bak_path)
            _cleanup_backup(bak_path)
            raise RuntimeError(f"任务 {task_id} 执行异常：{e}") from e

    # 不会到达这里
    _cleanup_backup(bak_path)
    return {
        "task_id": task_id,
        "status": "failed",
        "output": "",
        "file": file_path,
        "self_check_report": "未知错误",
        "passed": False,
        "issues": ["未知错误"],
        "retries": retries,
    }


def _run_level_serial(level_tasks: list, previous_outputs: dict, apply: bool, max_retries: int) -> list:
    """串行执行一层任务。"""
    results = []
    for task in level_tasks:
        result = _execute_task(task, previous_outputs, apply, max_retries)
        results.append(result)
        previous_outputs[task.get("id", "unknown")] = {
            "output": result["output"],
            "passed": result["passed"],
        }
    return results


def _run_level_parallel(level_tasks: list, previous_outputs: dict, apply: bool, max_retries: int) -> list:
    """并行执行一层任务。"""
    from concurrent.futures import ThreadPoolExecutor

    def run_one(task):
        return _execute_task(task, previous_outputs, apply, max_retries)

    results = []
    with ThreadPoolExecutor(max_workers=min(len(level_tasks), 4)) as executor:
        futures = {executor.submit(run_one, task): task for task in level_tasks}
        for future in futures:
            result = future.result()
            results.append(result)
            previous_outputs[result["task_id"]] = {
                "output": result["output"],
                "passed": result["passed"],
            }
    return results


def execute(tasks: list, apply: bool = False, max_retries: int = 2, parallel: bool = False) -> dict:
    """执行任务列表，返回结果。"""
    levels = _topo_levels(tasks)
    previous_outputs = {}
    all_results = []

    for level_idx, level_tasks in enumerate(levels):
        if parallel and len(level_tasks) > 1:
            results = _run_level_parallel(level_tasks, previous_outputs, apply, max_retries)
        else:
            results = _run_level_serial(level_tasks, previous_outputs, apply, max_retries)
        all_results.extend(results)

    return {"results": all_results}


# ---------- 5. 入口 ----------

def main() -> None:
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="执行任务列表")
    parser.add_argument("--file", help="dispatch 输出文件")
    parser.add_argument("--json", help="dispatch 输出 JSON 字符串")
    parser.add_argument("--apply", action="store_true", help="实际写文件（默认只生成结果）")
    parser.add_argument("--max-retries", type=int, default=2, help="最大返工次数（默认 2）")
    parser.add_argument("--parallel", action="store_true", help="同层级任务并行执行（默认串行）")
    args = parser.parse_args()

    if args.file:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    elif args.json:
        payload = json.loads(args.json)
    else:
        payload = json.loads(sys.stdin.read())

    tasks = payload.get("tasks", [])
    result = execute(tasks, apply=args.apply, max_retries=args.max_retries, parallel=args.parallel)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
