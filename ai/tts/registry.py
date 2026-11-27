"""TTS adapter registry and provider creation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.adapters import AdapterRegistration, AdapterRegistry, discover_builtin_adapters
from sdk.adapters.tts import TTSAdapter


def _normalize_tts_key(key: str) -> str:
    return str(key or "").strip().lower()


def configure_builtin_tts_adapters(
    registry: AdapterRegistry[TTSAdapter] | None = None,
) -> None:
    """Auto-discover and register all built-in TTS adapters from ``ai.tts.adapters``."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    discover_builtin_adapters("ai.tts.adapters", target)


def create_tts_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[TTSAdapter]:
    """Create a standalone TTS adapter registry (useful for isolated tests/DI)."""
    registry: AdapterRegistry[TTSAdapter] = AdapterRegistry(
        "TTS",
        key_normalizer=_normalize_tts_key,
        builtin_registrar=configure_builtin_tts_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[TTSAdapter] = AdapterRegistry(
    "TTS",
    key_normalizer=_normalize_tts_key,
    builtin_registrar=configure_builtin_tts_adapters,
)


def get_tts_adapter_registry() -> AdapterRegistry[TTSAdapter]:
    """Return the process-wide default TTS adapter registry."""
    return _DEFAULT_REGISTRY


def register_tts_adapter(
    provider: str,
    adapter_cls: type[TTSAdapter] | Callable[..., TTSAdapter],
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[TTSAdapter] | None = None,
) -> AdapterRegistration[TTSAdapter]:
    """Register a TTS adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider,
        adapter_cls,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def configure_registered_tts_adapters(
    adapters: Mapping[str, Any],
    *,
    allow_override_builtin: bool = True,
    registry: AdapterRegistry[TTSAdapter] | None = None,
) -> None:
    """Atomically replace plugin-provided TTS adapters (called by plugin host)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    target.configure_plugins(adapters, allow_override_builtin=allow_override_builtin)


def list_tts_adapters(
    registry: AdapterRegistry[TTSAdapter] | None = None,
) -> tuple[AdapterRegistration[TTSAdapter], ...]:
    """Return all registered TTS entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()


def create_tts_adapter(
    adapter_name: str,
    *,
    wait_until_ready: bool = False,
    registry: AdapterRegistry[TTSAdapter] | None = None,
    **kwargs: Any,
) -> TTSAdapter:
    """Construct a ``TTSAdapter`` and optionally wait until its server is ready."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    adapter = target.create(adapter_name, **kwargs)
    if wait_until_ready:
        try:
            adapter.wait_until_ready()
        except BaseException:
            stop_server = getattr(adapter, "stop_server", None)
            if callable(stop_server):
                stop_server()
            raise
    return adapter
