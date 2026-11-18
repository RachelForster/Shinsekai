"""Timeline rollback operations for session truncation and reroll."""

from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
from typing import Any

from ai.memory.constants import MEMORY_STORE_FILENAME
from ai.memory.engine import HybridMemoryEngine
from ai.memory.operations.context import _package
from ai.memory.ports import resolve_registered_memory_repository
from core.chat_history.models import rollback_memory_for_timeline
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore

logger = logging.getLogger(__name__)


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

    ops = _package()
    payload: dict[str, Any] = {"sessionId": sid, "turnSeq": cutoff}
    if protected_turn_seqs:
        payload["protectedTurnSeqs"] = list(protected_turn_seqs)
    service_result = ops._memory_service_request(
        "rollback",
        payload,
        monitor_ready=False,
    )
    if service_result is not None:
        return service_result

    try:
        with ops._mem0_operation_lock:
            loaded = ops.peek_mem0()
            if isinstance(loaded, HybridMemoryEngine):
                removed = rollback_memory_for_timeline(
                    loaded.repo.rollback_after_turn, sid, cutoff, protected_turn_seqs
                )
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": int(removed),
                }
            if loaded is not None and hasattr(loaded, "rollback_after_turn"):
                removed = rollback_memory_for_timeline(
                    loaded.rollback_after_turn, sid, cutoff, protected_turn_seqs
                )
                return {
                    "ok": True,
                    "session_id": sid,
                    "turn_seq": cutoff,
                    "rolled_back": int(removed),
                }

            registered_repo = resolve_registered_memory_repository()
            if registered_repo is not None:
                try:
                    removed = rollback_memory_for_timeline(
                        registered_repo.rollback_after_turn, sid, cutoff, protected_turn_seqs
                    )
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
                removed = transient_store.rollback_after_turn(
                    sid, cutoff, protected_turn_seqs=protected_turn_seqs
                )
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
    res = _package().memory_rollback_after_turn(
        session_id, turn_seq, protected_turn_seqs=protected_turn_seqs
    )
    if not isinstance(res, dict) or res.get("error"):
        return 0
    try:
        return int(res.get("rolled_back") or 0)
    except (TypeError, ValueError):
        return 0
