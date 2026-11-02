from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any

from sdk.llm_response import ChatResponse, OpenAIResponseCodec, ResponseCodec, ResponseDelta


class LLMAdapter(ABC):
    """Abstract LLM service adapter.

    Base defaults and conventions:
        - ``__init__(**kwargs)``: Unknown keys are ignored; only ``user_template=""`` is set here.
        - ``get_config_schema()``: Returns ``{}`` by default, so no adapter-specific fields appear on the
          API settings tab. Subclasses may return ``field_name -> meta`` dicts; common meta keys:
          ``type`` (str|int|float|bool), ``label``, ``default``, ``secret``, ``min``, ``max``,
          ``step``, ``choices`` (list of strings; rendered as a combo box).
        - ``chat(..., stream=False, **kwargs)``: Sampling and similar runtime args come from
          ``LLMManager.generation_config`` and each implementation's filtering (e.g. OpenAI-compatible
          stacks often accept ``temperature``, ``presence_penalty``, ``frequency_penalty``, ``max_tokens``;
          see ``filter_supported_chat_params`` in ``ai.llm.llm_adapter``). Global defaults (temperature,
          penalties, etc.) live in ``ApiConfig``, not in this schema.
    """

    supported_chat_params: frozenset[str] = frozenset()

    def __init__(self, **kwargs) -> None:
        self.user_template = ""
        self._current_stream: object | None = None
        self._current_response: object | None = None
        self.provider = str(kwargs.get("llm_provider") or "")

    @property
    def supports_native_vision(self) -> bool:
        """Whether this adapter accepts provider-neutral local image blocks.

        Unknown adapters are text-only by default. Adapters must explicitly
        opt in before image payloads are sent to their provider.
        """
        return False

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

    @classmethod
    def get_unsupported_chat_params(cls, provider: str) -> set[str]:
        """Return params that this adapter class cannot send to *provider*.

        Called before every ``chat()`` in OpenAIAdapter. Subclasses may override to
        strip provider-incompatible keys (e.g. Gemini does not accept penalty params
        over the OpenAI-compatible bridge)."""
        return set()

    @classmethod
    def get_supported_chat_params(cls) -> set[str]:
        """Parameter policy inherited and extendable by adapter subclasses."""
        return set(cls.supported_chat_params)

    @property
    def response_codec(self) -> ResponseCodec:
        """Existing plugins default to OpenAI-compatible response objects."""
        return OpenAIResponseCodec()

    @property
    def supports_streaming_tools(self) -> bool:
        return True

    def assistant_message_metadata(self, reasoning: str) -> dict[str, Any]:
        """Metadata a provider requires when replaying an assistant turn."""
        return {}

    def decode_response(self, response: Any) -> ChatResponse:
        return self.response_codec.decode(response)

    def iter_response_stream(
        self, response: Any, *, cancelled: Callable[[], bool],
    ) -> Iterator[ResponseDelta]:
        return self.response_codec.iter_stream(response, cancelled=cancelled)

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        pass

    def set_user_template(self, template: str) -> None:
        self.user_template = template

    def cancel(self) -> None:
        """Cancel the currently active request (best-effort).

        Default implementation clears stored stream/response references.
        Subclasses should override to close the underlying HTTP connection
        when possible.
        """
        self._current_stream = None
        self._current_response = None
