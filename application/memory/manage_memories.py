"""Manage memory actions and compose configured import dependencies.

Simple operations preserve the application boundary while import actions own
chunk sizing, adapter selection, progress, and cancellation composition.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable


def resolve_memory_owner_name(name: str | None, *, config_manager: Any = None) -> str:
    """Map renamed or legacy self-persona references to canonical ``__self__`` owner ID."""
    from config.schema import (
        SELF_PERSONA_ID,
        is_self_persona,
        is_self_persona_id,
        is_self_persona_name,
    )

    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    if is_self_persona_id(cleaned) or is_self_persona_name(cleaned):
        return SELF_PERSONA_ID
    if config_manager is not None:
        getter = getattr(config_manager, "get_character_by_name", None)
        char = getter(cleaned) if callable(getter) else None
        if char is not None and is_self_persona(char):
            return SELF_PERSONA_ID
    return cleaned


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
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_list

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    if session_id:
        return memory_list(owner, session_id=session_id)
    return memory_list(owner)


def search_memories(
    query: str,
    *,
    character_name: str,
    limit: int = 10,
    session_id: str = "",
    memory_mode: str = "",
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_search

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    return memory_search(
        query,
        character_name=owner,
        limit=limit,
        session_id=session_id,
        memory_mode=memory_mode,
    )


def recall_turn_memories(
    payload: dict[str, Any],
    *,
    config_manager: Any = None,
) -> dict[str, Any]:
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
    char_names = tuple(
        owner
        for owner in (
            resolve_memory_owner_name(str(x), config_manager=config_manager)
            for x in raw_chars
            if str(x).strip()
        )
        if owner
    )

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
    raw_locale = str(payload.get("locale") or "").strip() or None
    return memory_recall_turn(turn_input, locale=raw_locale)


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
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.extraction import dialogue_memory_kind
    from ai.memory.operations import memory_remember

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    resolved_player = (
        resolve_memory_owner_name(player_character, config_manager=config_manager)
        if player_character
        else ""
    )
    return memory_remember(
        content,
        character_name=owner,
        gist_text=gist_text,
        slot_key=slot_key,
        kind=dialogue_memory_kind(kind),
        topic_tags=topic_tags,
        entities=entities,
        importance=importance,
        event_at=event_at,
        memory_mode=memory_mode,
        player_character=resolved_player,
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
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_remember_and_list

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
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
    return memory_remember_and_list(content, character_name=owner, **extra)


def forget_and_list(
    memory_id: str,
    *,
    character_name: str,
    session_id: str = "",
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget_and_list

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    if session_id:
        return memory_forget_and_list(memory_id, character_name=owner, session_id=session_id)
    return memory_forget_and_list(memory_id, character_name=owner)


def pin_memory(memory_id: str, *, pinned: bool, session_id: str = "") -> dict[str, Any]:
    from ai.memory.operations import memory_set_pinned

    return memory_set_pinned(memory_id, pinned, session_id=session_id)


def pin_and_list(
    memory_id: str,
    *,
    pinned: bool,
    character_name: str,
    session_id: str = "",
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_set_pinned_and_list

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    return memory_set_pinned_and_list(
        memory_id,
        pinned,
        character_name=owner,
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
    config_manager: Any = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_awaken_and_list

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    return memory_awaken_and_list(
        memory_id,
        character_name=owner,
        session_id=session_id,
    )


def preview_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    config_manager: Any,
) -> dict[str, Any]:
    from ai.llm.template.integrations.localization import resolve_template_locale
    from ai.memory.extraction import configured_memory_chunk_tokens
    from ai.memory.imports import preview_memory_import

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    return preview_memory_import(
        paths,
        character_name=owner,
        source_root=source_root,
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        locale=resolve_template_locale(config_manager),
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
    from ai.llm.template.integrations.localization import resolve_template_locale
    from ai.memory.extraction import (
        configured_memory_chunk_tokens,
        create_configured_memory_adapter,
    )
    from ai.memory.imports import execute_memory_import

    owner = resolve_memory_owner_name(character_name, config_manager=config_manager)
    return execute_memory_import(
        paths,
        character_name=owner,
        source_root=source_root,
        llm_adapter=create_configured_memory_adapter(config_manager),
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
        locale=resolve_template_locale(config_manager),
    )
