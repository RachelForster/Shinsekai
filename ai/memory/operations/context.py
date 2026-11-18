"""Session routing context and shared helpers for memory operations."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
import inspect
import sys
import threading
from typing import Any

_mem0_operation_lock = threading.RLock()
_SEMANTIC_DEDUPLICATION_SEARCH_LIMIT = 5


def _package() -> Any:
    """Return the top-level ``ai.memory.operations`` module for monkeypatch-friendly lookups."""
    return sys.modules["ai.memory.operations"]


@dataclass(frozen=True, slots=True)
class MemoryToolSessionContext:
    """Implicit session routing context bound during LLM tool execution."""

    session_id: str = ""
    memory_mode: str = ""
    player_character: str = ""


_active_tool_context: ContextVar[MemoryToolSessionContext] = ContextVar(
    "shinsekai_memory_tool_context",
    default=MemoryToolSessionContext(),
)
_default_tool_context_lock = threading.RLock()
_default_tool_context = MemoryToolSessionContext()


def bind_memory_tool_context(
    *,
    session_id: str = "",
    memory_mode: str = "",
    player_character: str = "",
) -> Token[MemoryToolSessionContext]:
    """Bind per-contextvar and process-default session metadata for LLM memory tools."""
    global _default_tool_context
    ctx = MemoryToolSessionContext(
        session_id=str(session_id or "").strip(),
        memory_mode=str(memory_mode or "").strip(),
        player_character=str(player_character or "").strip(),
    )
    with _default_tool_context_lock:
        _default_tool_context = ctx
    return _active_tool_context.set(ctx)


def reset_memory_tool_context(token: Token[MemoryToolSessionContext] | None = None) -> None:
    """Clear bound memory tool context."""
    global _default_tool_context
    with _default_tool_context_lock:
        _default_tool_context = MemoryToolSessionContext()
    if token is not None:
        try:
            _active_tool_context.reset(token)
            return
        except ValueError:
            pass
    _active_tool_context.set(MemoryToolSessionContext())


def update_memory_tool_context_mode(session_id: str, mode: str) -> None:
    """Update the mode shared by the chat runtime's command and model threads."""
    global _default_tool_context
    with _default_tool_context_lock:
        if _default_tool_context.session_id == session_id:
            _default_tool_context = replace(_default_tool_context, memory_mode=mode)


def current_memory_tool_context() -> MemoryToolSessionContext:
    ctx = _active_tool_context.get()
    with _default_tool_context_lock:
        default = _default_tool_context
    if ctx.session_id == default.session_id and ctx.player_character == default.player_character:
        return default
    return ctx if ctx.session_id or ctx.memory_mode or ctx.player_character else default


def _memory_request_context(session_id: str | None) -> MemoryToolSessionContext:
    # Chat tools inherit the bound session. HTTP always supplies its own scope,
    # including an empty session ID for global memory.
    if session_id is None:
        return current_memory_tool_context()
    return MemoryToolSessionContext(session_id=str(session_id).strip())


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


def _search_mem0(mem: Any, query: str, *, filters: dict[str, str], limit: int) -> Any:
    """Search across duck-typed memory stores supporting either limit or top_k."""
    parameters = inspect.signature(mem.search).parameters
    pagination = {"top_k": limit} if "top_k" in parameters else {"limit": limit}
    return mem.search(query, filters=filters, **pagination)
