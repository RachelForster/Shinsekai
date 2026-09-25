"""Opt-in waiting queue and speech identities; no host state or side effects.

ChatTurnService serializes these operations with its own state lock. It alone
owns batching, timers, turn completion and delivery. Entries are opaque tokens:
this policy never reads or changes their text, attachments or callbacks.
"""
from __future__ import annotations

from collections import deque
from typing import Generic, Iterable, TypeVar

T = TypeVar("T")


class ContinuousASRPolicy(Generic[T]):
    def __init__(self) -> None:
        self._deferred: deque[T] = deque()
        self._retired: set[str] = set()
        self._sources: dict[str, tuple[str | None, T]] = {}

    def invalidate(self) -> None:
        self._deferred.clear()
        self._retired.clear()
        self._sources.clear()

    def track(self, entry: T, *, identity: str | None, sources: Iterable[str]) -> None:
        """Associate source utterances with their current, host-owned batch."""
        for source in sources:
            self._sources[source] = (identity, entry)

    def retire(self, utterance_id: str) -> T | None:
        """Revoke an accepted replacement's old batch and return it to the host."""
        self._retired.add(utterance_id)
        previous = self._sources.pop(utterance_id, None)
        if previous is None:
            return None
        identity, entry = previous
        if identity:
            self._retired.add(identity)
        self._deferred = deque(item for item in self._deferred if item is not entry)
        self._sources = {
            source: pair for source, pair in self._sources.items() if pair[1] is not entry
        }
        return entry

    def is_retired(self, identity: str | None) -> bool:
        return identity in self._retired

    def begin_turn(self, identity: str | None) -> None:
        """Release source tracking once a worker consumes the batch."""
        if identity:
            self._sources = {
                source: pair for source, pair in self._sources.items() if pair[0] != identity
            }

    def defer(self, entry: T) -> None:
        self._deferred.append(entry)

    def pop(self) -> T | None:
        return self._deferred.popleft() if self._deferred else None
