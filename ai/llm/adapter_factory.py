"""Legacy compatibility facade delegating to :mod:`ai.llm.registry`."""

from __future__ import annotations

from typing import Any

from ai.llm.registry import create_llm_adapter, get_llm_adapter_registry
from sdk.adapters.llm import LLMAdapter


class LLMAdapterFactory:
    """Compatibility wrapper backed by the process-wide LLM ``AdapterRegistry``."""

    _adapters = get_llm_adapter_registry().as_mutable_mapping()

    @staticmethod
    def create_adapter(llm_provider: str, **kwargs: Any) -> LLMAdapter:
        """Create and return an ``LLMAdapter`` instance for ``llm_provider``."""
        return create_llm_adapter(llm_provider, **kwargs)
