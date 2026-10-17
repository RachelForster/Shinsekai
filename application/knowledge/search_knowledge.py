"""Search the service-owned knowledge store using host character bindings."""

from __future__ import annotations

from typing import Any

from application.knowledge.runtime import get_mem0
from core.knowledge.bindings import list_knowledge_ids_for_characters


def search_knowledge(query: str, *, character_names: list[str], limit: int = 5) -> dict[str, Any]:
    from ai.knowledge.operations import search_knowledge as search_store

    try:
        text = str(query or "").strip()
        names = [name for value in character_names if (name := str(value or "").strip())]
        if not text:
            return {"error": "query is required"}
        knowledge_ids = list_knowledge_ids_for_characters(names)
        if not knowledge_ids:
            return {"query": text, "knowledge_ids": [], "count": 0, "memories": []}
        return search_store(get_mem0(), text, knowledge_ids=knowledge_ids, limit=limit)
    except Exception as exc:
        return {"error": str(exc)}
