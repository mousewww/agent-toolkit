#!/usr/bin/env python3
"""测试多个 API 端点和模型的可用性与延迟。

用法：
    python test_apis.py <provider> <base_url> <api_key> [model]

示例：
    python test_apis.py deepseek https://api.deepseek.com/v1 $KEY deepseek-v4-flash
    python test_apis.py packy    https://www.packyapi.com/v1 $KEY gpt-5.6-luna
"""

import json
import os
import sys
import time


def test_client(name: str, base_url: str, api_key: str, model: str, n: int = 3):
    try:
        from openai import OpenAI
    except ImportError:
        print("请先安装 openai: pip install openai")
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    print(f"\n=== {name} | {base_url} | model={model} ===")

    # 1. 尝试列出模型
    try:
        start = time.time()
        models = client.models.list()
        elapsed = time.time() - start
        model_ids = [m.id for m in models.data]
        print(f"[list models] OK, {len(model_ids)} models, {elapsed*1000:.1f}ms")
        # 打印包含关键字的模型名
        hints = [m for m in model_ids if any(k in m.lower() for k in ["flash", "luna", "mini", "deepseek", "gpt-5", "v4"])]
        if hints:
            print(f"  hints: {hints[:20]}")
    except Exception as e:
        print(f"[list models] FAIL: {e}")
        model_ids = []

    # 如果模型名没提供，尝试从列表里猜一个
    if not model and model_ids:
        for guess in ["deepseek-v4-flash", "deepseek-chat", "gpt-5.6-luna", "gpt-5.4-mini", "gpt-4o-mini"]:
            if guess in model_ids:
                model = guess
                print(f"  auto-pick model: {model}")
                break
    if not model:
        print("没有可用 model，跳过 chat 测试")
        return

    # 2. 简单 intake 类任务，测 n 次延迟
    messages = [
        {"role": "system", "content": "你只整理用户输入，去除口语填充词，保留原意，不要解释。"},
        {"role": "user", "content": "嗯，就是那个，我觉得你可以帮我看一下 agent-toolkit/pipeline/intake.py 这个文件，然后然后帮我改一下，让它输出更精简一点，然后嗯最好保留原意"},
    ]

    latencies = []
    for i in range(n):
        start = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=256,
            )
            elapsed = time.time() - start
            latencies.append(elapsed)
            content = resp.choices[0].message.content
            print(f"[chat {i+1}/{n}] {elapsed*1000:.1f}ms | tokens={resp.usage.total_tokens if resp.usage else '?'} | preview={content[:60]!r}")
        except Exception as e:
            print(f"[chat {i+1}/{n}] FAIL: {e}")

    if latencies:
        avg = sum(latencies) / len(latencies)
        print(f"[summary] avg={avg*1000:.1f}ms, min={min(latencies)*1000:.1f}ms, max={max(latencies)*1000:.1f}ms")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    name, base_url, api_key = sys.argv[1], sys.argv[2], sys.argv[3]
    model = sys.argv[4] if len(sys.argv) > 4 else ""
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    test_client(name, base_url, api_key, model, n)
