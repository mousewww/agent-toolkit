#!/usr/bin/env python3
"""
intake.py — 把用户原话捋顺，去除废话，保留本意。

用法：
    python intake.py "你说的原话"           # 命令行传参（Windows 中文易乱码，不推荐）
    python intake.py --file raw.txt         # 从文件读（最稳）
    python intake.py < raw.txt              # stdin（需确保 UTF-8）
    python intake.py --json '{"raw":"...","context":"..."}'

Windows Git Bash 下建议用 --file，避免命令行/stdin 编码问题。

输出 JSON：
    {
        "raw": "原始输入",
        "cleaned": "整理后的文本",
        "attachments": [...],
        "intent_hint": "implement|fix|explain|review|ask"
    }
"""

import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------- 0. 轻量配置 ----------

INTAKE_MODEL = os.environ.get("INTAKE_MODEL", "")  # 例如 "gpt-4o-mini"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


# ---------- 1. 规则清洗 ----------

FILLER_WORDS = [
    "嗯", "啊", "呃", "哦", "哎", "咦", "哈",
    "那个", "这个", "就是", "然后", "接着", "还有",
    "我觉得", "我认为", "我感觉", "我猜", "可能", "大概", "也许",
    "其实", "说实话", "老实说", "怎么说呢", "讲真的",
    "你能不能", "能不能", "麻烦你", "请帮忙", "帮我",
]

INTENT_KEYWORDS = {
    "implement": ["写", "实现", "创建", "新建", "生成", "做一个", "搭一个"],
    "fix": ["修", "改", "报错", "失败", "不对", "问题", "bug"],
    "explain": ["解释", "说明", "讲讲", "为什么", "怎么回事", "如何"],
    "review": ["看看", "检查", " review", "验收", "评估", "分析一下"],
}


