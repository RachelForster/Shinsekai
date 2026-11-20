"""User-facing memory operations backed by SOLID narrow ports."""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
import inspect
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from ai.memory.constants import MEMORY_STORE_FILENAME
from ai.memory.deduplication import find_duplicate_memory, semantic_deduplication_threshold
from ai.memory.ebbinghaus import EbbinghausRetentionPolicy
from ai.memory.metadata_tags import unpack_system_tags
from ai.memory.engine import (
    HybridMemoryEngine,
    resolve_memory_read_filter,
)
from ai.memory.orchestrator import is_roleplay_player_persona
from ai.memory.ports import (
    resolve_registered_memory_repository,
    resolve_registered_retention_policy,
)
from ai.memory.rule_recall_planner import RuleRecallPlanner
from ai.memory.runtime import ensure_mem0, peek_mem0
from core.chat_history.models import rollback_memory_for_timeline
from core.chat_history.sqlite_session_store import borrow_session_store_by_id
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    MemoryDraft,
    MemoryRecord,
    MemoryScopeFilter,
    RetentionPolicy,
    TurnRecallInput,
)
from sdk.adapters.session import MEMORY_MODE_SHARED, normalize_memory_mode

logger = logging.getLogger(__name__)
_MEMORY_SERVICE_URL_ENV = "SHINSEKAI_MEMORY_SERVICE_URL"
_MEMORY_SERVICE_TOKEN_ENV = "SHINSEKAI_MEMORY_SERVICE_TOKEN"
_MEMORY_SERVICE_OWNER_ENV = "SHINSEKAI_MEMORY_SERVICE_OWNER"
_MEMORY_SERVICE_TIMEOUT_ENV = "SHINSEKAI_MEMORY_SERVICE_TIMEOUT_SEC"
_MEMORY_SERVICE_TOKEN_HEADER = "X-Shinsekai-Bridge-Token"
_MEMORY_SERVICE_READY_MESSAGE = "记忆系统已就绪，可以继续使用。"
_MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC = 60.0
_MEMORY_SERVICE_READY_POLL_INTERVAL_SEC = 2.0
_MEMORY_SERVICE_READY_POLL_TIMEOUT_SEC = 300.0
_service_monitor_lock = threading.Lock()
_service_monitor_active = False
_mem0_operation_lock = threading.RLock()
_SEMANTIC_DEDUPLICATION_SEARCH_LIMIT = 5


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


def _memory_service_url() -> str:
    if str(os.environ.get(_MEMORY_SERVICE_OWNER_ENV) or "").strip() == "1":
        return ""
    return str(os.environ.get(_MEMORY_SERVICE_URL_ENV) or "").strip().rstrip("/")


