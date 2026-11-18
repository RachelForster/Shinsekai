"""Write-side memory mutations: remember, forget, pin/unpin, and awaken."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import logging
import time
from typing import Any

from ai.memory.deduplication import find_duplicate_memory, semantic_deduplication_threshold
from ai.memory.engine import HybridMemoryEngine
from ai.memory.operations.context import (
    _memory_request_context,
    _package,
    _resolve_agent_id,
    _search_mem0,
)
from ai.memory.orchestrator import is_roleplay_player_persona
from core.chat_history.sqlite_session_store import borrow_session_store_by_id
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    MemoryDraft,
)
from sdk.adapters.session import MEMORY_MODE_SHARED, normalize_memory_mode

logger = logging.getLogger(__name__)


def memory_remember(
    content: str,
    character_name: str | None = None,
    *,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "episodic",
    topic_tags: Sequence[str] = (),
    entities: Sequence[str] = (),
    importance: float = 0.5,
    pinned: bool = False,
    event_at: float | None = None,
    memory_mode: str = "",
    player_character: str = "",
    source_session_id: str | None = None,
    source_turn_seq: int | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "content 不能为空"}

    ops = _package()
    ctx = _memory_request_context(source_session_id)
    clean_gist = str(gist_text or "").strip()
    clean_slot = str(slot_key or "").strip()
    clean_kind = str(kind or "episodic").strip() or "episodic"
    clean_topics = [str(t).strip() for t in topic_tags if str(t).strip()]
    clean_entities = [str(e).strip() for e in entities if str(e).strip()]
    clean_imp = float(max(0.0, min(1.0, float(importance))))
    clean_event = None if event_at is None else float(event_at)
    clean_session = ctx.session_id
    clean_mode = str(memory_mode or ctx.memory_mode).strip()
    clean_persona = str(player_character or ctx.player_character).strip()
    clean_seq = None if source_turn_seq is None else int(source_turn_seq)
    agent_id = _resolve_agent_id(character_name)

    payload: dict[str, Any] = {
        "content": text,
        "characterName": agent_id,
    }
    if clean_gist:
        payload["gistText"] = clean_gist
    if clean_slot:
        payload["slotKey"] = clean_slot
    if clean_kind != "episodic":
        payload["kind"] = clean_kind
    if clean_topics:
        payload["topicTags"] = clean_topics
    if clean_entities:
        payload["entities"] = clean_entities
    if clean_imp != 0.5:
        payload["importance"] = clean_imp
    if pinned:
        payload["pinned"] = True
    if clean_event is not None:
        payload["eventAt"] = clean_event
    if clean_mode:
        payload["memoryMode"] = clean_mode
    if clean_persona:
        payload["playerCharacter"] = clean_persona
    if clean_session:
        payload["sourceSessionId"] = clean_session
    if clean_seq is not None:
        payload["sourceTurnSeq"] = clean_seq

    service_result = ops._memory_service_request("remember", payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            with ops._mem0_operation_lock, borrow_session_store_by_id(
                clean_session,
                create_if_dir_exists=True,
            ) as sess_store:
                save_repo = getattr(sess_store, "save_memory_repo", None) if sess_store is not None else None
                resolved_mode = (
                    normalize_memory_mode(clean_mode)
                    if clean_mode
                    else (
                        sess_store.get_memory_mode()
                        if sess_store is not None
                        else MEMORY_MODE_SHARED
                    )
                )
                if save_repo is None and (
                    resolved_mode != MEMORY_MODE_SHARED
                    or is_roleplay_player_persona(clean_persona)
                    or (clean_session and not clean_mode)
                ):
                    return {"error": "save-scoped memory store unavailable"}

                is_self = agent_id.casefold() in {"", "user", "__self__", "自设"}
                effective_kind = (
                    "canon"
                    if (pinned and not is_self and clean_kind == "episodic")
                    else clean_kind
                )
                draft_scope = (
                    SCOPE_SELF_PUBLIC
                    if is_self
                    else (
                        SCOPE_CHAR_CANON
                        if (effective_kind == "canon" or pinned)
                        else SCOPE_CHAR_CROSS_SAVE
                    )
                )
                draft = MemoryDraft(
                    owner_id="__self__" if is_self else agent_id,
                    detail_text=text,
                    gist_text=clean_gist or text,
                    scope=draft_scope,
                    slot_key=clean_slot,
                    kind=effective_kind,
                    topic_tags=tuple(clean_topics),
                    entities=tuple(clean_entities),
                    importance=clean_imp,
                    pinned=bool(pinned),
                    event_at=clean_event,
                    source_session_id=clean_session,
                    source_turn_seq=clean_seq,
                )
                report = mem.orchestrator.ingest_drafts(
                    (draft,),
                    memory_mode=resolved_mode,
                    save_repo=save_repo,
                    player_character=clean_persona,
                )
                if report.skipped_duplicates > 0 and not report.added_ids:
                    return {
                        "ok": True,
                        "duplicate": True,
                        "agent_id": agent_id,
                        "scope": draft_scope,
                        "pinned": bool(pinned),
                        "content": text,
                    }
                out: dict[str, Any] = {
                    "ok": True,
                    "duplicate": False,
                    "agent_id": agent_id,
                    "scope": draft_scope,
                    "pinned": bool(pinned),
                    "content": text,
                }
                if report.added_ids:
                    out["id"] = report.added_ids[0]
                if report.superseded_ids:
                    out["superseded_ids"] = list(report.superseded_ids)
                return out

        if (
            (clean_mode and normalize_memory_mode(clean_mode) != MEMORY_MODE_SHARED)
            or is_roleplay_player_persona(clean_persona)
            or (clean_session and not clean_mode)
        ):
            return {"error": "save-scoped memory store unavailable"}
        with ops._mem0_operation_lock:
            candidates = _search_mem0(
                mem,
                text,
                filters={"user_id": agent_id},
                limit=ops._SEMANTIC_DEDUPLICATION_SEARCH_LIMIT,
            )
            duplicate = find_duplicate_memory(
                text,
                candidates,
                threshold=semantic_deduplication_threshold(),
            )
            if duplicate is not None:
                return {
                    "ok": True,
                    "duplicate": True,
                    "duplicate_type": duplicate.match_type,
                    "similarity": duplicate.similarity,
                    "existing_memory_id": duplicate.memory_id,
                    "existing_memory": duplicate.memory,
                    "agent_id": agent_id,
                    "content": text,
                }
            mem.add(text, user_id=agent_id, infer=False)
        return {"ok": True, "duplicate": False, "agent_id": agent_id, "content": text}
    except Exception as e:
        logger.exception("memory_remember 失败")
        return {"error": str(e)}


def memory_remember_and_list(
    content: str,
    character_name: str | None = None,
    *,
    pinned: bool = False,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "memory content is required"}
    ops = _package()
    extra_kwargs: dict[str, Any] = {}
    if pinned:
        extra_kwargs["pinned"] = True
        extra_kwargs["kind"] = kind or "profile"
    elif kind:
        extra_kwargs["kind"] = kind
    if gist_text:
        extra_kwargs["gist_text"] = gist_text
    if slot_key:
        extra_kwargs["slot_key"] = slot_key
    result = ops.memory_remember(
        text,
        character_name=character_name,
        source_session_id=session_id,
        **extra_kwargs,
    )
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return ops.memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_forget(
    memory_id: str, *, session_id: str | None = None, memory_mode: str = "",
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id is required"}
    ops = _package()
    ctx = _memory_request_context(session_id)
    sid = ctx.session_id
    mode = str(memory_mode or ctx.memory_mode).strip()
    payload = {"memoryId": mid}
    if sid:
        payload["sessionId"] = sid
    if mode:
        payload["memoryMode"] = mode
    service_result = ops._memory_service_request("forget", payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    try:
        with ops._mem0_operation_lock:
            if isinstance(mem, HybridMemoryEngine):
                with borrow_session_store_by_id(sid) as store:
                    save_repo = getattr(store, "save_memory_repo", None)
                    resolved_mode = (
                        store.get_memory_mode() if store is not None and not mode
                        else normalize_memory_mode(mode)
                    )
                    if save_repo is None and (sid or resolved_mode != MEMORY_MODE_SHARED):
                        return {"error": "save-scoped memory store unavailable"}
                    deleted = save_repo is not None and save_repo.delete(mid)
                    if not deleted and resolved_mode == MEMORY_MODE_SHARED:
                        deleted = mem.repo.delete(mid)
            else:
                if sid or normalize_memory_mode(mode) != MEMORY_MODE_SHARED:
                    return {"error": "save-scoped memory store unavailable"}
                result = mem.delete(mid)
                deleted = result is not False
        if not deleted:
            return {"error": "memory not found", "memory_id": mid}
        return {"ok": True, "memory_id": mid}
    except Exception as exc:
        logger.exception("memory_forget failed")
        return {"error": str(exc)}


def memory_forget_and_list(
    memory_id: str,
    character_name: str | None = None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    ops = _package()
    result = ops.memory_forget(mid, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return ops.memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_forget_many_and_list(
    memory_ids: Sequence[str],
    character_name: str | None = None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Delete several memories, then return the refreshed list once.

    Individual failures do not abort the batch; they are reported in ``failed``.
    """
    seen: set[str] = set()
    ids: list[str] = []
    for raw in memory_ids or ():
        mid = str(raw or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    if not ids:
        return {"error": "memory ids are required"}
    ops = _package()
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for mid in ids:
        result = ops.memory_forget(mid, session_id=session_id)
        if isinstance(result, dict) and result.get("status") == "loading":
            return result
        if isinstance(result, dict) and result.get("error"):
            failed.append({"memoryId": mid, "error": str(result.get("error"))})
            continue
        deleted.append(mid)
    if not deleted and failed:
        return {"error": failed[0]["error"], "failed": failed}
    listed = ops.memory_list(character_name, **({"session_id": session_id} if session_id else {}))
    if isinstance(listed, dict) and not listed.get("error"):
        listed = {**listed, "deleted": deleted, "failed": failed}
    return listed


def _update_repo_pin(repo: Any, memory_id: str, pinned: bool) -> bool:
    existing = repo.get(memory_id) if hasattr(repo, "get") else None
    if existing is None:
        return False
    if pinned and existing.scope == SCOPE_CHAR_CROSS_SAVE:
        repo.upsert(replace(existing, pinned=True, scope=SCOPE_CHAR_CANON))
        return True
    if not pinned and (existing.scope == SCOPE_CHAR_CANON or existing.kind == "canon"):
        demoted_scope = (
            SCOPE_SELF_PUBLIC
            if existing.owner_id == "__self__"
            else (
                SCOPE_SAVE_ISOLATED
                if existing.scope == SCOPE_SAVE_ISOLATED
                else SCOPE_CHAR_CROSS_SAVE
            )
        )
        demoted = replace(
            existing,
            pinned=False,
            scope=demoted_scope,
            kind="profile" if existing.kind == "canon" else existing.kind,
        )
        repo.upsert(demoted)
        return True
    return bool(repo.set_pinned(memory_id, bool(pinned)))


def _memory_mutation_repositories(engine: HybridMemoryEngine, store: Any, sid: str):
    if not sid:
        return (engine.repo,)
    save_repo = getattr(store, "save_memory_repo", None)
    if save_repo is None:
        raise ValueError("save-scoped memory store unavailable")
    if store.get_memory_mode() == MEMORY_MODE_SHARED:
        return (save_repo, engine.repo)
    return (save_repo,)


def memory_set_pinned(
    memory_id: str,
    pinned: bool,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    ops = _package()
    sid = _memory_request_context(session_id).session_id
    req_payload: dict[str, Any] = {"memoryId": mid, "pinned": bool(pinned)}
    if sid:
        req_payload["sessionId"] = sid
    service_result = ops._memory_service_request("pin", req_payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    try:
        updated = False
        with ops._mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
            if isinstance(mem, HybridMemoryEngine):
                updated = any(
                    _update_repo_pin(repo, mid, pinned)
                    for repo in _memory_mutation_repositories(mem, sess_store, sid)
                )
            elif not sid and hasattr(mem, "set_pinned"):
                updated = bool(mem.set_pinned(mid, pinned))
        if not updated:
            return {"error": "memory not found in a writable scope", "memory_id": mid}
        return {"ok": True, "memory_id": mid, "pinned": bool(pinned), "updated": True}
    except Exception as exc:
        logger.exception("memory_set_pinned 失败")
        return {"error": str(exc)}


def memory_set_pinned_and_list(
    memory_id: str,
    pinned: bool,
    character_name: str | None = None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    ops = _package()
    result = ops.memory_set_pinned(memory_id, pinned, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return ops.memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_awaken(
    memory_id: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    ops = _package()
    sid = _memory_request_context(session_id).session_id
    req_payload: dict[str, Any] = {"memoryId": mid}
    if sid:
        req_payload["sessionId"] = sid
    service_result = ops._memory_service_request("awaken", req_payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    try:
        awakened = 0
        now_ts = time.time()
        with ops._mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
            if isinstance(mem, HybridMemoryEngine):
                for repo in _memory_mutation_repositories(mem, sess_store, sid):
                    awakened = int(repo.record_recall((mid,), recalled_at=now_ts))
                    if awakened:
                        break
            elif not sid and hasattr(mem, "record_recall"):
                awakened = int(mem.record_recall((mid,), recalled_at=now_ts))
        if not awakened:
            return {"error": "memory not found in a writable scope", "memory_id": mid}
        return {"ok": True, "memory_id": mid, "awakened": awakened}
    except Exception as exc:
        logger.exception("memory_awaken 失败")
        return {"error": str(exc)}


def memory_awaken_and_list(
    memory_id: str,
    character_name: str | None = None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    ops = _package()
    result = ops.memory_awaken(memory_id, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return ops.memory_list(character_name, **({"session_id": session_id} if session_id else {}))
