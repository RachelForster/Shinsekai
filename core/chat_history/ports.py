"""Dependency-inverted port registry for ConversationSessionPort backends."""

from __future__ import annotations

import threading

from sdk.adapters.session import (
    ConversationSessionPort,
    SessionStoreContribution,
)

_registry_lock = threading.Lock()
_session_store_contributions: dict[str, SessionStoreContribution] = {}


def register_session_store_contribution(contribution: SessionStoreContribution) -> None:
    """Register or replace a custom ConversationSessionPort provider contribution."""
    provider = str(contribution.provider or "").strip()
    if not provider:
        raise ValueError("SessionStoreContribution.provider is required")
    with _registry_lock:
        _session_store_contributions[provider] = contribution


def resolve_registered_session_store(session_key: str) -> ConversationSessionPort | None:
    """Instantiate the highest-priority available registered session store, if any."""
    with _registry_lock:
        items = sorted(
            _session_store_contributions.values(),
            key=lambda item: (item.priority, item.provider),
        )
    for item in items:
        if item.available():
            return item.factory(session_key)
    return None


def clear_session_store_contributions() -> None:
    """Clear all registered session store contributions (primarily for tests)."""
    with _registry_lock:
        _session_store_contributions.clear()


__all__ = [
    "ConversationSessionPort",
    "SessionStoreContribution",
    "clear_session_store_contributions",
    "register_session_store_contribution",
    "resolve_registered_session_store",
]
