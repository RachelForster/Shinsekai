"""SQLite-backed MemoryRepository adapter delegating to SqliteHybridStore."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    CandidateHit,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryScopeFilter,
)


class SqliteHybridMemoryRepo:
    """Adapter exposing narrow MemoryRepository semantics over SqliteHybridStore."""

    def __init__(self, store_or_path: SqliteHybridStore | str | Path = ":memory:") -> None:
        if isinstance(store_or_path, SqliteHybridStore):
            self._store = store_or_path
            self._owns_store = False
        else:
            self._store = SqliteHybridStore(store_or_path)
            self._owns_store = True

    @property
    def store(self) -> SqliteHybridStore:
        return self._store

    def close(self) -> None:
        if self._owns_store:
            self._store.close()

    def upsert(self, record: MemoryRecord) -> str:
        return self._store.upsert(record)

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._store.get(memory_id)

    def search_candidates(self, query: MemoryCandidateQuery) -> Sequence[CandidateHit]:
        return self._store.search_candidates(query)

    def expand_entities(
        self,
        entities: Sequence[str],
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 10,
    ) -> Sequence[MemoryRecord]:
        return self._store.expand_entities(entities, scope_filter, limit=limit)

    def list_by_scope(
        self,
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 200,
    ) -> Sequence[MemoryRecord]:
        return self._store.list_by_scope(scope_filter, limit=limit)

    def record_recall(self, memory_ids: Sequence[str], *, recalled_at: float) -> int:
        return self._store.record_recall(memory_ids, recalled_at=recalled_at)

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        return self._store.rollback_after_turn(session_id, turn_seq)

    def set_pinned(self, memory_id: str, pinned: bool) -> bool:
        return self._store.set_pinned(memory_id, pinned)

    def delete(self, memory_id: str) -> bool:
        return self._store.delete(memory_id)
