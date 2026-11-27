"""DeepSeek LLM adapter with thinking-mode configuration and parameter rules."""

from __future__ import annotations

from typing import Any

from ai.llm.adapters.common import (
    OPENAI_COMPAT_CHAT_PARAMS,
    close_active_stream,
    filter_adapter_chat_params,
    raise_if_http_client_error,
)
from ai.vision.message_content import normalize_openai_messages
from sdk.adapters import LLMAdapter
from sdk.logging import get_logger

logger = get_logger(__name__)

_THINKING_BANNED_PARAMS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
    }
)


class DeepSeekAdapter(LLMAdapter):
    """DeepSeek OpenAI 兼容接口；思考模式见 https://api-docs.deepseek.com/guides/thinking_mode"""

    supported_chat_params = OPENAI_COMPAT_CHAT_PARAMS

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-chat",
        *,
        thinking_enabled: bool = False,
        reasoning_effort: str = "high",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url
        self.model = model
        self.thinking_enabled = bool(thinking_enabled)
        normalized_effort = str(reasoning_effort or "high").strip().lower()
        self.reasoning_effort = (
            normalized_effort if normalized_effort in ("high", "max") else "high"
        )

    def cancel(self) -> None:
        """Close the active DeepSeek stream/response to abort an in-flight request."""
        close_active_stream(self)

    @property
    def supports_native_vision(self) -> bool:
        return False

    def assistant_message_metadata(self, reasoning: str) -> dict[str, Any]:
        if self.thinking_enabled and reasoning.strip():
            return {"reasoning_content": reasoning}
        return {}

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "thinking_enabled": {
                "type": "bool",
                "label": "思考模式",
                "default": False,
            },
            "reasoning_effort": {
                "type": "str",
                "label": "思考强度 (reasoning_effort)",
                "default": "high",
                "choices": ["high", "max"],
            },
        }

    def chat(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        response_format: dict[str, Any] = {"type": "json_object"},
        **kwargs: Any,
    ) -> Any:
        """Send a chat completion request to DeepSeek."""
        try:
            raw_kwargs = dict(kwargs)
            raw_kwargs.pop("reasoning_effort", None)
            raw_kwargs.pop("thinking_enabled", None)
            filtered = filter_adapter_chat_params(self, raw_kwargs)

            # 思考模式下 DeepSeek 不支持 temperature / top_p / presence_penalty / frequency_penalty
            if self.thinking_enabled:
                filtered = {
                    key: value
                    for key, value in filtered.items()
                    if key not in _THINKING_BANNED_PARAMS
                }

            # DeepSeek：设置了 reasoning_effort 时 thinking.type 不能为 disabled（见 API 错误提示）。
            extra_body: dict[str, Any] = {
                "thinking": {
                    "type": "enabled" if self.thinking_enabled else "disabled",
                },
            }

            # 与 OpenAI 一致：启用 tools 时不要传 response_format=json_object，否则易抑制 tool_calls。
            use_tools = bool(filtered.get("tools"))
            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": normalize_openai_messages(
                    messages,
                    supports_native_vision=self.supports_native_vision,
                ),
                "stream": stream,
                "extra_body": extra_body,
                **filtered,
            }
            if not use_tools:
                create_kwargs["response_format"] = response_format
            if self.thinking_enabled:
                create_kwargs["reasoning_effort"] = self.reasoning_effort

            response = self.client.chat.completions.create(**create_kwargs)
            if stream:
                self._current_stream = response
            else:
                self._current_response = response
            return response
        except Exception as exc:
            raise_if_http_client_error(exc)
            logger.error("DeepSeek chat error: %s", exc)
            return None
