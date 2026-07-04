"""User-facing memory operations."""

from __future__ import annotations

import logging
from typing import Any

from ai.memory.runtime import ensure_mem0, get_mem0

logger = logging.getLogger(__name__)


def _resolve_agent_id(character_name: str | None) -> str:
    name = (character_name or "").strip()
    return name if name else "user"


def _memory_row(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        return {
            "id": str(row.get("id") or ""),
            "memory": str(row.get("memory") or row.get("content") or ""),
        }
    return {"id": "", "memory": str(row)}


def memory_list(character_name: str | None = None, *, limit: int = 200) -> dict[str, Any]:
    agent_id = _resolve_agent_id(character_name)
    mem = get_mem0()
    raw = mem.get_all(filters={"user_id": agent_id}, limit=limit)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = [_memory_row(row) for row in rows]
    return {"agentId": agent_id, "count": len(memories), "memories": memories}


def memory_search(
    query: str,
    character_name: str | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "query 不能为空"}
    mem = ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        results = mem.search(q, filters={"user_id": agent_id}, limit=limit)
        if isinstance(results, dict) and "results" in results:
            mems = results["results"]
        elif isinstance(results, list):
            mems = results
        else:
            mems = []
        return {
            "agent_id": agent_id,
            "query": q,
            "count": len(mems),
            "memories": mems,
        }
    except Exception as e:
        logger.exception("memory_search 失败")
        return {"error": str(e)}


def memory_remember(
    content: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "content 不能为空"}
    mem = ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        mem.add(text, user_id=agent_id, infer=False)
        return {"ok": True, "agent_id": agent_id, "content": text}
    except Exception as e:
        logger.exception("memory_remember 失败")
        return {"error": str(e)}


def memory_remember_and_list(
    content: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "memory content is required"}
    result = memory_remember(text, character_name=character_name)
    if isinstance(result, dict) and result.get("error"):
        return result
    return memory_list(character_name)


def memory_forget(memory_id: str) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    mem = ensure_mem0()
    try:
        mem.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as e:
        logger.exception("memory_forget 失败")
        return {"error": str(e)}


def memory_forget_and_list(
    memory_id: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    result = memory_forget(mid)
    if isinstance(result, dict) and result.get("error"):
        return result
    return memory_list(character_name)