def _memory_service_timeout_sec() -> float:
    raw = str(os.environ.get(_MEMORY_SERVICE_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default timeout", _MEMORY_SERVICE_TIMEOUT_ENV, raw)
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    if timeout <= 0:
        logger.warning("non-positive %s=%r; using default timeout", _MEMORY_SERVICE_TIMEOUT_ENV, raw)
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    return timeout


def is_memory_backend_ready() -> bool:
    """Return True when either the HTTP bridge or an initialized/patched local engine is active."""
    if _memory_service_url():
        return True
    if peek_mem0() is not None:
        return True
    from ai.memory import runtime as _rt

    return ensure_mem0 is not _rt.ensure_mem0


def _memory_service_request(
    endpoint: str,
    payload: dict[str, Any],
    *,
    monitor_ready: bool = True,
) -> dict[str, Any] | None:
    base_url = _memory_service_url()
    if not base_url:
        return None

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = str(os.environ.get(_MEMORY_SERVICE_TOKEN_ENV) or "").strip()
    if token:
        headers[_MEMORY_SERVICE_TOKEN_HEADER] = token

    request = urllib.request.Request(
        f"{base_url}/{endpoint.strip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_memory_service_timeout_sec()) as response:
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return {"error": f"memory service HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"error": f"memory service unavailable: {exc}"}

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        preview = raw[:200].decode("utf-8", errors="replace")
        return {"error": f"memory service returned invalid JSON: {exc}; body={preview!r}"}
    result = data if isinstance(data, dict) else {"result": data}
    if monitor_ready and result.get("status") == "loading":
        _start_memory_service_ready_monitor()
    return result


def memory_service_status(
    *,
    start_loading: bool,
    monitor_ready: bool = True,
) -> dict[str, Any] | None:
    """Return bridge-owned memory status without loading engine in this process."""
    return _memory_service_request(
        "status",
        {"startLoading": bool(start_loading)},
        monitor_ready=monitor_ready,
    )


def _start_memory_service_ready_monitor() -> None:
    global _service_monitor_active
    if not _memory_service_url():
        return
    with _service_monitor_lock:
        if _service_monitor_active:
            return
        _service_monitor_active = True

    def _monitor() -> None:
        global _service_monitor_active
        deadline = time.monotonic() + _MEMORY_SERVICE_READY_POLL_TIMEOUT_SEC
        try:
            while time.monotonic() < deadline:
                time.sleep(_MEMORY_SERVICE_READY_POLL_INTERVAL_SEC)
                status = _memory_service_request("status", {})
                if not isinstance(status, dict):
                    continue
                if status.get("status") == "ready":
                    try:
                        from sdk.tool_registry import notify_tool_ready

                        notify_tool_ready("memory", _MEMORY_SERVICE_READY_MESSAGE)
                    except Exception:
                        logger.exception("memory service ready notification failed")
                    return
                if status.get("status") in {"error", "missing_dependency"}:
                    return
        finally:
            with _service_monitor_lock:
                _service_monitor_active = False

    threading.Thread(target=_monitor, name="memory-service-ready-monitor", daemon=True).start()


def _serialize_memory_record(
    record: MemoryRecord,
    *,
    policy: RetentionPolicy,
    now_ts: float,
) -> dict[str, Any]:
    state = policy.evaluate(record, now_ts=now_ts)
    is_pinned = bool(
        record.pinned or record.scope == SCOPE_CHAR_CANON or record.kind == "canon"
    )
    meta = unpack_system_tags(record.topic_tags)
    payload: dict[str, Any] = {
        "id": record.id,
        "memory": record.detail_text,
        "detail": record.detail_text,
        "gist": record.gist_text or record.detail_text,
        "clarity": state.tier,
        "retention": round(float(state.retention), 4),
        "kind": record.kind,
        "pinned": is_pinned,
        "scope": record.scope,
        "slotKey": record.slot_key,
        "topicTags": list(meta.public_tags),
        "entities": list(record.entities),
        "importance": round(float(record.importance), 3),
        "createdAt": float(record.created_at),
        "eventAt": float(record.event_at) if record.event_at is not None else None,
        "lastRecalledAt": (
            float(record.last_recalled_at)
            if record.last_recalled_at is not None
            else None
        ),
        "recallCount": int(record.recall_count),
        "sourceSessionId": record.source_session_id,
    }
    if meta.visual_ref:
        payload["visualRef"] = meta.visual_ref
    if meta.valid_until is not None:
        payload["validUntil"] = float(meta.valid_until)
    if meta.consolidated_seq is not None:
        payload["consolidatedSeq"] = int(meta.consolidated_seq)
    return payload


def memory_list(
    character_name: str | None = None,
    *,
    limit: int = 200,
    session_id: str = "",
) -> dict[str, Any]:
    agent_id = _resolve_agent_id(character_name)
    sid = str(session_id or "").strip()
    req_payload: dict[str, Any] = {"name": agent_id, "limit": limit}
    if sid:
        req_payload["sessionId"] = sid
    service_result = _memory_service_request("list", req_payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    if isinstance(mem, HybridMemoryEngine):
        max_items = max(1, int(limit))
        read_filter = resolve_memory_read_filter(agent_id)
        policy = (
            getattr(mem.orchestrator, "retention_policy", None)
            or resolve_registered_retention_policy()
            or EbbinghausRetentionPolicy()
        )
        now_ts = time.time()
        with _mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
            records_by_id: dict[str, MemoryRecord] = {}
            for rec in mem.repo.list_by_scope(read_filter, limit=max_items):
                records_by_id[rec.id] = rec
            save_repo = (
                getattr(sess_store, "save_memory_repo", None)
                if sess_store is not None
                else None
            )
            if save_repo is not None:
                save_filter = MemoryScopeFilter(
                    scopes=(SCOPE_SAVE_ISOLATED,),
                    owner_ids=read_filter.owner_ids,
                    session_id=sid or None,
                )
                for rec in save_repo.list_by_scope(save_filter, limit=max_items):
                    records_by_id[rec.id] = rec

        sorted_records = sorted(
            (
                r
                for r in records_by_id.values()
                if str(r.kind or "").strip().lower() != "retraction"
            ),
            key=lambda r: (
                0 if (r.pinned or r.scope == SCOPE_CHAR_CANON or r.kind == "canon") else 1,
                -float(r.created_at),
            ),
        )[:max_items]
        memories = [
            _serialize_memory_record(rec, policy=policy, now_ts=now_ts)
            for rec in sorted_records
        ]
        return {"agentId": agent_id, "count": len(memories), "memories": memories}

    with _mem0_operation_lock:
        parameters = inspect.signature(mem.get_all).parameters
        pagination = {"top_k": limit} if "top_k" in parameters else {"limit": limit}
        raw = mem.get_all(filters={"user_id": agent_id}, **pagination)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = [_memory_row(row) for row in rows]
    return {"agentId": agent_id, "count": len(memories), "memories": memories}


def memory_search(
    query: str,
    character_name: str | None = None,
    *,
    limit: int = 10,
    session_id: str | None = None,
    memory_mode: str = "",
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "query 不能为空"}

    ctx = _memory_request_context(session_id)
    eff_session_id = ctx.session_id
    eff_mode = str(memory_mode or ctx.memory_mode).strip()
    agent_id = _resolve_agent_id(character_name)

    payload: dict[str, Any] = {
        "query": q,
        "characterName": agent_id,
        "limit": limit,
    }
    if eff_session_id:
        payload["sessionId"] = eff_session_id
    if eff_mode:
        payload["memoryMode"] = eff_mode

    service_result = _memory_service_request("search", payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            with _mem0_operation_lock, borrow_session_store_by_id(eff_session_id) as sess_store:
                save_repo = getattr(sess_store, "save_memory_repo", None) if sess_store is not None else None
                resolved_mode = (
                    normalize_memory_mode(eff_mode)
                    if eff_mode
                    else (
                        sess_store.get_memory_mode()
                        if sess_store is not None
                        else MEMORY_MODE_SHARED
                    )
                )
                if save_repo is None and (resolved_mode != MEMORY_MODE_SHARED or (eff_session_id and not eff_mode)):
                    return {"error": "save-scoped memory store unavailable"}
                mems = mem.orchestrator.search_for_tool(
                    q,
                    character_name=agent_id,
                    session_id=eff_session_id,
                    memory_mode=resolved_mode,
                    save_repo=save_repo,
                    limit=max(1, int(limit)),
                )
            return {
                "agent_id": agent_id,
                "query": q,
                "count": len(mems),
                "memories": mems,
            }

        with _mem0_operation_lock:
            results = _search_mem0(mem, q, filters={"user_id": agent_id}, limit=limit)
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


def memory_recall_turn(turn_input: TurnRecallInput) -> dict[str, Any]:
    """Execute Phase 3 hybrid turn recall (planner + Ebbinghaus + save-mode isolation)."""
    payload: dict[str, Any] = {
        "userText": turn_input.user_text,
        "previousAssistantText": turn_input.previous_assistant_text,
        "activeCharacterNames": list(turn_input.active_character_names),
        "sessionId": turn_input.session_id,
        "memoryMode": turn_input.memory_mode,
        "source": turn_input.source,
        "nowTs": turn_input.now_ts,
        "secondsSinceLastTurn": turn_input.seconds_since_last_turn,
        "inWindowTurnSeqs": sorted(int(x) for x in turn_input.in_window_turn_seqs),
        "recentlyInjectedIds": sorted(str(x) for x in turn_input.recently_injected_ids),
    }
    service_result = _memory_service_request("recall", payload)
    if service_result is not None:
        return service_result

    mem = ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            sid = str(turn_input.session_id or "").strip()
            with _mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
                save_repo = getattr(sess_store, "save_memory_repo", None) if sess_store is not None else None
                explicit_mode = str(turn_input.memory_mode or "").strip()
                resolved_mode = (
                    sess_store.get_memory_mode()
                    if sess_store is not None and not explicit_mode
                    else normalize_memory_mode(explicit_mode or MEMORY_MODE_SHARED)
                )
                if save_repo is None and (resolved_mode != MEMORY_MODE_SHARED or (sid and not explicit_mode)):
                    return {"error": "save-scoped memory store unavailable"}
                effective_input = replace(turn_input, memory_mode=resolved_mode)
                block = mem.orchestrator.recall_for_turn(
                    effective_input,
                    save_repo=save_repo,
                )
            return {
                "ok": True,
                "rendered": block.rendered,
                "recalled_ids": list(block.recalled_ids),
            }

        planner = RuleRecallPlanner()
        plan = planner.plan(turn_input)
        if not plan.should_recall:
            return {"ok": True, "rendered": "", "recalled_ids": []}
        agent_id = (
            turn_input.active_character_names[0]
            if turn_input.active_character_names
            else "user"
        )
        q_text = plan.query_clauses[0] if plan.query_clauses else turn_input.user_text
        with _mem0_operation_lock:
            results = _search_mem0(mem, q_text, filters={"user_id": agent_id}, limit=plan.limit)
        rows = (
            results.get("results", [])
            if isinstance(results, dict)
            else (results if isinstance(results, list) else [])
        )
        recalled_ids: list[str] = []
        lines: list[str] = []
        for row in rows:
            normalized = _memory_row(row)
            if normalized["id"] and normalized["id"] in turn_input.recently_injected_ids:
                continue
            if normalized["memory"]:
                if normalized["id"]:
                    recalled_ids.append(normalized["id"])
                lines.append(f"- {normalized['memory']}")
        if not lines:
            return {"ok": True, "rendered": "", "recalled_ids": []}
        rendered = (
            "[Shinsekai long-term memory context]\n"
            "Relevant long-term memories for this turn. Use them only as background; "
            "do not mention the retrieval process unless the user asks.\n"
            + "\n".join(lines)
        )
        return {"ok": True, "rendered": rendered, "recalled_ids": recalled_ids}
    except Exception as exc:
        logger.exception("memory_recall_turn 失败")
        return {"error": str(exc)}


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

    service_result = _memory_service_request("remember", payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            with _mem0_operation_lock, borrow_session_store_by_id(
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
        with _mem0_operation_lock:
            candidates = _search_mem0(
                mem,
                text,
                filters={"user_id": agent_id},
                limit=_SEMANTIC_DEDUPLICATION_SEARCH_LIMIT,
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
    result = memory_remember(
        text,
        character_name=character_name,
        source_session_id=session_id,
        **extra_kwargs,
    )
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_forget(
    memory_id: str, *, session_id: str | None = None, memory_mode: str = "",
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id is required"}
    ctx = _memory_request_context(session_id)
    sid = ctx.session_id
    mode = str(memory_mode or ctx.memory_mode).strip()
    payload = {"memoryId": mid}
    if sid:
        payload["sessionId"] = sid
    if mode:
        payload["memoryMode"] = mode
    service_result = _memory_service_request("forget", payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        with _mem0_operation_lock:
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
    result = memory_forget(mid, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name, **({"session_id": session_id} if session_id else {}))


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
    sid = _memory_request_context(session_id).session_id
    req_payload: dict[str, Any] = {"memoryId": mid, "pinned": bool(pinned)}
    if sid:
        req_payload["sessionId"] = sid
    service_result = _memory_service_request("pin", req_payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        updated = False
        with _mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
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
    result = memory_set_pinned(memory_id, pinned, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_awaken(
    memory_id: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    sid = _memory_request_context(session_id).session_id
    req_payload: dict[str, Any] = {"memoryId": mid}
    if sid:
        req_payload["sessionId"] = sid
    service_result = _memory_service_request("awaken", req_payload)
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        awakened = 0
        now_ts = time.time()
        with _mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
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
    result = memory_awaken(memory_id, session_id=session_id)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name, **({"session_id": session_id} if session_id else {}))


def memory_rollback_after_turn(
    session_id: str,
    turn_seq: int,
    *,
    protected_turn_seqs: Sequence[int] = (),
) -> dict[str, Any]:
    """Roll back unpinned memories created after turn_seq and restore superseded slots."""
    sid = str(session_id or "").strip()
    cutoff = max(0, int(turn_seq))
    if not sid:
        return {"ok": True, "session_id": "", "turn_seq": cutoff, "rolled_back": 0}

    payload: dict[str, Any] = {"sessionId": sid, "turnSeq": cutoff}
    if protected_turn_seqs:
        payload["protectedTurnSeqs"] = list(protected_turn_seqs)
    service_result = _memory_service_request(
        "rollback",
        payload,
        monitor_ready=False,
    )
    if service_result is not None:
        return service_result

    try:
        with _mem0_operation_lock:
            loaded = peek_mem0()
            if isinstance(loaded, HybridMemoryEngine):
                removed = rollback_memory_for_timeline(loaded.repo.rollback_after_turn, sid, cutoff, protected_turn_seqs)
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": int(removed),
                }
            if loaded is not None and hasattr(loaded, "rollback_after_turn"):
                removed = rollback_memory_for_timeline(loaded.rollback_after_turn, sid, cutoff, protected_turn_seqs)
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": int(removed),
                }

            registered_repo = resolve_registered_memory_repository()
            if registered_repo is not None:
                try:
                    removed = rollback_memory_for_timeline(registered_repo.rollback_after_turn, sid, cutoff, protected_turn_seqs)
                finally:
                    close_fn = getattr(registered_repo, "close", None)
                    if callable(close_fn):
                        close_fn()
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": int(removed),
                }

            db_path = Path.cwd() / "data" / "memory" / MEMORY_STORE_FILENAME
            if not db_path.is_file():
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": 0,
                }
            transient_store = SqliteHybridStore(db_path, max_idle_connections=1)
            try:
                removed = transient_store.rollback_after_turn(sid, cutoff, protected_turn_seqs=protected_turn_seqs)
            finally:
                transient_store.close()
            return {
                "ok": True,
                "session_id": sid,
                "turn_seq": cutoff,
                "rolled_back": int(removed),
            }
    except Exception as exc:
        logger.exception("memory_rollback_after_turn 失败")
        return {"error": str(exc)}


def memory_rollback_count(
    session_id: str, turn_seq: int, *, protected_turn_seqs: Sequence[int] = (),
) -> int:
    """Convenience adapter returning integer rolled_back count for session truncation."""
    res = memory_rollback_after_turn(session_id, turn_seq, protected_turn_seqs=protected_turn_seqs)
    if not isinstance(res, dict) or res.get("error"):
        return 0
    try:
        return int(res.get("rolled_back") or 0)
    except (TypeError, ValueError):
        return 0
