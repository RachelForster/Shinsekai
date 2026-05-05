from __future__ import annotations

from abc import ABC, abstractmethod


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
          see ``filter_supported_chat_params`` in ``llm.llm_adapter``). Global defaults (temperature,
          penalties, etc.) live in ``ApiConfig``, not in this schema.
    """

    def __init__(self, **kwargs) -> None:
        self.user_template = ""

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

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        pass

    def set_user_template(self, template: str) -> None:
        self.user_template = template
