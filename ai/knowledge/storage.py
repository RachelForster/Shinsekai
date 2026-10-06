"""Mem0 compatibility and Qdrant record access."""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID


def _pagination(method: Any, limit: int) -> dict[str, int]:
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


def list_store_entries(store: Any, knowledge_id: str, limit: int) -> list[dict[str, str]]:
    raw = store.get_all(
        filters={"user_id": knowledge_id}, **_pagination(store.get_all, limit),
    )
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    return [format_knowledge_entry(row) for row in rows]


def search_store_entries(store: Any, query: str, knowledge_id: str, limit: int) -> list[Any]:
    result = store.search(
        query, filters={"user_id": knowledge_id}, **_pagination(store.search, limit),
    )
    if isinstance(result, dict):
        rows = result.get("results") or []
    else:
        rows = result if isinstance(result, list) else []
    return list(rows)

def scroll_knowledge_records(store: Any, *, knowledge_id: str | None = None, cursor: str | None = None,
            limit: int = 100, catalog: bool = False) -> tuple[list[Any], Any]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    offset: str | int | None = None
    if cursor:
        try:
            offset = int(cursor) if cursor.isdecimal() else str(UUID(cursor))
        except ValueError as exc:
            raise ValueError("invalid knowledge entries cursor") from exc
    vector_store = store.vector_store
    condition = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=knowledge_id))]) if knowledge_id else None
    return vector_store.client.scroll(
        collection_name=vector_store.collection_name,
        scroll_filter=condition,
        offset=offset,
        limit=limit,
        with_payload=["user_id"] if catalog else True,
        with_vectors=False,
    )
