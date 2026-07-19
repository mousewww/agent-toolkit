#!/usr/bin/env python3
"""
core/config.py — 统一管理 API 配置。

设计原则：
- 一个文件管所有 API 端点配置。
- 支持 Headroom 代理压缩：设置 HEADROOM_PROXY_URL 即可让所有 LLM 调用走压缩。
- 保留各节点独立设置 BASE_URL 的能力，方便调试。

优先级：
1. HEADROOM_PROXY_URL（全局代理，最省事）
2. <PROVIDER>_BASE_URL（按 provider 覆盖）
3. OPENAI_BASE_URL / OPENAI_API_BASE（通用覆盖）
4. 默认官方 URL
"""

import os


DEFAULT_APIS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "packy": "https://api-slb.packyapi.com/v1",
}


def get_base_url(provider: str = "deepseek") -> str:
    """获取指定 provider 的 API base URL。"""
    # 1. Headroom 全局代理
    headroom_url = os.environ.get("HEADROOM_PROXY_URL", "").strip()
    if headroom_url:
        return headroom_url

    # 2. Provider 专属覆盖
    provider_env = f"{provider.upper()}_BASE_URL"
    url = os.environ.get(provider_env, "").strip()
    if url:
        return url

    # 3. 通用 OpenAI 风格覆盖
    for fallback in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        url = os.environ.get(fallback, "").strip()
        if url:
            return url

    # 4. 默认值
    return DEFAULT_APIS.get(provider, "")


def get_api_key(preferred: str = "", fallback: str = "OPENAI_API_KEY") -> str:
    """获取 API key，支持指定优先变量和 fallback。"""
    if preferred:
        key = os.environ.get(preferred, "").strip()
        if key:
            return key
    return os.environ.get(fallback, "").strip()


def headroom_enabled() -> bool:
    """是否启用了 Headroom 代理。"""
    return bool(os.environ.get("HEADROOM_PROXY_URL", "").strip())
