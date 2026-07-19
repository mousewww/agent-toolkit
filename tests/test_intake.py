"""测试 intake.py — 原话清洗规则。"""

import pytest

from agent_toolkit.pipeline.intake import (
    _extract_attachments,
    _infer_intent,
    _normalize_space,
    _remove_fillers,
    clean,
)


class TestNormalizeSpace:
    """空白规范化。"""

    def test_multiple_spaces_collapsed(self):
        assert _normalize_space("a   b     c") == "a b c"

    def test_multiple_newlines_collapsed(self):
        assert _normalize_space("a\n\n\n\nb") == "a\n\nb"

    def test_code_block_preserved(self):
        text = "前面\n```python\nx = 1\n\n\ny = 2\n```\n后面"
        result = _normalize_space(text)
        assert "```python" in result
        assert "x = 1" in result
        assert "y = 2" in result


class TestRemoveFillers:
    """去除口语填充词。"""

    def test_remove_filler_at_start(self):
        assert _remove_fillers("嗯，帮我写个函数") == "写个函数"

    def test_remove_filler_after_punctuation(self):
        # "然后" 被去除后，前面的句号和后面的逗号会残留为 "。，"
        # 这是当前规则清洗的已知行为（未做跨类型标点合并）
        result = _remove_fillers("写个函数。然后，测试一下")
        assert "写个函数" in result
        assert "然后" not in result
        assert "测试一下" in result

    def test_preserve_code_block(self):
        text = "```python\n# 嗯，这个\nx = 1\n```"
        result = _remove_fillers(text)
        assert "嗯" in result  # 代码块内保留

    def test_empty_string(self):
        assert _remove_fillers("") == ""


class TestExtractAttachments:
    """提取附件。"""

    def test_extract_code_block(self):
        text = "```python\nx = 1\n```"
        result = _extract_attachments(text)
        assert any(a["type"] == "code" and a["lang"] == "python" for a in result)

    def test_extract_url(self):
        text = "看看 https://example.com/page 这个链接"
        result = _extract_attachments(text)
        assert any(a["type"] == "url" and "example.com" in a["value"] for a in result)

    def test_extract_path(self):
        text = "修改 src/main.py 文件"
        result = _extract_attachments(text)
        assert any(a["type"] == "path" and "src/main.py" in a["value"] for a in result)

    def test_windows_path(self):
        text = "检查 C:\\Users\\test\\file.txt"
        result = _extract_attachments(text)
        assert any(a["type"] == "path" and "file.txt" in a["value"] for a in result)

    def test_no_attachments(self):
        text = "写个排序函数"
        result = _extract_attachments(text)
        assert result == []


class TestInferIntent:
    """意图推断。"""

    def test_implement_intent(self):
        assert _infer_intent("写一个快速排序") == "implement"

    def test_fix_intent(self):
        assert _infer_intent("修一下这个 bug") == "fix"

    def test_explain_intent(self):
        assert _infer_intent("解释一下递归") == "explain"

    def test_review_intent(self):
        assert _infer_intent("帮我 review 这段代码") == "review"

    def test_ask_fallback(self):
        assert _infer_intent("随便说点") == "ask"


class TestClean:
    """主流程集成。"""

    def test_empty_input(self):
        result = clean("")
        assert result["cleaned"] == ""
        assert result["attachments"] == []
        assert result["intent_hint"] == "ask"

    def test_basic_clean(self):
        raw = "嗯，帮我写一个快速排序算法，然后测试一下"
        result = clean(raw, use_llm=False)
        assert "快速排序" in result["cleaned"]
        assert "帮我" not in result["cleaned"]  # 填充词被去除
        assert result["intent_hint"] == "implement"

    def test_with_code_attachment(self):
        raw = "```python\ndef foo():\n    pass\n```\n优化这个函数"
        result = clean(raw, use_llm=False)
        assert any(a["type"] == "code" for a in result["attachments"])

    def test_with_url_attachment(self):
        raw = "参考 https://docs.python.org/3/tutorial/ 写个例子"
        result = clean(raw, use_llm=False)
        assert any(a["type"] == "url" for a in result["attachments"])

    def test_raw_preserved(self):
        raw = "原始输入文本"
        result = clean(raw, use_llm=False)
        assert result["raw"] == raw
