"""Generic, thread-safe registry primitives for pluggable host/AI adapters."""

from core.adapters.discovery import (
    BuiltinAdapterSpec,
    builtin_adapter,
    discover_builtin_adapters,
    get_builtin_adapter_specs,
)
from core.adapters.registry import AdapterRegistration, AdapterRegistry

__all__ = [
    "AdapterRegistration",
    "AdapterRegistry",
    "BuiltinAdapterSpec",
    "builtin_adapter",
    "discover_builtin_adapters",
    "get_builtin_adapter_specs",
]
