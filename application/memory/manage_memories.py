"""Manage memory actions and compose configured import dependencies.

Simple operations preserve the application boundary while import actions own
chunk sizing, adapter selection, progress, and cancellation composition.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable


def check_mem0_status(*, start_loading: bool = True) -> dict[str, Any]:
    from ai.memory.runtime import check_mem0_status as _check_mem0_status

    return _check_mem0_status(start_loading=start_loading)


def shutdown_memory_runtime() -> None:
    from ai.memory.runtime import shutdown_memory_runtime as _shutdown_memory_runtime

    _shutdown_memory_runtime()


def wait_for_memory_ready() -> None:
    """Wait for the existing memory runtime before launching semantic media."""
    from ai.memory.runtime import get_mem0

    get_mem0()


def list_memories(
    character_name: str,
    *,
    session_id: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    from ai.memory.operations import memory_list

    extra: dict[str, Any] = {}
    if session_id:
        extra["session_id"] = session_id
    if limit is not None:
        extra["limit"] = limit
    if offset:
        extra["offset"] = offset
    return memory_list(character_name, **extra)


_DEFAULT_EXPORT_LABELS: dict[str, str] = {
    "header": "Character memories",
    "exportedAt": "Exported at",
    "total": "Entries",
    "canon": "Canon",
    "detail": "Detail",
    "createdAt": "Created at",
}


def _format_export_timestamp(value: Any) -> str:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 1e12:  # milliseconds
        ts /= 1000.0
    from datetime import datetime

    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def format_memories_text(
    character_name: str,
    memories: Sequence[dict[str, Any]],
    *,
    labels: dict[str, str] | None = None,
    now: Any = None,
) -> str:
    """Render memories as a numbered, human-readable plain-text document."""
    from datetime import datetime

    lab = {**_DEFAULT_EXPORT_LABELS, **{k: str(v) for k, v in (labels or {}).items() if v}}
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {lab['header']}: {character_name}",
        f"# {lab['exportedAt']}: {stamp}",
        f"# {lab['total']}: {len(memories)}",
        "",
    ]
    for index, memory in enumerate(memories, start=1):
        text = str(memory.get("memory") or "").strip()
        gist = str(memory.get("gist") or "").strip()
        detail = str(memory.get("detail") or "").strip() or (text if gist else "")
        headline = gist or text
        canon = bool(
            memory.get("pinned") or memory.get("clarity") == "canon" or memory.get("kind") == "canon"
        )
        lines.append(f"{index}. {'[' + lab['canon'] + '] ' if canon else ''}{headline}")
        if detail and detail != headline:
            indented = detail.replace("\r\n", "\n").replace("\n", "\n   ")
            lines.append(f"   {lab['detail']}: {indented}")
        created = _format_export_timestamp(memory.get("createdAt", memory.get("created_at")))
        if created:
            lines.append(f"   {lab['createdAt']}: {created}")
        memory_id = str(memory.get("id") or "").strip()
        if memory_id:
            lines.append(f"   ID: {memory_id}")
        lines.append("")
    return "\n".join(lines)


def export_memories_text(
    character_name: str,
    *,
    session_id: str = "",
    memory_ids: Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Collect all (or the selected) memories of a character and render them as text."""
    from ai.memory.operations import memory_list_all

    listed = (
        memory_list_all(character_name, session_id=session_id)
        if session_id
        else memory_list_all(character_name)
    )
    if not isinstance(listed, dict) or listed.get("error") or listed.get("status") == "loading":
        return listed
    memories = [row for row in listed.get("memories") or [] if isinstance(row, dict)]
    if memory_ids:
        wanted = {str(item).strip() for item in memory_ids if str(item or "").strip()}
        memories = [row for row in memories if str(row.get("id") or "") in wanted]
    agent_id = str(listed.get("agentId") or character_name)
    return {
        "agentId": agent_id,
        "count": len(memories),
        "text": format_memories_text(character_name or agent_id, memories, labels=labels),
    }


