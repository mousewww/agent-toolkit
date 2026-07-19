"""测试 runner.py — 管线端到端集成。

所有 LLM 调用都被 mock，无需 API key。
"""

from unittest.mock import patch

import pytest

from agent_toolkit.pipeline import runner


class TestRunPipeline:
    """完整管线跑通。"""

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.prompt_optimize")
    @patch("agent_toolkit.pipeline.runner.dispatch")
    @patch("agent_toolkit.pipeline.runner.execute")
    @patch("agent_toolkit.pipeline.runner.accept")
    def test_pipeline_basic(self, mock_accept, mock_execute, mock_dispatch, mock_prompt, mock_refine):
        mock_refine.return_value = {
            "goal": "实现快速排序",
            "inputs": [],
            "outputs": ["sorted array"],
            "constraints": [],
            "acceptance": ["通过测试"],
            "context": ""
        }
        mock_prompt.return_value = {"prompt": "写快速排序", "model_hint": "gpt-4"}
        mock_dispatch.return_value = {
            "tasks": [
                {
                    "id": "t1",
                    "description": "写快速排序",
                    "files": ["sort.py"],
                    "depends_on": []
                }
            ]
        }
        mock_execute.return_value = {
            "results": [{"task_id": "t1", "status": "success"}]
        }
        mock_accept.return_value = {"passed": True, "issues": []}

        result = runner.run_pipeline("帮我写个快速排序")
        assert result["intake"]["cleaned"] == "写个快速排序"
        assert result["refine"]["goal"] == "实现快速排序"
        assert result["prompt"]["prompt"] == "写快速排序"
        assert result["dispatch"]["tasks"][0]["id"] == "t1"
        assert result["execute"]["results"][0]["status"] == "success"
        assert result["accept"]["passed"] is True

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.clarify")
    @patch("agent_toolkit.pipeline.runner.to_markdown")
    def test_pipeline_with_clarify(self, mock_to_md, mock_clarify, mock_refine):
        mock_refine.return_value = {"goal": "排序"}
        mock_clarify.return_value = {
            "questions": {"q1": "用什么语言？"},
            "assumptions": ["假设用 Python"],
            "answers": {}
        }
        mock_to_md.return_value = "# 需求澄清\n\n1. 用什么语言？"

        result = runner.run_pipeline("写个排序", do_clarify=True)
        assert result["clarify"]["questions"]["q1"] == "用什么语言？"
        assert result["mode"] == "clarify_checklist"
        assert "prompt" not in result  # clarify 非交互模式不继续

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.clarify")
    @patch("agent_toolkit.pipeline.runner.to_markdown")
    def test_pipeline_clarify_interactive(self, mock_to_md, mock_clarify, mock_refine):
        mock_refine.side_effect = [
            {"goal": "排序"},
            {"goal": "排序（Python）"},
        ]
        mock_clarify.return_value = {
            "questions": {"q1": "用什么语言？"},
            "assumptions": ["假设用 Python"],
            "answers": {"q1": "Python"}
        }

        with patch("agent_toolkit.pipeline.runner.prompt_optimize") as mock_prompt, \
             patch("agent_toolkit.pipeline.runner.dispatch") as mock_dispatch, \
             patch("agent_toolkit.pipeline.runner.execute") as mock_execute, \
             patch("agent_toolkit.pipeline.runner.accept") as mock_accept:
            mock_prompt.return_value = {"prompt": "写排序"}
            mock_dispatch.return_value = {"tasks": []}
            mock_execute.return_value = {"results": []}
            mock_accept.return_value = {"passed": True}

            result = runner.run_pipeline("写个排序", do_clarify=True, interactive=True)
            assert result["refine"]["goal"] == "排序（Python）"
            assert "execute" in result

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.prompt_optimize")
    @patch("agent_toolkit.pipeline.runner.dispatch")
    @patch("agent_toolkit.pipeline.runner.execute")
    @patch("agent_toolkit.pipeline.runner.accept")
    def test_pipeline_empty_input(self, mock_accept, mock_execute, mock_dispatch, mock_prompt, mock_refine):
        mock_refine.return_value = {"goal": ""}
        mock_prompt.return_value = {"prompt": ""}
        mock_dispatch.return_value = {"tasks": []}
        mock_execute.return_value = {"results": []}
        mock_accept.return_value = {"passed": True}

        result = runner.run_pipeline("")
        assert result["intake"]["cleaned"] == ""
        assert result["refine"] is not None


class TestRunPipelineErrorHandling:
    """错误处理。"""

    @patch("agent_toolkit.pipeline.runner.refine")
    def test_refine_error_propagated(self, mock_refine):
        mock_refine.side_effect = ValueError("refine failed")

        with pytest.raises(ValueError, match="refine failed"):
            runner.run_pipeline("test")

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.prompt_optimize")
    def test_prompt_optimize_error_propagated(self, mock_prompt, mock_refine):
        mock_refine.return_value = {"goal": "test"}
        mock_prompt.side_effect = RuntimeError("prompt failed")

        with pytest.raises(RuntimeError, match="prompt failed"):
            runner.run_pipeline("test")

    @patch("agent_toolkit.pipeline.runner.refine")
    @patch("agent_toolkit.pipeline.runner.prompt_optimize")
    @patch("agent_toolkit.pipeline.runner.dispatch")
    def test_dispatch_error_propagated(self, mock_dispatch, mock_prompt, mock_refine):
        mock_refine.return_value = {"goal": "test"}
        mock_prompt.return_value = {"prompt": "test"}
        mock_dispatch.side_effect = RuntimeError("dispatch failed")

        with pytest.raises(RuntimeError, match="dispatch failed"):
            runner.run_pipeline("test")
