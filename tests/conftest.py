"""pytest 共享配置与 fixtures。"""

import pytest


@pytest.fixture(autouse=True)
def no_api_calls(monkeypatch):
    """默认禁用所有真实 API 调用，防止测试意外消耗 key 或触发网络请求。"""
    # 清空所有可能触发 LLM 的环境变量
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ROUTER_API_KEY", "")
    monkeypatch.setenv("REFINE_API_KEY", "")
    monkeypatch.setenv("CLARIFY_API_KEY", "")
    monkeypatch.setenv("PROMPT_API_KEY", "")
    monkeypatch.setenv("DISPATCH_API_KEY", "")
    monkeypatch.setenv("EXECUTE_API_KEY", "")
    monkeypatch.setenv("INTAKE_MODEL", "")
    monkeypatch.setenv("ROUTER_MODEL", "")
    monkeypatch.setenv("HEADROOM_PROXY_URL", "")