def search_memories(
    query: str,
    *,
    character_name: str,
    limit: int = 10,
    session_id: str = "",
    memory_mode: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_search

    return memory_search(
        query,
        character_name=character_name,
        limit=limit,
        session_id=session_id,
        memory_mode=memory_mode,
    )


def recall_turn_memories(payload: dict[str, Any]) -> dict[str, Any]:
    from ai.memory.operations import memory_recall_turn
    from sdk.adapters.memory import TurnRecallInput

    raw_seqs = payload.get("inWindowTurnSeqs", payload.get("in_window_turn_seqs")) or ()
    in_window_seqs = frozenset(
        int(x) for x in raw_seqs if x is not None and str(x).strip() != ""
    )
    raw_injected = (
        payload.get("recentlyInjectedIds", payload.get("recently_injected_ids")) or ()
    )
    injected_ids = frozenset(str(x).strip() for x in raw_injected if str(x).strip())
    raw_chars = (
        payload.get("activeCharacterNames", payload.get("active_character_names")) or ()
    )
    char_names = tuple(str(x).strip() for x in raw_chars if str(x).strip())

    turn_input = TurnRecallInput(
        user_text=str(payload.get("userText", payload.get("user_text", "")) or ""),
        previous_assistant_text=str(
            payload.get(
                "previousAssistantText",
                payload.get("previous_assistant_text", ""),
            )
            or ""
        ),
        active_character_names=char_names,
        session_id=str(payload.get("sessionId", payload.get("session_id", "")) or ""),
        memory_mode=str(
            payload.get("memoryMode", payload.get("memory_mode", "")) or ""
        ),
        source=str(payload.get("source") or "user"),
        now_ts=float(payload.get("nowTs", payload.get("now_ts", 0.0)) or 0.0),
        seconds_since_last_turn=float(
            payload.get(
                "secondsSinceLastTurn",
                payload.get("seconds_since_last_turn", 0.0),
            )
            or 0.0
        ),
        in_window_turn_seqs=in_window_seqs,
        recently_injected_ids=injected_ids,
    )
    return memory_recall_turn(turn_input)


def search_media_assets(payload: dict[str, Any]) -> dict[str, Any]:
    from ai.memory.media_assets import media_asset_search_response

    return media_asset_search_response(payload)


def index_media_assets(payload: dict[str, Any]) -> dict[str, Any]:
    from ai.memory.media_assets import media_asset_index_response

    return media_asset_index_response(payload)


def remember_memory(
    content: str,
    *,
    character_name: str,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "episodic",
    topic_tags: Sequence[str] = (),
    entities: Sequence[str] = (),
    importance: float = 0.5,
    event_at: float | None = None,
    memory_mode: str = "",
    player_character: str = "",
    source_session_id: str = "",
    source_turn_seq: int | None = None,
) -> dict[str, Any]:
    from ai.memory.extraction import dialogue_memory_kind
    from ai.memory.operations import memory_remember

    return memory_remember(
        content,
        character_name=character_name,
        gist_text=gist_text,
        slot_key=slot_key,
        kind=dialogue_memory_kind(kind),
        topic_tags=topic_tags,
        entities=entities,
        importance=importance,
        event_at=event_at,
        memory_mode=memory_mode,
        player_character=player_character,
        source_session_id=source_session_id,
        source_turn_seq=source_turn_seq,
    )


def rollback_memories(session_id: str, *, turn_seq: int, protected_turn_seqs: Sequence[int] = ()) -> dict[str, Any]:
    from ai.memory.operations import memory_rollback_after_turn

    return memory_rollback_after_turn(session_id, turn_seq, protected_turn_seqs=protected_turn_seqs)


def forget_memory(
    memory_id: str, *, session_id: str = "", memory_mode: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget

    return memory_forget(memory_id, session_id=session_id, memory_mode=memory_mode)


def remember_and_list(
    content: str,
    *,
    character_name: str,
    pinned: bool = False,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_remember_and_list

    extra: dict[str, Any] = {}
    if pinned:
        extra["pinned"] = True
    if gist_text:
        extra["gist_text"] = gist_text
    if slot_key:
        extra["slot_key"] = slot_key
    if kind:
        extra["kind"] = kind
    if session_id:
        extra["session_id"] = session_id
    return memory_remember_and_list(content, character_name=character_name, **extra)


def forget_and_list(
    memory_id: str,
    *,
    character_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget_and_list

    if session_id:
        return memory_forget_and_list(memory_id, character_name=character_name, session_id=session_id)
    return memory_forget_and_list(memory_id, character_name=character_name)


def forget_many_and_list(
    memory_ids: Sequence[str],
    *,
    character_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget_many_and_list

    if session_id:
        return memory_forget_many_and_list(memory_ids, character_name=character_name, session_id=session_id)
    return memory_forget_many_and_list(memory_ids, character_name=character_name)


def pin_memory(memory_id: str, *, pinned: bool, session_id: str = "") -> dict[str, Any]:
    from ai.memory.operations import memory_set_pinned

    return memory_set_pinned(memory_id, pinned, session_id=session_id)


def pin_and_list(
    memory_id: str,
    *,
    pinned: bool,
    character_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_set_pinned_and_list

    return memory_set_pinned_and_list(
        memory_id,
        pinned,
        character_name=character_name,
        session_id=session_id,
    )


def awaken_memory(memory_id: str, *, session_id: str = "") -> dict[str, Any]:
    from ai.memory.operations import memory_awaken

    return memory_awaken(memory_id, session_id=session_id)


def awaken_and_list(
    memory_id: str,
    *,
    character_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    from ai.memory.operations import memory_awaken_and_list

    return memory_awaken_and_list(
        memory_id,
        character_name=character_name,
        session_id=session_id,
    )


def preview_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    config_manager: Any,
) -> dict[str, Any]:
    from ai.memory.extraction import configured_memory_chunk_tokens
    from ai.memory.imports import preview_memory_import

    return preview_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
    )


def execute_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    config_manager: Any,
    progress_callback: Callable[[str, float, str, str | None], None],
    cancel_callback: Callable[[], None],
) -> dict[str, Any]:
    from ai.memory.extraction import (
        configured_memory_chunk_tokens,
        create_configured_memory_adapter,
    )
    from ai.memory.imports import execute_memory_import

    return execute_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        llm_adapter=create_configured_memory_adapter(config_manager),
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
