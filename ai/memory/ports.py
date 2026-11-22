"""Narrow SOLID ports and plug-and-play adapter registry for memory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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

RetentionPolicyFactory = Callable[[], RetentionPolicy]
RecallPlannerFactory = Callable[[], RecallPlanner]


@dataclass(frozen=True, slots=True)
class RetentionPolicyContribution:
    """Plugin contribution registering a custom RetentionPolicy implementation."""

    provider: str
    factory: RetentionPolicyFactory
    available: MemoryAvailabilityProbe = lambda: True
    priority: int = 100


@dataclass(frozen=True, slots=True)
class RecallPlannerContribution:
    """Plugin contribution registering a custom RecallPlanner implementation."""

    provider: str
    factory: RecallPlannerFactory
    available: MemoryAvailabilityProbe = lambda: True
    priority: int = 100


_registry_lock = threading.RLock()
_embedding_contributions: dict[str, EmbeddingProviderContribution] = {}
_repository_contributions: dict[str, MemoryRepositoryContribution] = {}
_retention_contributions: dict[str, RetentionPolicyContribution] = {}
_planner_contributions: dict[str, RecallPlannerContribution] = {}


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
        _retention_contributions.clear()
        _planner_contributions.clear()


def register_retention_policy(contribution: RetentionPolicyContribution) -> None:
    """Register or replace a RetentionPolicy contribution by provider key."""
    key = str(contribution.provider or "").strip().lower()
    if not key:
        raise ValueError("retention policy provider name is required")
    with _registry_lock:
        _retention_contributions[key] = contribution


def register_recall_planner(contribution: RecallPlannerContribution) -> None:
    """Register or replace a RecallPlanner contribution by provider key."""
    key = str(contribution.provider or "").strip().lower()
    if not key:
        raise ValueError("recall planner provider name is required")
    with _registry_lock:
        _planner_contributions[key] = contribution


def resolve_registered_retention_policy(provider: str = "") -> RetentionPolicy | None:
    """Resolve an explicitly named or highest-priority available RetentionPolicy."""
    with _registry_lock:
        items = dict(_retention_contributions)
    target = str(provider or "").strip().lower()
    if target:
        contrib = items.get(target)
        if contrib is None:
            raise KeyError(f"unknown retention policy provider: {provider}")
        return contrib.factory()
    for contrib in sorted(items.values(), key=lambda item: (item.priority, item.provider)):
        try:
            if contrib.available():
                return contrib.factory()
        except Exception:
            continue
    return None


def resolve_registered_recall_planner(provider: str = "") -> RecallPlanner | None:
    """Resolve an explicitly named or highest-priority available RecallPlanner."""
    with _registry_lock:
        items = dict(_planner_contributions)
    target = str(provider or "").strip().lower()
    if target:
        contrib = items.get(target)
        if contrib is None:
            raise KeyError(f"unknown recall planner provider: {provider}")
        return contrib.factory()
    for contrib in sorted(items.values(), key=lambda item: (item.priority, item.provider)):
        try:
            if contrib.available():
                return contrib.factory()
        except Exception:
            continue
    return None


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
    "RecallPlannerContribution",
    "RecallPlannerFactory",
    "RetentionPolicy",
    "RetentionPolicyContribution",
    "RetentionPolicyFactory",
    "StaticVectorStorePort",
    "clear_memory_adapter_registrations",
    "register_embedding_provider",
    "register_memory_repository",
    "register_recall_planner",
    "register_retention_policy",
    "resolve_registered_embedding_provider",
    "resolve_registered_memory_repository",
    "resolve_registered_recall_planner",
    "resolve_registered_retention_policy",
]
