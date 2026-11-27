"""OpenAI-compatible LLM adapter shared by OpenAI, Gemini, Doubao, Qwen, and Ollama."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from ai.llm.adapters.common import (
    OPENAI_COMPAT_CHAT_PARAMS,
    close_active_stream,
    filter_adapter_chat_params,
    raise_if_http_client_error,
)
from ai.vision.message_content import normalize_openai_messages
from core.adapters import builtin_adapter
from sdk.adapters import LLMAdapter
from sdk.logging import get_logger

logger = get_logger(__name__)

_NATIVE_VISION_MODEL_PREFIXES: tuple[str, ...] = (
    "chatgpt-4o",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.5",
    "gpt-4-turbo",
    "gpt-5",
)


@builtin_adapter("ChatGPT", label="ChatGPT", order=20)
@builtin_adapter(
    "Gemini",
    label="Gemini",
    order=30,
    default_kwargs={
        "supports_streaming_tools": False,
        "unsupported_chat_params": frozenset({"frequency_penalty", "presence_penalty"}),
    },
)
@builtin_adapter("豆包", label="豆包", order=50)
@builtin_adapter("通义千问", label="通义千问", order=60)
@builtin_adapter("Ollama", label="Ollama", order=70)
class OpenAIAdapter(LLMAdapter):
    """Chat Completions adapter supporting configurable provider capability overrides."""

    supported_chat_params = OPENAI_COMPAT_CHAT_PARAMS
    _supports_streaming_tools_override: bool | None = None
    _unsupported_chat_params_override: frozenset[str] | None = None

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-3.5-turbo",
        *,
        supports_streaming_tools: bool | None = None,
        unsupported_chat_params: Collection[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        from openai import OpenAI

        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = model
        self._supports_streaming_tools_override = (
            None if supports_streaming_tools is None else bool(supports_streaming_tools)
        )
        self._unsupported_chat_params_override = (
            None if unsupported_chat_params is None else frozenset(unsupported_chat_params)
        )

    @property
    def supports_streaming_tools(self) -> bool:
        override = getattr(self, "_supports_streaming_tools_override", None)
        if override is not None:
            return bool(override)
        return self.provider.casefold() != "gemini"

    @property
    def supports_native_vision(self) -> bool:
        """Opt in only model families known to accept OpenAI image content."""
        model = str(self.model or "").strip().lower()
        return model.startswith(_NATIVE_VISION_MODEL_PREFIXES)

    def cancel(self) -> None:
        """Close the active OpenAI stream/response to abort an in-flight request."""
        close_active_stream(self)

    @classmethod
    def get_unsupported_chat_params(cls, provider: str) -> set[str]:
        if provider == "Gemini":
            return {"frequency_penalty", "presence_penalty"}
        return set()

    def chat(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        response_format: dict[str, Any] = {"type": "json_object"},
        **kwargs: Any,
    ) -> Any:
        """Send a chat completion request to the OpenAI-compatible provider."""
        try:
            filtered = filter_adapter_chat_params(self, kwargs)
            unsupported_override = getattr(
                self, "_unsupported_chat_params_override", None
            )
            unsupported = (
                unsupported_override
                if unsupported_override is not None
                else self.get_unsupported_chat_params(self.provider)
            )
            if unsupported:
                filtered = {
                    key: value
                    for key, value in filtered.items()
                    if key not in unsupported
                }

            use_tools = bool(filtered.get("tools"))
            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": normalize_openai_messages(
                    messages,
                    supports_native_vision=self.supports_native_vision,
                ),
                "stream": stream,
                **filtered,
            }
            # 兼容旧版 max_tokens 参数：新版 OpenAI 模型（o1/o3/o4 等）要求使用 max_completion_tokens
            if (
                "max_tokens" in create_kwargs
                and "max_completion_tokens" not in create_kwargs
            ):
                create_kwargs["max_completion_tokens"] = create_kwargs.pop("max_tokens")
            if not use_tools:
                create_kwargs["response_format"] = response_format

            response = self.client.chat.completions.create(**create_kwargs)
            if stream:
                self._current_stream = response
            else:
                self._current_response = response
            return response
        except Exception as exc:
            raise_if_http_client_error(exc)
            logger.exception(
                "OpenAI chat error [%s]: %s", type(exc).__name__, exc
            )
            return None
