"""Knowledge record queries and cached entry counts."""

from __future__ import annotations

import inspect
import threading
import time
from contextlib import contextmanager

from typing import TYPE_CHECKING, Any, Callable, Iterator
from uuid import UUID

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

_catalog_lock = threading.Lock()
_catalog_client: QdrantClient | None = None
_catalog_collection: str | None = None
_catalog_expires = 0.0
_catalog_counts: dict[str, int] = {}


def pagination_arguments(method: Callable[..., Any], limit: int) -> dict[str, int]:
    """Support Mem0 releases using either limit or top_k."""
    parameter = "top_k" if "top_k" in inspect.signature(method).parameters else "limit"
    return {parameter: limit}


def format_knowledge_entry(row: Any, *, include_text: bool = False) -> dict[str, str]:
    """Format a browse row while preserving list and search text fallbacks."""
    if not isinstance(row, dict):
        return {"id": "", "memory": str(row)}
    content = row.get("memory") or row.get("content")
    if include_text:
        content = content or row.get("text")
    return {"id": str(row.get("id") or ""), "memory": str(content or "")}


def list_store_entries(get_all: Callable[..., Any], knowledge_id: str, limit: int) -> list[dict[str, str]]:
    raw = get_all(
        filters={"user_id": knowledge_id}, **pagination_arguments(get_all, limit),
    )
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    return [format_knowledge_entry(row) for row in rows]


def scroll_knowledge_records(
    client: QdrantClient, collection_name: str, *,
    knowledge_id: str | None = None, cursor: str | None = None,
    limit: int = 100, catalog: bool = False,
) -> tuple[list[Any], Any]:
    """Read one page without loading vectors; catalog reads project only IDs."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    offset: str | int | None = None
    if cursor:
        try:
            offset = int(cursor) if cursor.isdecimal() else str(UUID(cursor))
        except ValueError as exc:
            raise ValueError("invalid knowledge entries cursor") from exc
    condition = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=knowledge_id))]) if knowledge_id else None
    return client.scroll(
        collection_name=collection_name,
        scroll_filter=condition,
        offset=offset,
        limit=limit,
        with_payload=["user_id"] if catalog else True,
        with_vectors=False,
    )


def collect_knowledge_entry_ids(
    client: QdrantClient, collection_name: str, knowledge_id: str,
) -> list[str]:
    """Collect every entry before deletion so scrolling sees a stable collection."""
    knowledge_id = str(knowledge_id or "").strip()
    if not knowledge_id:
        raise ValueError("knowledge id is required")
    ids: set[str] = set()
    cursor = None
    while True:
        records, next_cursor = scroll_knowledge_records(
            client, collection_name,
            knowledge_id=knowledge_id, cursor=cursor, limit=256,
        )
        ids.update(str(record.id) for record in records)
        if next_cursor is None:
            return sorted(ids)
        cursor = str(next_cursor)


def invalidate_knowledge_catalog() -> None:
    global _catalog_expires
    with _catalog_lock:
        _catalog_expires = 0.0


@contextmanager
def invalidate_catalog_after_write() -> Iterator[None]:
    """Expire counts after writes, including failures after partial changes."""
    try:
        yield
    finally:
        invalidate_knowledge_catalog()


def _build_knowledge_catalog(client: QdrantClient, collection_name: str) -> dict[str, int]:
    """Count entries across all vector-store pages."""
    counts: dict[str, int] = {}
    cursor = None
    while True:
        records, next_cursor = scroll_knowledge_records(client, collection_name, cursor=cursor, limit=256, catalog=True)
        for record in records:
            payload = record.payload or {}
            knowledge_id = str(payload.get("user_id") or "").strip()
            if not knowledge_id:
                continue
            counts[knowledge_id] = counts.get(knowledge_id, 0) + 1
        if next_cursor is None:
            return counts
        cursor = str(next_cursor)


def get_knowledge_entry_counts(
    client: QdrantClient, collection_name: str, *, refresh: bool = False,
) -> dict[str, int]:
    """Reuse a catalog for 30 seconds; publish only fully completed scans.

    The caller holds the knowledge operation lock before acquiring the catalog
    lock, matching the lock order used by writes and invalidation.
    """
    global _catalog_client, _catalog_collection, _catalog_expires, _catalog_counts
    with _catalog_lock:
        if (
            refresh or client is not _catalog_client
            or collection_name != _catalog_collection
            or time.monotonic() >= _catalog_expires
        ):
            counts = _build_knowledge_catalog(client, collection_name)
            _catalog_client, _catalog_collection, _catalog_counts = client, collection_name, counts
            _catalog_expires = time.monotonic() + 30.0
        return dict(_catalog_counts)
