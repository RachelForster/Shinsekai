"""Vision adapter registry and provider registration helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ai.vision.vision_adapter import VisionAdapter
from core.adapters import AdapterRegistration, AdapterRegistry, discover_builtin_adapters

VisionAdapterFactory = Callable[..., VisionAdapter]


def _normalize_vision_key(key: str) -> str:
    return str(key or "").strip().lower()


def configure_builtin_vision_adapters(
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> None:
    """Auto-discover and register all built-in vision adapters from ``ai.vision.adapters``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    discover_builtin_adapters("ai.vision.adapters", target)


def create_vision_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[VisionAdapter]:
    """Create a standalone Vision adapter registry."""
    registry: AdapterRegistry[VisionAdapter] = AdapterRegistry(
        "Vision",
        key_normalizer=_normalize_vision_key,
        builtin_registrar=configure_builtin_vision_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[VisionAdapter] = AdapterRegistry(
    "Vision",
    key_normalizer=_normalize_vision_key,
    builtin_registrar=configure_builtin_vision_adapters,
)


def get_vision_adapter_registry() -> AdapterRegistry[VisionAdapter]:
    """Return the process-wide default Vision adapter registry."""
    return _DEFAULT_REGISTRY


def register_vision_adapter(
    provider: str,
    factory: VisionAdapterFactory,
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> AdapterRegistration[VisionAdapter]:
    """Register a vision adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider,
        factory,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def list_vision_adapters(
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> tuple[AdapterRegistration[VisionAdapter], ...]:
    """Return all registered Vision entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()