def _normalize_space(text: str) -> str:
    """统一空白，但不破坏代码块。"""
    # 保留 ```...``` 内部原样
    parts = re.split(r'(```[\s\S]*?```)', text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 代码块
            result.append(part)
        else:
            part = part.replace("\t", " ")
            part = re.sub(r' +', ' ', part)
            part = re.sub(r'\n\s*\n+', '\n\n', part)
            result.append(part.strip())
    return '\n\n'.join(p for p in result if p).strip()


def _remove_fillers(text: str) -> str:
    """按规则去除口语填充词（中文填充词常直接接后续内容，所以只要求前面是边界）。
    多轮迭代，因为去掉一个词可能让另一个词暴露出来。"""
    # 保护代码块
    parts = re.split(r'(```[\s\S]*?```)', text)
    result = []
    boundary = r'\s，。！？、；：\"\'（）'
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
            continue
        # 多轮清洗，直到稳定
        for _ in range(10):  # 上限 10 轮，防止意外死循环
            new_part = part
            for word in FILLER_WORDS:
                # 只要填充词位于句首或标点后，就删除，不管后面跟什么
                pattern = rf'(^|[{boundary}]){re.escape(word)}'
                new_part = re.sub(pattern, r'\1', new_part)
            # 清理残留的多余空格和标点
            new_part = re.sub(r' +', ' ', new_part)
            new_part = re.sub(r'，\s*，+', '，', new_part)
            new_part = re.sub(r'。\s*。+', '。', new_part)
            new_part = re.sub(r'^[，。！？、；：\s]+', '', new_part)
            new_part = re.sub(r'[，。！？、；：\s]+$', '', new_part)
            if new_part == part:
                break
            part = new_part
        result.append(part.strip())
    return '\n\n'.join(p for p in result if p).strip()


def _extract_attachments(text: str) -> list[dict[str, str]]:
    """提取路径、URL、代码块。"""
    attachments: list[dict[str, str]] = []

    # 代码块
    for m in re.finditer(r'```(\w*)\n([\s\S]*?)```', text):
        attachments.append({"type": "code", "lang": m.group(1), "value": m.group(2).strip()})

    # URL（贪婪到空白或中文标点/右括号为止，允许路径中的点）
    urls = []
    for m in re.finditer(r'https?://[^\s\)\]\，]+', text):
        value = m.group(0).rstrip("。，！？、；：")
        urls.append(value)
        attachments.append({"type": "url", "value": value})

    # 把已识别的 URL 先从文本中遮住，避免被当成路径
    text_for_paths = text
    for url in urls:
        text_for_paths = text_for_paths.replace(url, "")

    # Windows / Unix 路径（贪婪匹配到空白或中文标点为止）
    path_pattern = re.compile(
        r'(?:[A-Za-z]:[\\/]|\.{0,2}[\\/])?[^\s\n\，\。：；"\'（）()<>«»`]*[\\/][^\s\n\，\。：；"\'（）()<>«»`]*'
    )
    for m in path_pattern.finditer(text_for_paths):
        value = m.group(0).strip("\"'()<>")
        # 过滤掉明显不是路径的（无分隔符、无扩展名）
        has_sep = "/" in value or "\\" in value
        has_dot = "." in value
        if has_sep and (has_dot or value.count("/") + value.count("\\") >= 2):
            if not any(a["value"] == value for a in attachments):
                attachments.append({"type": "path", "value": value})

    return attachments


def _infer_intent(text: str) -> str:
    """简单关键词判断意图，没把握就标 ask。"""
    text_lower = text.lower()
    scores = {k: 0 for k in INTENT_KEYWORDS}
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower or kw in text:
                scores[intent] += 1
    if any(scores.values()):
        return max(scores, key=scores.get)
    return "ask"


# ---------- 2. LLM 语义清洗（可选） ----------

def _llm_clean(text: str, context: str = "") -> str:
    """调用轻量模型做语义级捋顺。失败则回退到原文。"""
    if not INTAKE_MODEL or not OPENAI_API_KEY:
        return text

    try:
        import openai
    except ImportError:
        return text

    ctx = f"\n当前上下文：{context}" if context else ""
    prompt = (
        "请把下面这段话整理通顺。要求："
        "1. 删除口语填充词和冗余表达；"
        "2. 保留所有事实、数字、路径、名称；"
        "3. 不要补充任何原文没有的信息；"
        "4. 只输出整理后的文本，不要解释。"
        f"{ctx}\n\n原文：{text}\n\n整理后："
    )

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        resp = client.chat.completions.create(
            model=INTAKE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        return resp.choices[0].message.content.strip() or text
    except Exception:
        return text


# ---------- 3. 主流程 ----------

def clean(raw: str, context: str = "", use_llm: bool = True) -> dict[str, Any]:
    if not raw:
        return {
            "raw": raw,
            "cleaned": "",
            "attachments": [],
            "intent_hint": "ask",
        }

    # 先规则清洗
    text = _normalize_space(raw)
    text = _remove_fillers(text)
    attachments = _extract_attachments(raw)  # 从原文提取更完整

    # 可选 LLM 语义级整理
    if use_llm and INTAKE_MODEL:
        text = _llm_clean(text, context)
        text = _normalize_space(text)  # LLM 输出再规范一下

    intent = _infer_intent(text)

    return {
        "raw": raw,
        "cleaned": text,
        "attachments": attachments,
        "intent_hint": intent,
    }


def main() -> None:
    # Windows/Git Bash 下强制 UTF-8，避免 stdin/stdout 编码问题
    if sys.stdin.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # 读取输入
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        raw = Path(sys.argv[2]).read_text(encoding="utf-8")
        context = ""
    elif len(sys.argv) > 1 and sys.argv[1] == "--json":
        payload = json.loads(sys.argv[2])
        raw = payload.get("raw", "")
        context = payload.get("context", "")
    elif len(sys.argv) > 1:
        raw = sys.argv[1]
        context = ""
    else:
        raw = sys.stdin.read()
        context = ""

    result = clean(raw, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
