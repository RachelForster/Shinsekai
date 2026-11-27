"""Generic, thread-safe registry primitives for pluggable host/AI adapters."""

from core.adapters.registry import AdapterRegistration, AdapterRegistry

__all__ = [
    "AdapterRegistration",
    "AdapterRegistry",
]
