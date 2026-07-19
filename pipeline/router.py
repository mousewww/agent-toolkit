#!/usr/bin/env python3
"""
router.py — 最外层路由：拿到用户原话，判断该走哪条处理路径。

用法：
    python router.py --file input.txt
    python router.py --json '{"raw":"..."}'
    python router.py --raw "今天北京天气怎样"
    cat input.txt | python router.py

输出 JSON：
    {
        "route": "programming | search | chat | tool",
        "confidence": 0.95,
        "reason": "一句话理由",
        "response": "search/chat 类型时的直接回答（可选）",
        "next": "programming/tool 类型时建议下一步调用的脚本",
        "parameters": {}
    }

默认模型：deepseek-v4-flash。
搜索使用 DuckDuckGo Instant Answer API（免费、无需 key，但结果有限）。
"""

import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


# ---------- 0. 配置 ----------

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import get_base_url, get_api_key

ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "deepseek-v4-flash")
ROUTER_API_KEY = get_api_key("ROUTER_API_KEY")
ROUTER_BASE_URL = get_base_url("deepseek")


# ---------- 1. LLM 调用 ----------

def _call_llm(system: str, user: str, max_tokens: int = 512) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("请先安装 openai: pip install openai")

    if not ROUTER_API_KEY:
        raise RuntimeError("未设置 ROUTER_API_KEY / OPENAI_API_KEY")

    client = OpenAI(api_key=ROUTER_API_KEY, base_url=ROUTER_BASE_URL)
    resp = client.chat.completions.create(
        model=ROUTER_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
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

    # 尝试提取 { ... }
    for match in re.finditer(r'\{', text):
        start = match.start()
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"无法解析 JSON: {text[:300]!r}")


# ---------- 2. 路由分类 ----------

CLASSIFY_PROMPT = """你是一个请求分类器。请根据用户输入判断它属于哪一类，输出 JSON。

类别：
- programming：需要修改代码、创建文件、处理项目、运行脚本、读写数据库、管理仓库文件等
- search：需要查询最新信息、新闻、天气、股价、当前事件、事实验证等
- chat：闲聊、解释概念、头脑风暴、不需要联网也不需要改代码
- tool：需要调用特定工具（如发邮件、查日历、创建待办、操作钉钉等）

输出 JSON 格式：
{
  "route": "programming | search | chat | tool",
  "confidence": 0.0,
  "reason": "分类理由",
  "parameters": {
    "search_query": "如果是 search，提取的搜索关键词",
    "tool_name": "如果是 tool，可能的工具名"
  }
}

只输出 JSON，不要解释。"""


def _classify(raw: str) -> dict:
    """用 v4-flash 判断请求类型。"""
    if not raw:
        return {"route": "chat", "confidence": 1.0, "reason": "输入为空", "parameters": {}}

    raw_output = _call_llm(CLASSIFY_PROMPT, f"用户输入：{raw}", max_tokens=512)
    data = _extract_json(raw_output)
    return {
        "route": data.get("route", "chat"),
        "confidence": float(data.get("confidence", 0.5)),
        "reason": data.get("reason", ""),
        "parameters": data.get("parameters", {}) if isinstance(data.get("parameters"), dict) else {},
    }


# ---------- 3. 联网搜索 ----------

def _search_duckduckgo(query: str) -> list:
    """用 DuckDuckGo Instant Answer API 做简单搜索，返回摘要列表。"""
    if not query:
        return []

    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    })

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return [{"source": "error", "text": f"搜索失败：{e}"}]

    results = []

    # AbstractText 是 DuckDuckGo 的即时答案摘要
    abstract = data.get("AbstractText", "")
    if abstract:
        results.append({"source": data.get("AbstractURL", "DuckDuckGo"), "text": abstract})

    # RelatedTopics 是相关主题
    for topic in data.get("RelatedTopics", [])[:5]:
        if isinstance(topic, dict) and "Text" in topic:
            results.append({"source": topic.get("FirstURL", "DuckDuckGo"), "text": topic["Text"]})

    return results


def _answer_with_search(query: str, raw: str) -> str:
    """搜索后由 v4-flash 生成回答。"""
    results = _search_duckduckgo(query)

    if not results:
        # 搜索无结果时，直接让模型基于知识回答，并标注
        return _call_llm(
            "你是一个 helpful assistant。请回答用户问题。如果问题涉及时效性信息，请说明你的知识可能不是最新的。",
            raw,
            max_tokens=1024,
        )

    context = "\n\n".join(f"[{i+1}] {r['source']}\n{r['text']}" for i, r in enumerate(results[:5]))
    user_prompt = f"""用户问题：{raw}

搜索结果：
{context}

请根据搜索结果回答用户问题。如果搜索结果不足以回答，请说明。回答尽量简洁。"""

    return _call_llm(
        "你是一个 helpful assistant。请根据提供的搜索结果回答问题，标注信息来源。",
        user_prompt,
        max_tokens=1024,
    )


# ---------- 4. 回答闲聊 ----------

def _answer_chat(raw: str) -> str:
    return _call_llm(
        "你是一个 helpful assistant。请简洁、直接地回答用户。",
        raw,
        max_tokens=1024,
    )


# ---------- 5. 主入口 ----------

def route(raw: str) -> dict:
    """对用户原话进行路由，必要时直接生成回答。"""
    classification = _classify(raw)
    route_type = classification["route"]
    result = {
        "route": route_type,
        "confidence": classification["confidence"],
        "reason": classification["reason"],
        "parameters": classification["parameters"],
        "response": "",
        "next": "",
    }

    if route_type == "search":
        query = classification["parameters"].get("search_query", raw)
        result["response"] = _answer_with_search(query, raw)
        result["next"] = "直接返回回答"

    elif route_type == "chat":
        result["response"] = _answer_chat(raw)
        result["next"] = "直接返回回答"

    elif route_type == "tool":
        tool_name = classification["parameters"].get("tool_name", "unknown")
        result["next"] = f"调用工具: {tool_name}"

    elif route_type == "programming":
        result["next"] = "agent-toolkit/pipeline/runner.py"

    else:
        result["route"] = "chat"
        result["response"] = _answer_chat(raw)
        result["next"] = "直接返回回答"

    return result


def main() -> None:
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        raw = Path(sys.argv[2]).read_text(encoding="utf-8")
    elif len(sys.argv) > 2 and sys.argv[1] == "--raw":
        raw = sys.argv[2]
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        payload = json.loads(sys.argv[2])
        raw = payload.get("raw", "")
    else:
        raw = sys.stdin.read()

    result = route(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
