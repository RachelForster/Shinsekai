"""Compatibility re-export facade for concrete LLM adapters.

Concrete implementations now live under :mod:`ai.llm.adapters`.
"""

from __future__ import annotations

from ai.llm.adapters import (
    CLAUDE_CHAT_PARAMS,
    OPENAI_COMPAT_CHAT_PARAMS,
    SUPPORTED_CHAT_PARAMS,
    ClaudeAdapter,
    DeepSeekAdapter,
    OpenAIAdapter,
    filter_adapter_chat_params as _filter_adapter_chat_params,
    filter_supported_chat_params,
    raise_if_http_client_error as _raise_if_http_client_error,
)

__all__ = [
    "CLAUDE_CHAT_PARAMS",
    "ClaudeAdapter",
    "DeepSeekAdapter",
    "OPENAI_COMPAT_CHAT_PARAMS",
    "OpenAIAdapter",
    "SUPPORTED_CHAT_PARAMS",
    "_filter_adapter_chat_params",
    "_raise_if_http_client_error",
    "filter_supported_chat_params",
]
