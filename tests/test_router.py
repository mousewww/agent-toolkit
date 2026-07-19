"""测试 router.py — 路由分类与回答生成。

所有 LLM 调用和联网搜索都被 mock，无需 API key。
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_toolkit.pipeline import router


class TestExtractJson:
    """JSON 解析容错。"""

    def test_pure_json(self):
        text = '{"route": "chat", "confidence": 0.9}'
        assert router._extract_json(text) == {"route": "chat", "confidence": 0.9}

    def test_json_in_code_block(self):
        text = '```json\n{"route": "search"}\n```'
        assert router._extract_json(text) == {"route": "search"}

    def test_json_in_plain_code_block(self):
        text = '```\n{"route": "programming"}\n```'
        assert router._extract_json(text) == {"route": "programming"}

    def test_json_embedded_in_text(self):
        text = '好的，结果是：\n\n{"route": "chat", "confidence": 1.0}\n\n希望对你有帮助。'
        assert router._extract_json(text) == {"route": "chat", "confidence": 1.0}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            router._extract_json("not json at all")


class TestClassify:
    """路由分类（mock LLM）。"""

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_classify_programming(self, mock_llm):
        mock_llm.return_value = '{"route": "programming", "confidence": 0.95, "reason": "涉及代码修改"}'
        result = router._classify("帮我写个排序函数")
        assert result["route"] == "programming"
        assert result["confidence"] == 0.95

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_classify_search(self, mock_llm):
        mock_llm.return_value = '{"route": "search", "confidence": 0.9, "parameters": {"search_query": "北京天气"}}'
        result = router._classify("今天北京天气怎样")
        assert result["route"] == "search"
        assert result["parameters"]["search_query"] == "北京天气"

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_classify_chat(self, mock_llm):
        mock_llm.return_value = '{"route": "chat", "confidence": 1.0}'
        result = router._classify("你好")
        assert result["route"] == "chat"

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_classify_tool(self, mock_llm):
        mock_llm.return_value = '{"route": "tool", "parameters": {"tool_name": "calendar"}}'
        result = router._classify("帮我查一下日程")
        assert result["route"] == "tool"

    def test_classify_empty_input(self):
        result = router._classify("")
        assert result["route"] == "chat"
        assert result["confidence"] == 1.0


class TestSearchDuckDuckGo:
    """DuckDuckGo 搜索。"""

    @patch("urllib.request.urlopen")
    def test_search_with_results(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "AbstractText": "Python 是一种编程语言",
            "AbstractURL": "https://python.org",
            "RelatedTopics": [
                {"Text": "Python 官网", "FirstURL": "https://python.org"}
            ]
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = router._search_duckduckgo("python")
        assert len(result) > 0
        assert any("Python" in r["text"] for r in result)

    @patch("urllib.request.urlopen")
    def test_search_empty_query(self, mock_urlopen):
        result = router._search_duckduckgo("")
        assert result == []

    @patch("urllib.request.urlopen")
    def test_search_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("timeout")
        result = router._search_duckduckgo("test")
        assert result[0]["source"] == "error"
        assert "timeout" in result[0]["text"]


class TestRoute:
    """主入口路由。"""

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_route_programming(self, mock_llm):
        mock_llm.return_value = '{"route": "programming", "confidence": 0.95}'
        result = router.route("写个快速排序")
        assert result["route"] == "programming"
        assert result["next"] == "agent-toolkit/pipeline/runner.py"

    @patch("agent_toolkit.pipeline.router._call_llm")
    @patch("agent_toolkit.pipeline.router._search_duckduckgo")
    def test_route_search(self, mock_search, mock_llm):
        mock_llm.side_effect = [
            '{"route": "search", "confidence": 0.9, "parameters": {"search_query": "天气"}}',
            "今天北京晴，25°C"
        ]
        mock_search.return_value = [{"source": "test", "text": "晴 25°C"}]

        result = router.route("北京天气")
        assert result["route"] == "search"
        assert result["response"] == "今天北京晴，25°C"
        assert result["next"] == "直接返回回答"

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_route_chat(self, mock_llm):
        mock_llm.side_effect = [
            '{"route": "chat", "confidence": 1.0}',
            "你好！有什么可以帮你的？"
        ]
        result = router.route("你好")
        assert result["route"] == "chat"
        assert result["response"] == "你好！有什么可以帮你的？"

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_route_tool(self, mock_llm):
        mock_llm.return_value = '{"route": "tool", "confidence": 0.8, "parameters": {"tool_name": "email"}}'
        result = router.route("发邮件给老板")
        assert result["route"] == "tool"
        assert "email" in result["next"]

    @patch("agent_toolkit.pipeline.router._call_llm")
    def test_route_unknown_fallback(self, mock_llm):
        mock_llm.side_effect = [
            '{"route": "unknown", "confidence": 0.3}',
            "我不太确定你的需求"
        ]
        result = router.route("blah blah")
        assert result["route"] == "chat"  # fallback
        assert result["response"] == "我不太确定你的需求"
