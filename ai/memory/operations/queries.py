"""Read-side memory queries: list, full export pagination, search, and turn recall."""

from __future__ import annotations

from dataclasses import replace
import inspect
import logging
import time
from typing import Any

from ai.memory.ebbinghaus import EbbinghausRetentionPolicy
from ai.memory.engine import (
    HybridMemoryEngine,
    resolve_memory_read_filter,
)
from ai.memory.operations.context import (
    _memory_request_context,
    _memory_row,
    _package,
    _resolve_agent_id,
    _search_mem0,
)
from ai.memory.ports import resolve_registered_retention_policy
from ai.memory.rule_recall_planner import RuleRecallPlanner
from core.chat_history.sqlite_session_store import borrow_session_store_by_id
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_SAVE_ISOLATED,
    MemoryRecord,
    MemoryScopeFilter,
    RetentionPolicy,
    TurnRecallInput,
)
from sdk.adapters.session import MEMORY_MODE_SHARED, normalize_memory_mode

logger = logging.getLogger(__name__)


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
    return {
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
        "topicTags": list(record.topic_tags),
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


def _count_repo_memories(repo: Any, scope_filter: MemoryScopeFilter) -> int | None:
    counter = getattr(repo, "count_memories", None)
    if not callable(counter):
        return None
    try:
        return int(counter(scope_filter))
    except Exception:
        logger.debug("count_memories failed", exc_info=True)
        return None


def memory_list(
    character_name: str | None = None,
    *,
    limit: int = 200,
    offset: int = 0,
    session_id: str = "",
) -> dict[str, Any]:
    """List one window of memories ordered pinned-first, newest-first.

    The result carries ``total`` (all matching memories, when the backend can count
    them) plus ``offset``/``limit`` so callers can page through large stores.
    """
    ops = _package()
    agent_id = _resolve_agent_id(character_name)
    sid = str(session_id or "").strip()
    max_items = max(1, int(limit))
    start = max(0, int(offset or 0))
    req_payload: dict[str, Any] = {"name": agent_id, "limit": max_items}
    if start:
        req_payload["offset"] = start
    if sid:
        req_payload["sessionId"] = sid
    service_result = ops._memory_service_request("list", req_payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    fetch_limit = start + max_items
    if isinstance(mem, HybridMemoryEngine):
        read_filter = resolve_memory_read_filter(agent_id)
        policy = (
            getattr(mem.orchestrator, "retention_policy", None)
            or resolve_registered_retention_policy()
            or EbbinghausRetentionPolicy()
        )
        now_ts = time.time()
        total: int | None = 0
        with ops._mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
            records_by_id: dict[str, MemoryRecord] = {}
            # Each repo returns its own top ``offset + limit`` rows; merging those and
            # slicing yields the exact requested window of the combined ordering.
            for rec in mem.repo.list_by_scope(read_filter, limit=fetch_limit):
                records_by_id[rec.id] = rec
            repo_total = _count_repo_memories(mem.repo, read_filter)
            total = None if repo_total is None else repo_total
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
                for rec in save_repo.list_by_scope(save_filter, limit=fetch_limit):
                    records_by_id[rec.id] = rec
                save_total = _count_repo_memories(save_repo, save_filter)
                total = None if total is None or save_total is None else total + save_total

        # Mirror the repository ORDER BY (pinned first, newest first) so windows stay
        # consistent across offsets.
        sorted_records = sorted(
            records_by_id.values(),
            key=lambda r: (0 if r.pinned else 1, -float(r.created_at)),
        )
        window = sorted_records[start:start + max_items]
        memories = [
            _serialize_memory_record(rec, policy=policy, now_ts=now_ts)
            for rec in window
        ]
        if total is None:
            # Backend cannot count: report what we know (a lower bound when the window is full).
            total = start + len(memories) + (1 if len(sorted_records) > start + max_items else 0)
        return {
            "agentId": agent_id,
            "count": len(memories),
            "memories": memories,
            "total": int(total),
            "offset": start,
            "limit": max_items,
        }

    with ops._mem0_operation_lock:
        parameters = inspect.signature(mem.get_all).parameters
        pagination = {"top_k": fetch_limit} if "top_k" in parameters else {"limit": fetch_limit}
        raw = mem.get_all(filters={"user_id": agent_id}, **pagination)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = [_memory_row(row) for row in rows][start:start + max_items]
    result: dict[str, Any] = {"agentId": agent_id, "count": len(memories), "memories": memories}
    if start:
        result["offset"] = start
    if len(rows) < fetch_limit:
        # Fewer rows than requested means we saw everything.
        result["total"] = len(rows)
    return result


def memory_list_all(
    character_name: str | None = None,
    *,
    session_id: str = "",
    batch_size: int = 500,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Collect every memory for a character by paging through ``memory_list``."""
    ops = _package()
    size = max(1, int(batch_size))
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    agent_id = _resolve_agent_id(character_name)
    offset = 0
    extra = {"session_id": session_id} if session_id else {}
    while offset < max_items:
        page = ops.memory_list(character_name, limit=size, offset=offset, **extra)
        if not isinstance(page, dict) or page.get("error") or page.get("status") == "loading":
            return page
        if offset > 0 and page.get("offset") != offset:
            # Legacy backends ignore offset; stop instead of re-reading the first window.
            break
        agent_id = str(page.get("agentId") or agent_id)
        rows = page.get("memories") or []
        for row in rows:
            key = str(row.get("id") or "") if isinstance(row, dict) else ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            collected.append(row)
        total = page.get("total")
        offset += len(rows)
        if len(rows) < size or (isinstance(total, int) and offset >= total):
            break
    return {"agentId": agent_id, "count": len(collected), "total": len(collected), "memories": collected}


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

    ops = _package()
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

    service_result = ops._memory_service_request("search", payload)
    if service_result is not None:
        return service_result
    mem = ops.ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            with ops._mem0_operation_lock, borrow_session_store_by_id(eff_session_id) as sess_store:
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

        with ops._mem0_operation_lock:
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
    ops = _package()
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
    service_result = ops._memory_service_request("recall", payload)
    if service_result is not None:
        return service_result

    mem = ops.ensure_mem0()
    try:
        if isinstance(mem, HybridMemoryEngine):
            sid = str(turn_input.session_id or "").strip()
            with ops._mem0_operation_lock, borrow_session_store_by_id(sid) as sess_store:
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
        with ops._mem0_operation_lock:
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
