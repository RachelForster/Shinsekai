"""Built-in provider registration and adapter construction."""

from ai.llm.llm_adapter import ClaudeAdapter, DeepSeekAdapter, OpenAIAdapter
from sdk.adapters.llm import LLMAdapter


class LLMAdapterFactory:
    """Factory for creating different LLMAdapter instances."""
    _adapters = {
        "Deepseek": DeepSeekAdapter,
        "ChatGPT": OpenAIAdapter,
        "Gemini":  OpenAIAdapter,
        "Claude": ClaudeAdapter,
        "豆包": OpenAIAdapter,
        "通义千问": OpenAIAdapter,
        "Ollama": OpenAIAdapter
    }

    @staticmethod
    def create_adapter(llm_provider: str, **kwargs) -> LLMAdapter:
        """Creates and returns an LLMAdapter instance based on the given name."""
        adapter_class = LLMAdapterFactory._adapters.get(llm_provider)

        if not adapter_class:
            raise ValueError(f"Unsupported LLM adapter: '{llm_provider}'. Supported adapters are: {list(LLMAdapterFactory._adapters.keys())}")

        try:
            from config.adapter_extra_kwargs import filter_kwargs_for_ctor

            kwargs.setdefault("llm_provider", llm_provider)
            return adapter_class(**filter_kwargs_for_ctor(adapter_class, kwargs))
        except TypeError as e:
            print(f"Error creating adapter '{llm_provider}'. Check the required arguments.")
            raise e
