"""T2I adapter registry and provider creation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.adapters import AdapterRegistration, AdapterRegistry
from sdk.adapters.t2i import T2IAdapter


def _normalize_t2i_key(key: str) -> str:
    return str(key or "").strip().lower()


def _load_comfyui_adapter() -> type[T2IAdapter]:
    from ai.t2i.t2i_adapter import ComfyUIT2IAdapter

    return ComfyUIT2IAdapter


def _load_stable_diffusion_adapter() -> type[T2IAdapter]:
    from ai.t2i.t2i_adapter import StableDiffusionAdapter

    return StableDiffusionAdapter


_BUILTIN_T2I_SPECS: tuple[tuple[str, Callable[[], type[T2IAdapter]], str, int], ...] = (
    ("comfyui", _load_comfyui_adapter, "ComfyUI", 10),
    ("stable diffusion", _load_stable_diffusion_adapter, "Stable Diffusion", 20),
)


def configure_builtin_t2i_adapters(
    registry: AdapterRegistry[T2IAdapter] | None = None,
) -> None:
    """Idempotently register all built-in T2I provider adapters."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    for key, loader, label, order in _BUILTIN_T2I_SPECS:
        target.register_builtin(key, loader=loader, label=label, order=order)


def create_t2i_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[T2IAdapter]:
    """Create a standalone T2I adapter registry."""
    registry: AdapterRegistry[T2IAdapter] = AdapterRegistry(
        "T2I",
        key_normalizer=_normalize_t2i_key,
        builtin_registrar=configure_builtin_t2i_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[T2IAdapter] = AdapterRegistry(
    "T2I",
    key_normalizer=_normalize_t2i_key,
    builtin_registrar=configure_builtin_t2i_adapters,
)


def get_t2i_adapter_registry() -> AdapterRegistry[T2IAdapter]:
    """Return the process-wide default T2I adapter registry."""
    return _DEFAULT_REGISTRY


def register_t2i_adapter(
    provider: str,
    adapter_cls: type[T2IAdapter] | Callable[..., T2IAdapter],
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[T2IAdapter] | None = None,
) -> AdapterRegistration[T2IAdapter]:
    """Register a T2I adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider,
        adapter_cls,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def configure_registered_t2i_adapters(
    adapters: Mapping[str, Any],
    *,
    registry: AdapterRegistry[T2IAdapter] | None = None,
) -> None:
    """Atomically replace plugin-provided T2I adapters (called by plugin host)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    target.configure_plugins(adapters)


def list_t2i_adapters(
    registry: AdapterRegistry[T2IAdapter] | None = None,
) -> tuple[AdapterRegistration[T2IAdapter], ...]:
    """Return all registered T2I entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()


def create_t2i_adapter(
    adapter_name: str,
    *,
    registry: AdapterRegistry[T2IAdapter] | None = None,
    **kwargs: Any,
) -> T2IAdapter:
    """Construct a ``T2IAdapter`` instance for ``adapter_name``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.create(adapter_name, **kwargs)
