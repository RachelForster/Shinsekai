"""LLM tool wrappers for long-term memory.

The memory implementation lives under :mod:`ai.memory`; this module stays a
thin LLM-facing wrapper.
"""

from __future__ import annotations

from typing import Any

from ai.memory.config import build_mem0_config as _build_mem0_config
from ai.memory.config import is_embedding_model_cached as _is_embedding_model_cached
from ai.memory.operations import memory_forget, memory_remember, memory_search
from ai.memory.runtime import check_mem0_status
from ai.memory.runtime import get_mem0 as _get_mem0
from sdk.tool_registry import tool

__all__ = [
    "_build_mem0_config",
    "_get_mem0",
    "_is_embedding_model_cached",
    "check_mem0_status",
    "memory_forget",
    "memory_remember",
    "memory_search",
]


@tool(
    name="memory_search",
    group="memory",
    description=(
        "Search YOUR long-term memory (including older or dormant memories when queried directly). "
        "character_name: YOUR OWN full name from dialog (the character who is speaking). "
        "When you are playing a character, use that character's name. "
        "query: Chinese, Japanese, or English keywords or time hints (e.g. '昨天 约定', '京都 红叶'). "
        "Call BEFORE using cross-session info. "
        "NOTE: first call may return status:'loading'. "
        "If you get status:'loading', follow the message instruction — do NOT retry this tool or any memory_* tool."
    ),
)
def _tool_memory_search(
    query: str,
    character_name: str = "user",
    limit: int = 10,
) -> dict[str, Any]:
    return memory_search(query, character_name=character_name, limit=limit)


@tool(
    name="memory_remember",
    group="memory",
    description=(
        "Save a durable fact or promise to YOUR memory. "
        "character_name: YOUR OWN full name from dialog (the character who is speaking). "
        "When you are playing 狛枝凪斗, use '狛枝凪斗', NOT 'user'. "
        "content: the concrete fact in Chinese, Japanese, or English. "
        "Only use character_name='user' for public facts about the human user, not about yourself. "
        "slot_key: optional conflict-update key (e.g. 'profile:favorite_drink') when updating a changeable preference. "
        "kind: optional 'episodic' (default), 'profile', or 'promise'. "
        "NOTE: first call may return status:'loading'. If so, follow the message — do NOT retry any memory_* tool."
    ),
)
def _tool_memory_remember(
    content: str,
    character_name: str = "user",
    slot_key: str = "",
    kind: str = "episodic",
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if slot_key:
        extra["slot_key"] = slot_key
    if kind and kind != "episodic":
        extra["kind"] = kind
    return memory_remember(content, character_name=character_name, **extra)


@tool(
    name="memory_forget",
    group="memory",
    description=(
        "Delete a memory entry. memory_id comes from a memory_search result's id field. "
        "NOTE: first call may return status:'loading'. If so, follow the message — do NOT retry any memory_* tool."
    ),
)
def _tool_memory_forget(memory_id: str) -> dict[str, Any]:
    return memory_forget(memory_id)
