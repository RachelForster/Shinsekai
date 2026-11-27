"""LLM adapter registry and provider creation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.adapters import AdapterRegistration, AdapterRegistry, discover_builtin_adapters
from sdk.adapters.llm import LLMAdapter


def _normalize_llm_key(key: str) -> str:
    return str(key or "").strip()


def configure_builtin_llm_adapters(
    registry: AdapterRegistry[LLMAdapter] | None = None,
) -> None:
    """Auto-discover and register all built-in LLM adapters from ``ai.llm.adapters``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    discover_builtin_adapters("ai.llm.adapters", target)


def create_llm_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[LLMAdapter]:
    """Create a standalone LLM adapter registry (useful for isolated tests/DI)."""
    registry: AdapterRegistry[LLMAdapter] = AdapterRegistry(
        "LLM",
        key_normalizer=_normalize_llm_key,
        builtin_registrar=configure_builtin_llm_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[LLMAdapter] = AdapterRegistry(
    "LLM",
    key_normalizer=_normalize_llm_key,
    builtin_registrar=configure_builtin_llm_adapters,
)


def get_llm_adapter_registry() -> AdapterRegistry[LLMAdapter]:
    """Return the process-wide default LLM adapter registry."""
    return _DEFAULT_REGISTRY


def register_llm_adapter(
    provider: str,
    adapter_cls: type[LLMAdapter] | Callable[..., LLMAdapter],
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[LLMAdapter] | None = None,
) -> AdapterRegistration[LLMAdapter]:
    """Register an LLM adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider,
        adapter_cls,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def configure_registered_llm_adapters(
    adapters: Mapping[str, Any],
    *,
    allow_override_builtin: bool = True,
    registry: AdapterRegistry[LLMAdapter] | None = None,
) -> None:
    """Atomically replace plugin-provided LLM adapters (called by plugin host)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    target.configure_plugins(adapters, allow_override_builtin=allow_override_builtin)


def list_llm_adapters(
    registry: AdapterRegistry[LLMAdapter] | None = None,
) -> tuple[AdapterRegistration[LLMAdapter], ...]:
    """Return all registered LLM entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()


def create_llm_adapter(
    llm_provider: str,
    *,
    registry: AdapterRegistry[LLMAdapter] | None = None,
    **kwargs: Any,
) -> LLMAdapter:
    """Construct an ``LLMAdapter`` instance for ``llm_provider``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    call_kwargs = dict(kwargs)
    call_kwargs.setdefault("llm_provider", llm_provider)
    return target.create(llm_provider, **call_kwargs)
