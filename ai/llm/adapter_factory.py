"""LLM adapter construction.

This module keeps provider selection independent from conversation management so
callers that only need to build an adapter do not pull in the chat runtime.
"""

from ai.llm.llm_adapter import (
    ClaudeAdapter,
    DeepSeekAdapter,
    LLMAdapter,
    OpenAIAdapter,
)


class LLMAdapterFactory:
    """Factory for creating supported :class:`LLMAdapter` instances."""

    _adapters = {
        "Deepseek": DeepSeekAdapter,
        "ChatGPT": OpenAIAdapter,
        "Gemini": OpenAIAdapter,
        "Claude": ClaudeAdapter,
        "豆包": OpenAIAdapter,
        "通义千问": OpenAIAdapter,
        "Ollama": OpenAIAdapter,
    }

    @staticmethod
    def create_adapter(llm_provider: str, **kwargs) -> LLMAdapter:
        adapter_class = LLMAdapterFactory._adapters.get(llm_provider)
        if not adapter_class:
            supported = list(LLMAdapterFactory._adapters.keys())
            raise ValueError(
                f"Unsupported LLM adapter: '{llm_provider}'. "
                f"Supported adapters are: {supported}"
            )

        try:
            from config.adapter_extra_kwargs import filter_kwargs_for_ctor

            adapter_kwargs = dict(kwargs)
            adapter_kwargs.setdefault("llm_provider", llm_provider)
            return adapter_class(
                **filter_kwargs_for_ctor(adapter_class, adapter_kwargs)
            )
        except TypeError:
            print(
                f"Error creating adapter '{llm_provider}'. Check the required arguments."
            )
            raise
