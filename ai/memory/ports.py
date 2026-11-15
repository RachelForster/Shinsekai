"""Narrow SOLID ports and plug-and-play adapter registry for memory."""

from __future__ import annotations

import threading
from sdk.adapters.memory import (
    EmbeddingProvider,
    EmbeddingProviderContribution,
    EmbeddingProviderFactory,
    MemoryAvailabilityProbe,
    MemoryExtractorPort,
    MemoryRepository,
    MemoryRepositoryContribution,
    MemoryRepositoryFactory,
    RecallPlanner,
    RetentionPolicy,
    StaticVectorStorePort,
)

_registry_lock = threading.RLock()
_embedding_contributions: dict[str, EmbeddingProviderContribution] = {}
_repository_contributions: dict[str, MemoryRepositoryContribution] = {}


def register_embedding_provider(contribution: EmbeddingProviderContribution) -> None:
    """Register or replace an EmbeddingProvider contribution by provider key."""
    key = str(contribution.provider or "").strip().lower()
    if not key:
        raise ValueError("embedding provider name is required")
    with _registry_lock:
        _embedding_contributions[key] = contribution


def register_memory_repository(contribution: MemoryRepositoryContribution) -> None:
    """Register or replace a MemoryRepository contribution by provider key."""
    key = str(contribution.provider or "").strip().lower()
    if not key:
        raise ValueError("memory repository provider name is required")
    with _registry_lock:
        _repository_contributions[key] = contribution


def resolve_registered_embedding_provider(provider: str = "") -> EmbeddingProvider | None:
    """Resolve an explicitly named or highest-priority available EmbeddingProvider."""
    with _registry_lock:
        items = dict(_embedding_contributions)
    target = str(provider or "").strip().lower()
    if target:
        contrib = items.get(target)
        if contrib is None:
            raise KeyError(f"unknown embedding provider: {provider}")
        return contrib.factory()
    for contrib in sorted(items.values(), key=lambda item: (item.priority, item.provider)):
        try:
            if contrib.available():
                return contrib.factory()
        except Exception:
            continue
    return None


def resolve_registered_memory_repository(provider: str = "") -> MemoryRepository | None:
    """Resolve an explicitly named or highest-priority available MemoryRepository."""
    with _registry_lock:
        items = dict(_repository_contributions)
    target = str(provider or "").strip().lower()
    if target:
        contrib = items.get(target)
        if contrib is None:
            raise KeyError(f"unknown memory repository provider: {provider}")
        return contrib.factory()
    for contrib in sorted(items.values(), key=lambda item: (item.priority, item.provider)):
        try:
            if contrib.available():
                return contrib.factory()
        except Exception:
            continue
    return None


def clear_memory_adapter_registrations() -> None:
    """Reset custom registrations (primarily used by unit tests)."""
    with _registry_lock:
        _embedding_contributions.clear()
        _repository_contributions.clear()


__all__ = [
    "EmbeddingProvider",
    "EmbeddingProviderContribution",
    "EmbeddingProviderFactory",
    "MemoryAvailabilityProbe",
    "MemoryExtractorPort",
    "MemoryRepository",
    "MemoryRepositoryContribution",
    "MemoryRepositoryFactory",
    "RecallPlanner",
    "RetentionPolicy",
    "StaticVectorStorePort",
    "clear_memory_adapter_registrations",
    "register_embedding_provider",
    "register_memory_repository",
    "resolve_registered_embedding_provider",
    "resolve_registered_memory_repository",
]
