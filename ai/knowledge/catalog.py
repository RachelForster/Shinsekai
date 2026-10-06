"""Cached knowledge catalog scanning, matching, and pagination."""

from __future__ import annotations

import threading
import time
from typing import Any

from ai.knowledge.storage import scroll_knowledge_records
from ai.knowledge.bindings import get_knowledge_binding_counts

_catalog_lock = threading.Lock()
_catalog_store: Any = None
_catalog_expires = 0.0
_catalog_counts: dict[str, int] = {}


def invalidate_knowledge_catalog() -> None:
    global _catalog_expires
    with _catalog_lock:
        _catalog_expires = 0.0


def _build_knowledge_catalog(store: Any) -> dict[str, int]:
    """Count entries across all vector-store pages."""
    counts: dict[str, int] = {}
    cursor = None
    while True:
        records, next_cursor = scroll_knowledge_records(store, cursor=cursor, limit=256, catalog=True)
        for record in records:
            payload = record.payload or {}
            knowledge_id = str(payload.get("user_id") or "").strip()
            if not knowledge_id:
                continue
            counts[knowledge_id] = counts.get(knowledge_id, 0) + 1
        if next_cursor is None:
            return counts
        cursor = str(next_cursor)


def _get_cached_knowledge_catalog(
    store: Any, *, refresh: bool,
) -> dict[str, int]:
    """Reuse a catalog for 30 seconds; publish only fully completed scans.

    The caller holds the knowledge operation lock before acquiring the catalog
    lock, matching the lock order used by writes and invalidation.
    """
    global _catalog_store, _catalog_expires, _catalog_counts
    with _catalog_lock:
        if refresh or store is not _catalog_store or time.monotonic() >= _catalog_expires:
            counts = _build_knowledge_catalog(store)
            _catalog_store, _catalog_counts = store, counts
            _catalog_expires = time.monotonic() + 30.0
        return dict(_catalog_counts)


def _matching_knowledge_ids(
    query: str,
    counts: dict[str, int],
    bindings: dict[str, int],
) -> list[str]:
    """Match knowledge IDs, including binding-only knowledge."""
    term = query.strip().casefold()
    return sorted(
        (
            knowledge_id for knowledge_id in counts.keys() | bindings.keys()
            if term in knowledge_id.casefold()
        ),
        key=lambda knowledge_id: (knowledge_id.casefold(), knowledge_id),
    )


def _build_knowledge_catalog_page(
    knowledge_ids: list[str],
    counts: dict[str, int],
    bindings: dict[str, int],
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Normalize pagination and format entry and character counts."""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    selected = knowledge_ids[(page - 1) * page_size:page * page_size]
    return {
        "count": len(knowledge_ids),
        "page": page,
        "pageSize": page_size,
        "knowledge": [
            {
                "knowledge_id": knowledge_id,
                "entryCount": counts.get(knowledge_id, 0),
                "characterCount": bindings.get(knowledge_id, 0),
            }
            for knowledge_id in selected
        ],
    }



def list_knowledge_catalog(
    store: Any, query: str = "", *, page: int = 1, page_size: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    """List knowledge bases with entry and binding counts under the caller's lock."""
    counts = _get_cached_knowledge_catalog(store, refresh=refresh)
    bindings = get_knowledge_binding_counts()
    knowledge_ids = _matching_knowledge_ids(query, counts, bindings)
    return _build_knowledge_catalog_page(
        knowledge_ids, counts, bindings, page=page, page_size=page_size,
    )
