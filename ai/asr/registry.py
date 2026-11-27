"""ASR adapter registry and provider creation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.adapters import AdapterRegistration, AdapterRegistry, discover_builtin_adapters
from sdk.adapters.asr import ASRAdapter


def _normalize_asr_key(key: str) -> str:
    return str(key or "").strip().lower().replace("-", "_")


def configure_builtin_asr_adapters(
    registry: AdapterRegistry[ASRAdapter] | None = None,
) -> None:
    """Auto-discover and register all built-in ASR adapters from ``ai.asr.adapters``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    discover_builtin_adapters("ai.asr.adapters", target)


def create_asr_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[ASRAdapter]:
    """Create a standalone ASR adapter registry."""
    registry: AdapterRegistry[ASRAdapter] = AdapterRegistry(
        "ASR",
        key_normalizer=_normalize_asr_key,
        builtin_registrar=configure_builtin_asr_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[ASRAdapter] = AdapterRegistry(
    "ASR",
    key_normalizer=_normalize_asr_key,
    builtin_registrar=configure_builtin_asr_adapters,
)


def get_asr_adapter_registry() -> AdapterRegistry[ASRAdapter]:
    """Return the process-wide default ASR adapter registry."""
    return _DEFAULT_REGISTRY


def register_asr_adapter(
    provider_slug: str,
    adapter_cls: type[ASRAdapter] | Callable[..., ASRAdapter],
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[ASRAdapter] | None = None,
) -> AdapterRegistration[ASRAdapter]:
    """Register an ASR adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider_slug,
        adapter_cls,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def configure_registered_asr_adapters(
    adapters: Mapping[str, Any],
    *,
    registry: AdapterRegistry[ASRAdapter] | None = None,
) -> None:
    """Atomically replace plugin-provided ASR adapters (called by plugin host)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    target.configure_plugins(adapters)


def list_asr_adapters(
    registry: AdapterRegistry[ASRAdapter] | None = None,
) -> tuple[AdapterRegistration[ASRAdapter], ...]:
    """Return all registered ASR entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()
