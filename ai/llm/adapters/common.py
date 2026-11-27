"""Shared chat parameter filtering, error propagation, and cancellation helpers."""

from __future__ import annotations

from typing import Any

from sdk.adapters import LLMAdapter
from sdk.exception.types import http_client_error_from_exception

OPENAI_COMPAT_CHAT_PARAMS: frozenset[str] = frozenset(
    {
        "temperature",
        "presence_penalty",
        "frequency_penalty",
        "max_tokens",
        "tools",
        "tool_choice",
    }
)

CLAUDE_CHAT_PARAMS: frozenset[str] = frozenset(
    {
        "temperature",
        "max_tokens",
        "tools",
    }
)

SUPPORTED_CHAT_PARAMS: dict[str, set[str]] = {
    "DeepSeekAdapter": set(OPENAI_COMPAT_CHAT_PARAMS),
    "OpenAIAdapter": set(OPENAI_COMPAT_CHAT_PARAMS),
    "ClaudeAdapter": set(CLAUDE_CHAT_PARAMS),
}


def filter_supported_chat_params(adapter_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter raw chat kwargs using the legacy adapter-name parameter map."""
    supported = SUPPORTED_CHAT_PARAMS.get(adapter_name, set())
    return {key: value for key, value in kwargs.items() if key in supported}


def filter_adapter_chat_params(adapter: LLMAdapter, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter raw chat kwargs using ``adapter.get_supported_chat_params()``."""
    supported = adapter.get_supported_chat_params()
    return {key: value for key, value in kwargs.items() if key in supported}


def raise_if_http_client_error(exc: BaseException) -> None:
    """Re-raise transport/HTTP client exceptions so callers can handle retries or status."""
    if http_client_error_from_exception(exc):
        raise exc


def close_active_stream(adapter: LLMAdapter) -> None:
    """Best-effort close of active stream/response handles stored on an adapter."""
    stream = getattr(adapter, "_current_stream", None)
    if stream is not None:
        close_fn = getattr(stream, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass
        adapter._current_stream = None
    adapter._current_response = None
