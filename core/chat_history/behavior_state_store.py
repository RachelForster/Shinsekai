"""Atomic behavior state snapshots, transactional turn commits, and crash recovery."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import time
from typing import TYPE_CHECKING, Any
import uuid

from core.chat_history.behavior_state_models import (
    BEHAVIOR_TURN_JOURNAL_FILENAME,
    BehaviorCommitResult,
    BehaviorRecoveryReport,
    BehaviorStateSnapshot,
    BehaviorTurnJournalRecord,
    BehaviorVersionConflictError,
    atomic_write_journal,
    ensure_behavior_state_schema,
    normalize_branch_id,
    row_to_behavior_snapshot,
)
from core.chat_history.models import strip_internal_message_keys, turn_node_from_message

if TYPE_CHECKING:
    from core.chat_history.sqlite_session_store import SqliteSessionStore


@contextmanager
def _immediate_tx(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        conn.rollback()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.commit()


def _serialize_outfits_for_turn(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT character_name, active_group, locked, updated_at_ms "
        "FROM outfit_states ORDER BY character_name ASC"
    ).fetchall()
    payload = {
        str(row["character_name"]): {
            "character_name": str(row["character_name"]),
            "active_group": str(row["active_group"] or ""),
            "locked": bool(row["locked"]),
            "updated_at_ms": int(row["updated_at_ms"] or 0),
        }
        for row in rows
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class BehaviorStateStore:
    """Coordinate atomic SQLite commits for turns and SessionBehavior snapshots."""

    def __init__(
        self,
        session_store: SqliteSessionStore,
        session_dir: str | Path | None = None,
    ) -> None:
        self._session_store = session_store
        if session_dir is not None and str(session_dir).strip():
            self._session_dir: Path | None = Path(session_dir)
        elif session_store.db_path is not None:
            self._session_dir = session_store.db_path.parent
        else:
            self._session_dir = None
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                ensure_behavior_state_schema(conn)
                conn.commit()

    @property
    def journal_path(self) -> Path | None:
        if self._session_dir is None:
            return None
        return self._session_dir / BEHAVIOR_TURN_JOURNAL_FILENAME

    def _get_latest_conn(
        self, conn: sqlite3.Connection, branch_id: str
    ) -> BehaviorStateSnapshot | None:
        row = conn.execute(
            "SELECT branch_id, turn_seq, behavior_id, state_version, state_json, created_at_ms "
            "FROM session_state_snapshots "
            "WHERE branch_id = ? "
            "ORDER BY state_version DESC, turn_seq DESC LIMIT 1",
            (normalize_branch_id(branch_id),),
        ).fetchone()
        return row_to_behavior_snapshot(row) if row is not None else None

    def get_latest_state(self, branch_id: str = "main") -> BehaviorStateSnapshot | None:
        with self._session_store._store._borrow_conn() as conn:
            return self._get_latest_conn(conn, branch_id)

    def get_state_at_or_before(
        self, branch_id: str, turn_seq: int
    ) -> BehaviorStateSnapshot | None:
        b = normalize_branch_id(branch_id)
        with self._session_store._store._borrow_conn() as conn:
            row = conn.execute(
                "SELECT branch_id, turn_seq, behavior_id, state_version, state_json, created_at_ms "
                "FROM session_state_snapshots "
                "WHERE branch_id = ? AND turn_seq <= ? "
                "ORDER BY turn_seq DESC, state_version DESC LIMIT 1",
                (b, max(0, int(turn_seq))),
            ).fetchone()
            return row_to_behavior_snapshot(row) if row is not None else None

    def initialize_state(
        self,
        *,
        branch_id: str = "main",
        behavior_id: str,
        state: Mapping[str, Any],
        created_at_ms: int | None = None,
    ) -> BehaviorStateSnapshot:
        b = normalize_branch_id(branch_id)
        bid = str(behavior_id or "").strip()
        if not bid:
            raise ValueError("behavior_id must not be empty")
        now_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        state_copy = copy.deepcopy(dict(state))
        state_json = json.dumps(state_copy, ensure_ascii=False, separators=(",", ":"))
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                existing = self._get_latest_conn(conn, b)
                if existing is not None:
                    return existing
                with _immediate_tx(conn):
                    conn.execute(
                        "INSERT INTO session_state_snapshots("
                        "branch_id, turn_seq, behavior_id, state_version, state_json, created_at_ms"
                        ") VALUES (?, 0, ?, 1, ?, ?)",
                        (b, bid, state_json, now_ms),
                    )
                return BehaviorStateSnapshot(
                    branch_id=b,
                    turn_seq=0,
                    behavior_id=bid,
                    state_version=1,
                    state=state_copy,
                    created_at_ms=now_ms,
                )

    def commit_behavior_turn(
        self,
        *,
        branch_id: str = "main",
        behavior_id: str,
        expected_state_version: int,
        next_state: Mapping[str, Any],
        messages: Sequence[Mapping[str, Any]] = (),
        created_at_ms: int | None = None,
    ) -> BehaviorCommitResult:
        b = normalize_branch_id(branch_id)
        bid = str(behavior_id or "").strip()
        if not bid:
            raise ValueError("behavior_id must not be empty")
        now_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        state_copy = copy.deepcopy(dict(next_state))
        state_json = json.dumps(state_copy, ensure_ascii=False, separators=(",", ":"))
        jpath = self.journal_path

        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                latest = self._get_latest_conn(conn, b)
                actual_ver = latest.state_version if latest is not None else None
                if latest is None or actual_ver != int(expected_state_version):
                    raise BehaviorVersionConflictError(
                        int(expected_state_version), actual_ver, branch_id=b
                    )
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM turns WHERE branch_id = ?",
                    (b,),
                ).fetchone()
                base_turn_seq = int(max_row["max_seq"]) if max_row is not None else 0
                next_ver = int(expected_state_version) + 1

                if jpath is not None:
                    atomic_write_journal(
                        jpath,
                        BehaviorTurnJournalRecord(
                            journal_id=uuid.uuid4().hex,
                            branch_id=b,
                            behavior_id=bid,
                            base_turn_seq=base_turn_seq,
                            base_state_version=int(expected_state_version),
                            next_state_version=next_ver,
                            created_at_ms=now_ms,
                        ).to_dict(),
                    )

                appended_seqs: list[int] = []
                with _immediate_tx(conn):
                    outfits_json = _serialize_outfits_for_turn(conn)
                    for raw_msg in messages:
                        if not isinstance(raw_msg, Mapping):
                            continue
                        role = str(raw_msg.get("role") or "").strip()
                        if role == "system":
                            conn.execute(
                                "INSERT INTO session_meta(key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                (f"system_prompt:{b}", str(raw_msg.get("content") or "")),
                            )
                            continue
                        node = turn_node_from_message(raw_msg, branch_id=b, created_at_ms=now_ms)
                        clean_raw = strip_internal_message_keys(node.raw_message)
                        cur = conn.execute(
                            """
                            INSERT INTO turns(
                                branch_id, turn_id, role, speaker, raw_message_json,
                                rendered_html, plain_text, voice_id, attachments_json,
                                source, outfit_snapshot_json, created_at_ms
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                b,
                                str(node.turn_id or ""),
                                node.role,
                                str(node.speaker or ""),
                                json.dumps(clean_raw, ensure_ascii=False, separators=(",", ":")),
                                str(node.rendered_html or ""),
                                str(node.plain_text or ""),
                                str(node.voice_id or ""),
                                json.dumps(
                                    list(node.attachments),
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                                str(node.source or node.role),
                                outfits_json,
                                now_ms,
                            ),
                        )
                        appended_seqs.append(int(cur.lastrowid or 0))

                    anchor_seq = (
                        appended_seqs[-1]
                        if appended_seqs
                        else max(0, base_turn_seq, latest.turn_seq)
                    )
                    conn.execute(
                        """
                        INSERT INTO session_state_snapshots(
                            branch_id, turn_seq, behavior_id, state_version, state_json, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(branch_id, turn_seq) DO UPDATE SET
                            behavior_id = excluded.behavior_id,
                            state_version = excluded.state_version,
                            state_json = excluded.state_json,
                            created_at_ms = excluded.created_at_ms
                        """,
                        (b, anchor_seq, bid, next_ver, state_json, now_ms),
                    )

            if jpath is not None:
                jpath.unlink(missing_ok=True)

        return BehaviorCommitResult(
            snapshot=BehaviorStateSnapshot(
                branch_id=b,
                turn_seq=anchor_seq,
                behavior_id=bid,
                state_version=next_ver,
                state=state_copy,
                created_at_ms=now_ms,
            ),
            appended_turn_seqs=tuple(appended_seqs),
        )

    def fork_branch(
        self,
        source_branch_id: str,
        target_branch_id: str,
        *,
        up_to_turn_seq: int | None = None,
    ) -> BehaviorStateSnapshot | None:
        src = normalize_branch_id(source_branch_id)
        dst = normalize_branch_id(target_branch_id)
        if src == dst:
            return self.get_latest_state(dst)
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                with _immediate_tx(conn):
                    conn.execute("DELETE FROM session_state_snapshots WHERE branch_id = ?", (dst,))
                    sql = (
                        "INSERT INTO session_state_snapshots("
                        "branch_id, turn_seq, behavior_id, state_version, state_json, created_at_ms"
                        ") SELECT ?, turn_seq, behavior_id, state_version, state_json, created_at_ms "
                        "FROM session_state_snapshots WHERE branch_id = ?"
                    )
                    params: tuple[Any, ...] = (dst, src)
                    if up_to_turn_seq is not None:
                        sql += " AND turn_seq <= ?"
                        params = (dst, src, max(0, int(up_to_turn_seq)))
                    conn.execute(sql, params)
                return self._get_latest_conn(conn, dst)

    def switch_branch(self, target_branch_id: str) -> BehaviorStateSnapshot | None:
        return self.get_latest_state(normalize_branch_id(target_branch_id))

    def remap_branch_id(self, old_branch_id: str, new_branch_id: str) -> int:
        old_b = normalize_branch_id(old_branch_id)
        new_b = normalize_branch_id(new_branch_id)
        if old_b == new_b:
            return 0
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                with _immediate_tx(conn):
                    cur = conn.execute(
                        "UPDATE session_state_snapshots SET branch_id = ? WHERE branch_id = ?",
                        (new_b, old_b),
                    )
                return int(cur.rowcount or 0)

    def truncate_after(self, branch_id: str, turn_seq: int) -> BehaviorStateSnapshot | None:
        b = normalize_branch_id(branch_id)
        cutoff = max(0, int(turn_seq))
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                with _immediate_tx(conn):
                    conn.execute(
                        "DELETE FROM session_state_snapshots WHERE branch_id = ? AND turn_seq > ?",
                        (b, cutoff),
                    )
                return self._get_latest_conn(conn, b)

    def clear_branch(
        self, branch_id: str, *, preserve_initial: bool = True
    ) -> BehaviorStateSnapshot | None:
        b = normalize_branch_id(branch_id)
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                with _immediate_tx(conn):
                    clause = "branch_id = ? AND turn_seq > 0" if preserve_initial else "branch_id = ?"
                    conn.execute(f"DELETE FROM session_state_snapshots WHERE {clause}", (b,))
                return self._get_latest_conn(conn, b)

    def recover_pending(self) -> BehaviorRecoveryReport:
        jpath = self.journal_path
        if jpath is None or not jpath.is_file():
            return BehaviorRecoveryReport(action="none")
        try:
            record = BehaviorTurnJournalRecord.from_dict(
                json.loads(jpath.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, KeyError, TypeError):
            jpath.unlink(missing_ok=True)
            return BehaviorRecoveryReport(action="cleaned_noop")

        b = normalize_branch_id(record.branch_id)
        with self._session_store._write_lock:
            with self._session_store._store._borrow_conn() as conn:
                latest = self._get_latest_conn(conn, b)
                if latest is not None and latest.state_version >= record.next_state_version:
                    jpath.unlink(missing_ok=True)
                    return BehaviorRecoveryReport(
                        action="finalized", branch_id=b, restored_snapshot=latest
                    )
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM turns WHERE branch_id = ?",
                    (b,),
                ).fetchone()
                max_seq = int(max_row["max_seq"]) if max_row is not None else 0
                if max_seq > record.base_turn_seq:
                    with _immediate_tx(conn):
                        conn.execute(
                            "DELETE FROM turns WHERE branch_id = ? AND seq > ?",
                            (b, record.base_turn_seq),
                        )
                        conn.execute(
                            "DELETE FROM session_state_snapshots WHERE branch_id = ? AND turn_seq > ?",
                            (b, record.base_turn_seq),
                        )
                    restored = self._get_latest_conn(conn, b)
                    jpath.unlink(missing_ok=True)
                    return BehaviorRecoveryReport(
                        action="rolled_back", branch_id=b, restored_snapshot=restored
                    )
                jpath.unlink(missing_ok=True)
                return BehaviorRecoveryReport(
                    action="cleaned_noop", branch_id=b, restored_snapshot=latest
                )


__all__ = [
    "BEHAVIOR_TURN_JOURNAL_FILENAME",
    "BehaviorCommitResult",
    "BehaviorRecoveryReport",
    "BehaviorStateSnapshot",
    "BehaviorStateStore",
    "BehaviorTurnJournalRecord",
    "BehaviorVersionConflictError",
    "ensure_behavior_state_schema",
]
