"""SQLite-backed ConversationSessionPort owning per-save history.db."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.chat_history.behavior_state_store import ensure_behavior_state_schema
from core.chat_history.models import (
    CompactCheckpoint,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
    MemoryMode,
    OutfitState,
    TruncateReport,
    TurnNode,
    build_compact_summary_message,
    extract_summary_body,
    is_compact_summary_message,
    is_omitted_history_summary,
    normalize_memory_mode,
    rollback_memory_for_timeline,
    strip_internal_message_keys,
    turn_node_from_message,
)
from core.chat_history.ports import resolve_registered_session_store
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    CandidateHit,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryRepository,
    MemoryScopeFilter,
)
from sdk.adapters.session import ConversationSessionPort
from sdk.adapters.storage import BackendKind, BackendStatus

logger = logging.getLogger(__name__)

HISTORY_DB_FILENAME = "history.db"
SESSION_SCHEMA_VERSION = "1"

_META_SCHEMA_VERSION = "schema_version"
_META_MEMORY_MODE = "memory_mode"
_META_MEMORY_MODE_EXPLICIT = "memory_mode_explicit"
_META_MEMORY_MODE_START_SEQ = "memory_mode_start_seq"
_META_AUTO_OUTFIT_SWITCH = "auto_outfit_switch"
_META_LEGACY_MIGRATED = "legacy_migrated"
_META_LEGACY_ERROR = "legacy_migration_error"

_SESSION_DDL = """
CREATE TABLE IF NOT EXISTS session_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id TEXT NOT NULL DEFAULT 'main',
    turn_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    speaker TEXT NOT NULL DEFAULT '',
    raw_message_json TEXT NOT NULL,
    rendered_html TEXT NOT NULL DEFAULT '',
    plain_text TEXT NOT NULL DEFAULT '',
    voice_id TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'user',
    outfit_snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_turns_branch_seq
    ON turns(branch_id, seq);

CREATE TABLE IF NOT EXISTS compact_checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id TEXT NOT NULL DEFAULT 'main',
    up_to_seq INTEGER NOT NULL,
    rolling_summary TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_branch_seq
    ON compact_checkpoints(branch_id, up_to_seq DESC, checkpoint_id DESC);

CREATE TABLE IF NOT EXISTS outfit_states (
    character_name TEXT PRIMARY KEY,
    active_group TEXT NOT NULL DEFAULT '',
    locked INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL DEFAULT 0
);
"""


def canonical_session_id_for_dir(session_dir: str | Path) -> str:
    """Compute a deterministic SHA-256 session_id matching conversation_library._id."""
    resolved = Path(session_dir).resolve(strict=False)
    normalized = os.path.normcase(str(resolved))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _serialize_outfit_snapshot(snapshot: Mapping[str, OutfitState]) -> str:
    payload = {
        cname: {
            "character_name": state.character_name,
            "active_group": state.active_group,
            "locked": bool(state.locked),
            "updated_at_ms": int(state.updated_at_ms),
        }
        for cname, state in snapshot.items()
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialize_outfit_snapshot(raw: str | None) -> dict[str, OutfitState]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    out: dict[str, OutfitState] = {}
    for key, item in parsed.items():
        if isinstance(item, Mapping):
            cname = str(item.get("character_name") or key or "").strip()
            if not cname:
                continue
            out[cname] = OutfitState(
                character_name=cname,
                active_group=str(item.get("active_group") or ""),
                locked=bool(item.get("locked", False)),
                updated_at_ms=int(item.get("updated_at_ms") or 0),
            )
        elif isinstance(item, str):
            cname = str(key or "").strip()
            if cname:
                out[cname] = OutfitState(character_name=cname, active_group=item)
    return out


class _SessionSaveMemoryRepo:
    """Narrow MemoryRepository facade over the session's embedded SqliteHybridStore."""

    def __init__(self, store: SqliteHybridStore) -> None:
        self._store = store

    def upsert(self, record: MemoryRecord) -> str:
        return self._store.upsert(record)

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._store.get(memory_id)

    def search_candidates(self, query: MemoryCandidateQuery) -> Sequence[CandidateHit]:
        return self._store.search_candidates(query)

    def expand_entities(
        self,
        entities: Sequence[str],
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 10,
    ) -> Sequence[MemoryRecord]:
        return self._store.expand_entities(entities, scope_filter, limit=limit)

    def list_by_scope(
        self,
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 200,
    ) -> Sequence[MemoryRecord]:
        return self._store.list_by_scope(scope_filter, limit=limit)

    def record_recall(self, memory_ids: Sequence[str], *, recalled_at: float) -> int:
        return self._store.record_recall(memory_ids, recalled_at=recalled_at)

    def rollback_after_turn(
        self, session_id: str, turn_seq: int, *, protected_turn_seqs: Sequence[int] = (),
    ) -> int:
        return self._store.rollback_after_turn(session_id, turn_seq, protected_turn_seqs=protected_turn_seqs)

    def set_pinned(self, memory_id: str, pinned: bool) -> bool:
        return self._store.set_pinned(memory_id, pinned)

    def delete(self, memory_id: str) -> bool:
        return self._store.delete(memory_id)


def _longest_suffix_prefix_overlap(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> int:
    """Return largest k > 0 such that existing[-k:] == incoming[:k]."""
    max_k = min(len(existing), len(incoming))
    for k in range(max_k, 0, -1):
        if list(existing[-k:]) == list(incoming[:k]):
            return k
    return 0


def durable_history_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        strip_internal_message_keys(m)
        for m in messages
        if isinstance(m, Mapping)
        and m.get("role") != "system"
        and not is_compact_summary_message(m)
    ]


def legacy_journal_overlap(
    existing: Sequence[Mapping[str, Any]],
    pending: Sequence[Mapping[str, Any]],
    snapshot: Sequence[Mapping[str, Any]],
) -> int:
    """Match an old dual-written journal from the last saved snapshot onward."""
    overlap = _longest_suffix_prefix_overlap(existing, pending)
    if list(existing[:len(snapshot)]) != list(snapshot):
        return overlap

    # The old writer committed to SQLite before appending to .tmp. The
    # journal can match the start of the DB tail even if the DB is ahead.
    starts = [len(snapshot)]
    if snapshot:
        starts.append(len(snapshot) - 1)
    for start in starts:
        matched = 0
        for saved, journaled in zip(existing[start:], pending):
            if saved != journaled:
                break
            matched += 1
        if start == len(snapshot) or matched > 1:
            overlap = max(overlap, matched)
    return overlap


def read_legacy_history_journal(path: Path) -> list[Any]:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        return json.loads("[" + raw.rstrip(",\n\r") + "]")
    except ValueError:
        # Legacy writers appended a JSON object per line. After a crash,
        # recover complete records while ignoring only the torn last line.
        lines = raw.splitlines()
        return [json.loads(line.strip().rstrip(",")) for line in lines[:-1]]


class SqliteSessionStore:
    """Thread-safe SQLite implementation of ConversationSessionPort backed by history.db."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        session_id: str | None = None,
        shared_memory_rollback: Callable[..., int] | None = None,
        max_pool_size: int = 4,
        name: str | None = None,
    ) -> None:
        raw_str = str(db_path)
        if raw_str == ":memory:":
            self._db_path: Path | None = None
            resolved_session_id = str(session_id or "sqlite-memory-session").strip()
        else:
            candidate = Path(db_path)
            if candidate.suffix.lower() != ".db":
                candidate = candidate / HISTORY_DB_FILENAME
            self._db_path = candidate
            resolved_session_id = (
                str(session_id).strip()
                if session_id
                else canonical_session_id_for_dir(candidate.parent)
            )

        self._session_id = resolved_session_id
        custom_name = str(name).strip() if name is not None else ""
        self._name = custom_name or f"db.session.{self._session_id[:12]}"
        self._shared_memory_rollback = shared_memory_rollback
        self._write_lock = threading.RLock()
        self._store = SqliteHybridStore(
            ":memory:" if self._db_path is None else self._db_path,
            max_idle_connections=max_pool_size,
            name=f"{self._name}.hybrid",
        )
        self._save_repo = _SessionSaveMemoryRepo(self._store)
        self._closed = False
        self._init_session_schema()
        if self._db_path is not None and self._session_id:
            _register_session_db_path(self._session_id, self._db_path)

    @property
    def name(self) -> str:
        """Logical backend identifier for ``StorageHub`` registration."""
        return self._name

    def status(self) -> BackendStatus:
        """Return session DB health and schema version."""
        with self._write_lock:
            closed = self._closed
        kind: BackendKind = "memory" if self._db_path is None else "sqlite"
        location = ":memory:" if self._db_path is None else str(self._db_path)
        if closed:
            return BackendStatus(
                name=self._name,
                kind=kind,
                location=location,
                healthy=False,
                schema_version=int(SESSION_SCHEMA_VERSION),
                detail="closed",
            )
        inner = self._store.status()
        return BackendStatus(
            name=self._name,
            kind=kind,
            location=location,
            healthy=inner.healthy,
            schema_version=int(SESSION_SCHEMA_VERSION),
            detail=inner.detail,
        )

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def save_memory_repo(self) -> MemoryRepository:
        return self._save_repo

    @property
    def shared_memory_rollback(self) -> Callable[..., int] | None:
        return self._shared_memory_rollback

    @shared_memory_rollback.setter
    def shared_memory_rollback(self, callback: Callable[..., int] | None) -> None:
        self._shared_memory_rollback = callback

    def _init_session_schema(self) -> None:
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                conn.executescript(_SESSION_DDL)
                ensure_behavior_state_schema(conn)
                conn.execute(
                    "INSERT OR IGNORE INTO session_meta(key, value) VALUES (?, ?)",
                    (_META_SCHEMA_VERSION, SESSION_SCHEMA_VERSION),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO session_meta(key, value) VALUES (?, ?)",
                    (_META_AUTO_OUTFIT_SWITCH, "1"),
                )
                conn.commit()

    def _get_meta(self, key: str) -> str | None:
        with self._store._borrow_conn() as conn:
            row = conn.execute(
                "SELECT value FROM session_meta WHERE key = ?",
                (str(key),),
            ).fetchone()
            return str(row["value"]) if row is not None else None

    def _set_meta(self, key: str, value: str) -> None:
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                conn.execute(
                    "INSERT INTO session_meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(key), str(value)),
                )
                conn.commit()

    @staticmethod
    def _sys_prompt_key(branch_id: str) -> str:
        b = str(branch_id or "main").strip() or "main"
        return f"system_prompt:{b}"

    def get_system_prompt(self, *, branch_id: str = "main") -> str | None:
        return self._get_meta(self._sys_prompt_key(branch_id))

    def set_system_prompt(self, prompt: str, *, branch_id: str = "main") -> None:
        self._set_meta(self._sys_prompt_key(branch_id), str(prompt))

    @staticmethod
    def _row_to_turn(row: Any) -> TurnNode:
        try:
            raw_msg = json.loads(row["raw_message_json"] or "{}")
        except (TypeError, ValueError):
            raw_msg = {}
        if not isinstance(raw_msg, dict):
            raw_msg = {}
        try:
            raw_attachments = json.loads(row["attachments_json"] or "[]")
        except (TypeError, ValueError):
            raw_attachments = []
        attachments = (
            tuple(dict(a) for a in raw_attachments if isinstance(a, Mapping))
            if isinstance(raw_attachments, list)
            else ()
        )
        return TurnNode(
            seq=int(row["seq"]),
            branch_id=str(row["branch_id"] or "main"),
            turn_id=str(row["turn_id"] or ""),
            role=str(row["role"] or ""),
            speaker=str(row["speaker"] or ""),
            raw_message=raw_msg,
            rendered_html=str(row["rendered_html"] or ""),
            plain_text=str(row["plain_text"] or ""),
            voice_id=str(row["voice_id"] or ""),
            attachments=attachments,
            source=str(row["source"] or "user"),
            outfit_snapshot=_deserialize_outfit_snapshot(row["outfit_snapshot_json"]),
            created_at_ms=int(row["created_at_ms"] or 0),
        )

    def _read_outfits_conn(self, conn: Any) -> dict[str, OutfitState]:
        rows = conn.execute(
            "SELECT character_name, active_group, locked, updated_at_ms "
            "FROM outfit_states ORDER BY character_name ASC"
        ).fetchall()
        return {
            str(r["character_name"]): OutfitState(
                character_name=str(r["character_name"]),
                active_group=str(r["active_group"] or ""),
                locked=bool(r["locked"]),
                updated_at_ms=int(r["updated_at_ms"] or 0),
            )
            for r in rows
        }

    def _write_outfits_conn(self, conn: Any, outfits: Mapping[str, OutfitState]) -> None:
        conn.execute("DELETE FROM outfit_states")
        for cname, state in outfits.items():
            clean_name = str(cname or state.character_name or "").strip()
            if not clean_name:
                continue
            conn.execute(
                "INSERT INTO outfit_states(character_name, active_group, locked, updated_at_ms) "
                "VALUES (?, ?, ?, ?)",
                (
                    clean_name,
                    str(state.active_group or ""),
                    1 if state.locked else 0,
                    int(state.updated_at_ms),
                ),
            )

    def append_turn(self, turn: TurnNode) -> TurnNode:
        branch_id = str(turn.branch_id or "main").strip() or "main"
        role = str(turn.role or "").strip()
        if not role:
            raise ValueError("TurnNode.role is required")
        now_ms = int(turn.created_at_ms) if turn.created_at_ms > 0 else int(time.time() * 1000)
        clean_raw = strip_internal_message_keys(turn.raw_message)
        attachments = tuple(copy.deepcopy(dict(a)) for a in turn.attachments)

        with self._write_lock:
            with self._store._borrow_conn() as conn:
                current_outfits = self._read_outfits_conn(conn)
                if turn.outfit_snapshot:
                    for char_name, state in turn.outfit_snapshot.items():
                        cname = str(char_name or state.character_name or "").strip()
                        if cname:
                            current_outfits[cname] = OutfitState(
                                character_name=cname,
                                active_group=str(state.active_group or ""),
                                locked=bool(state.locked),
                                updated_at_ms=int(state.updated_at_ms or now_ms),
                            )
                    self._write_outfits_conn(conn, current_outfits)

                cur = conn.execute(
                    """
                    INSERT INTO turns(
                        branch_id, turn_id, role, speaker, raw_message_json,
                        rendered_html, plain_text, voice_id, attachments_json,
                        source, outfit_snapshot_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        branch_id,
                        str(turn.turn_id or ""),
                        role,
                        str(turn.speaker or ""),
                        json.dumps(clean_raw, ensure_ascii=False, separators=(",", ":")),
                        str(turn.rendered_html or ""),
                        str(turn.plain_text or ""),
                        str(turn.voice_id or ""),
                        json.dumps(list(attachments), ensure_ascii=False, separators=(",", ":")),
                        str(turn.source or role),
                        _serialize_outfit_snapshot(current_outfits),
                        now_ms,
                    ),
                )
                seq = int(cur.lastrowid or 0)
                conn.commit()

        return replace(
            turn,
            seq=seq,
            branch_id=branch_id,
            raw_message=clean_raw,
            attachments=attachments,
            outfit_snapshot=current_outfits,
            created_at_ms=now_ms,
        )

    def append_raw_message(
        self,
        message: Mapping[str, Any],
        *,
        branch_id: str = "main",
        outfit_snapshot: Mapping[str, OutfitState] | None = None,
    ) -> TurnNode:
        b = str(branch_id or "main").strip() or "main"
        if str(message.get("role") or "") == "system":
            self.set_system_prompt(str(message.get("content") or ""), branch_id=b)
            return TurnNode(
                seq=0,
                branch_id=b,
                role="system",
                raw_message=strip_internal_message_keys(message),
                source="system",
                created_at_ms=int(time.time() * 1000),
            )
        node = turn_node_from_message(
            message,
            branch_id=b,
            outfit_snapshot=outfit_snapshot,
        )
        return self.append_turn(node)

    def replace_turns(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        branch_id: str = "main",
    ) -> Sequence[TurnNode]:
        return self.sync_messages(messages, branch_id=branch_id)

    def sync_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        branch_id: str = "main",
    ) -> Sequence[TurnNode]:
        """Synchronize runtime messages with SQLite without clobbering pre-compact turns."""
        b = str(branch_id or "main").strip() or "main"
        with self._write_lock:
            non_system: list[dict[str, Any]] = []
            for raw in messages:
                if not isinstance(raw, Mapping):
                    continue
                if raw.get("role") == "system":
                    self.set_system_prompt(str(raw.get("content") or ""), branch_id=b)
                    continue
                non_system.append(copy.deepcopy(dict(raw)))

            summary_idx = -1
            for idx, item in enumerate(non_system):
                if is_compact_summary_message(item):
                    summary_idx = idx

            if summary_idx >= 0:
                existing_branch = self.list_turns(branch_id=b)
                if existing_branch:
                    # An LLM window is a projection, including when its tail
                    # was trimmed again for a smaller context. Never replace
                    # journaled turns or their sequence numbers with it.
                    return existing_branch

                summary_msg = non_system[summary_idx]
                body = extract_summary_body(str(summary_msg.get("content") or ""))
                if body and not is_omitted_history_summary(body):
                    # A legacy JSON export may only contain the old summary
                    # and its tail, with no raw prefix available to import.
                    self.add_compact_checkpoint(up_to_seq=0, rolling_summary=body, branch_id=b)
                for item in non_system[summary_idx + 1 :]:
                    self.append_raw_message(item, branch_id=b)
                return self.list_turns(branch_id=b)

            clean_incoming = [strip_internal_message_keys(m) for m in non_system]
            existing_branch = list(self.list_turns(branch_id=b))
            existing_raw = [dict(t.raw_message) for t in existing_branch]

            if existing_raw == clean_incoming:
                return tuple(existing_branch)

            if (
                len(clean_incoming) < len(existing_raw)
                and existing_raw[: len(clean_incoming)] == clean_incoming
            ):
                cutoff = existing_branch[len(clean_incoming) - 1].seq if clean_incoming else 0
                self.truncate_after(cutoff, branch_id=b)
                return self.list_turns(branch_id=b)

            if (
                len(clean_incoming) > len(existing_raw)
                and clean_incoming[: len(existing_raw)] == existing_raw
            ):
                for extra in clean_incoming[len(existing_raw) :]:
                    self.append_raw_message(extra, branch_id=b)
                return self.list_turns(branch_id=b)

            with self._store._borrow_conn() as conn:
                conn.execute("DELETE FROM turns WHERE branch_id = ?", (b,))
                conn.execute("DELETE FROM compact_checkpoints WHERE branch_id = ?", (b,))
                conn.commit()
            for item in clean_incoming:
                self.append_raw_message(item, branch_id=b)
            return self.list_turns(branch_id=b)

    def list_turns(
        self,
        *,
        branch_id: str = "main",
        after_seq: int = 0,
        up_to_seq: int | None = None,
    ) -> Sequence[TurnNode]:
        b = str(branch_id or "main").strip() or "main"
        low = int(after_seq)
        with self._store._borrow_conn() as conn:
            if up_to_seq is None:
                rows = conn.execute(
                    "SELECT * FROM turns WHERE branch_id = ? AND seq > ? ORDER BY seq ASC",
                    (b, low),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM turns WHERE branch_id = ? AND seq > ? AND seq <= ? ORDER BY seq ASC",
                    (b, low, int(up_to_seq)),
                ).fetchall()
        return tuple(self._row_to_turn(r) for r in rows)

    def truncate_after(
        self,
        seq: int,
        *,
        branch_id: str = "main",
    ) -> TruncateReport:
        cutoff = max(0, int(seq))
        b = str(branch_id or "main").strip() or "main"
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                protected = tuple(
                    int(row["seq"])
                    for row in conn.execute(
                        "SELECT seq FROM turns WHERE branch_id != ? AND seq > ?",
                        (b, cutoff),
                    )
                )
                cur_turns = conn.execute(
                    "DELETE FROM turns WHERE branch_id = ? AND seq > ?",
                    (b, cutoff),
                )
                deleted_turns = int(cur_turns.rowcount or 0)

                if cutoff == 0:
                    cur_cp = conn.execute(
                        "DELETE FROM compact_checkpoints WHERE branch_id = ?",
                        (b,),
                    )
                else:
                    cur_cp = conn.execute(
                        "DELETE FROM compact_checkpoints WHERE branch_id = ? AND up_to_seq > ?",
                        (b, cutoff),
                    )
                deleted_checkpoints = int(cur_cp.rowcount or 0)
                conn.execute(
                    "DELETE FROM session_state_snapshots WHERE branch_id = ? AND turn_seq > ?",
                    (b, cutoff),
                )

                latest_row = conn.execute(
                    "SELECT outfit_snapshot_json FROM turns "
                    "WHERE branch_id = ? AND seq <= ? ORDER BY seq DESC LIMIT 1",
                    (b, cutoff),
                ).fetchone()
                if latest_row is not None:
                    restored_outfits = _deserialize_outfit_snapshot(
                        latest_row["outfit_snapshot_json"]
                    )
                else:
                    restored_outfits = {}
                self._write_outfits_conn(conn, restored_outfits)
                conn.commit()

            rolled_back_save = self._save_repo.rollback_after_turn(
                self._session_id, cutoff, protected_turn_seqs=protected,
            )

        rolled_back_shared = 0
        if self._shared_memory_rollback is not None:
            rolled_back_shared = rollback_memory_for_timeline(
                self._shared_memory_rollback, self._session_id, cutoff, protected,
            )

        return TruncateReport(
            kept_up_to_seq=cutoff,
            deleted_turns=deleted_turns,
            deleted_checkpoints=deleted_checkpoints,
            rolled_back_save_memories=rolled_back_save,
            rolled_back_shared_memories=rolled_back_shared,
            restored_outfits=restored_outfits,
        )

    def clear(self, *, branch_id: str | None = None) -> None:
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                if branch_id is None:
                    conn.execute("DELETE FROM turns")
                    conn.execute("DELETE FROM compact_checkpoints")
                    conn.execute("DELETE FROM outfit_states")
                    conn.execute(
                        "DELETE FROM session_meta WHERE key LIKE 'system_prompt:%'"
                    )
                    conn.execute("DELETE FROM memories")
                    conn.execute("DELETE FROM session_state_snapshots WHERE turn_seq > 0")
                else:
                    b = str(branch_id or "main").strip() or "main"
                    conn.execute("DELETE FROM turns WHERE branch_id = ?", (b,))
                    conn.execute("DELETE FROM compact_checkpoints WHERE branch_id = ?", (b,))
                    conn.execute(
                        "DELETE FROM session_state_snapshots WHERE branch_id = ? AND turn_seq > 0",
                        (b,),
                    )
                    conn.execute(
                        "DELETE FROM session_meta WHERE key = ?",
                        (self._sys_prompt_key(b),),
                    )
                    if b == "main":
                        conn.execute("DELETE FROM outfit_states")
                conn.commit()
        if branch_id is None and self._shared_memory_rollback is not None:
            self._shared_memory_rollback(self._session_id, 0)

    def add_compact_checkpoint(
        self,
        *,
        up_to_seq: int,
        rolling_summary: str,
        branch_id: str = "main",
        created_at_ms: int | None = None,
    ) -> CompactCheckpoint:
        b = str(branch_id or "main").strip() or "main"
        anchor = max(0, int(up_to_seq))
        body = extract_summary_body(rolling_summary)
        if not body:
            raise ValueError("CompactCheckpoint.rolling_summary cannot be empty")
        ts_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO compact_checkpoints(branch_id, up_to_seq, rolling_summary, created_at_ms) "
                    "VALUES (?, ?, ?, ?)",
                    (b, anchor, body, ts_ms),
                )
                cp_id = int(cur.lastrowid or 0)
                conn.commit()
        return CompactCheckpoint(
            checkpoint_id=cp_id,
            branch_id=b,
            up_to_seq=anchor,
            rolling_summary=body,
            created_at_ms=ts_ms,
        )

    def get_active_compact_checkpoint(
        self,
        *,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> CompactCheckpoint | None:
        b = str(branch_id or "main").strip() or "main"
        with self._store._borrow_conn() as conn:
            if max_seq is None:
                row = conn.execute(
                    "SELECT checkpoint_id, branch_id, up_to_seq, rolling_summary, created_at_ms "
                    "FROM compact_checkpoints WHERE branch_id = ? "
                    "ORDER BY up_to_seq DESC, checkpoint_id DESC LIMIT 1",
                    (b,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT checkpoint_id, branch_id, up_to_seq, rolling_summary, created_at_ms "
                    "FROM compact_checkpoints WHERE branch_id = ? AND up_to_seq <= ? "
                    "ORDER BY up_to_seq DESC, checkpoint_id DESC LIMIT 1",
                    (b, int(max_seq)),
                ).fetchone()
        if row is None:
            return None
        return CompactCheckpoint(
            checkpoint_id=int(row["checkpoint_id"]),
            branch_id=str(row["branch_id"]),
            up_to_seq=int(row["up_to_seq"]),
            rolling_summary=str(row["rolling_summary"]),
            created_at_ms=int(row["created_at_ms"] or 0),
        )

    def list_compact_checkpoints(
        self,
        *,
        branch_id: str = "main",
    ) -> Sequence[CompactCheckpoint]:
        b = str(branch_id or "main").strip() or "main"
        with self._store._borrow_conn() as conn:
            rows = conn.execute(
                "SELECT checkpoint_id, branch_id, up_to_seq, rolling_summary, created_at_ms "
                "FROM compact_checkpoints WHERE branch_id = ? "
                "ORDER BY up_to_seq ASC, checkpoint_id ASC",
                (b,),
            ).fetchall()
        return tuple(
            CompactCheckpoint(
                checkpoint_id=int(r["checkpoint_id"]),
                branch_id=str(r["branch_id"]),
                up_to_seq=int(r["up_to_seq"]),
                rolling_summary=str(r["rolling_summary"]),
                created_at_ms=int(r["created_at_ms"] or 0),
            )
            for r in rows
        )

    def build_active_llm_messages(
        self,
        *,
        system_prompt: str | None = None,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        b = str(branch_id or "main").strip() or "main"
        resolved_system = (
            system_prompt
            if system_prompt is not None
            else self.get_system_prompt(branch_id=b)
        )
        cp = self.get_active_compact_checkpoint(branch_id=b, max_seq=max_seq)
        after = cp.up_to_seq if cp is not None else 0
        turns = self.list_turns(branch_id=b, after_seq=after, up_to_seq=max_seq)

        assembled: list[dict[str, Any]] = []
        if resolved_system is not None:
            assembled.append({"role": "system", "content": resolved_system})
        if cp is not None:
            assembled.append(
                build_compact_summary_message(
                    cp.rolling_summary,
                    up_to_seq=cp.up_to_seq,
                )
            )
        for turn in turns:
            assembled.append(copy.deepcopy(dict(turn.raw_message)))
        return assembled

    def build_full_raw_messages(
        self,
        *,
        include_system: bool = True,
        branch_id: str = "main",
    ) -> list[dict[str, Any]]:
        """Return 100% uncompacted raw messages for UI history and active.json mirror."""
        b = str(branch_id or "main").strip() or "main"
        result: list[dict[str, Any]] = []
        sys_prompt = self.get_system_prompt(branch_id=b)
        if include_system and sys_prompt is not None:
            result.append({"role": "system", "content": sys_prompt})
        for turn in self.list_turns(branch_id=b):
            result.append(copy.deepcopy(dict(turn.raw_message)))
        return result

    def get_memory_mode(self) -> MemoryMode:
        raw = self._get_meta(_META_MEMORY_MODE)
        # Older databases seeded "shared" even when nobody chose a mode.
        uses_default = raw is None or (
            raw == MEMORY_MODE_SHARED and self._get_meta(_META_MEMORY_MODE_EXPLICIT) != "1"
        )
        if uses_default and self._db_path is not None:
            session_dir = self._db_path.parent
            if (session_dir / "story-v2.json").is_file() or (
                session_dir / "story-prompt-binding.json"
            ).is_file():
                return MEMORY_MODE_ISOLATED
        return normalize_memory_mode(raw)

    def set_memory_mode(self, mode: MemoryMode) -> None:
        normalized = normalize_memory_mode(mode)
        with self._write_lock:
            changed = self.get_memory_mode() != normalized
            with self._store._borrow_conn() as conn:
                prefs = [(_META_MEMORY_MODE, normalized), (_META_MEMORY_MODE_EXPLICIT, "1")]
                if changed:
                    # Do not extract old dialogue again under a different scope.
                    last_seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM turns").fetchone()[0])
                    previous = conn.execute(
                        "SELECT value FROM session_meta WHERE key = ?", (_META_MEMORY_MODE_START_SEQ,),
                    ).fetchone()
                    boundary = max(last_seq, int(previous[0]) if previous is not None else 0)
                    if boundary:
                        prefs.append((_META_MEMORY_MODE_START_SEQ, str(boundary)))
                conn.executemany(
                    "INSERT INTO session_meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    prefs,
                )
                conn.commit()

    def get_memory_mode_start_seq(self) -> int | None:
        stored = self._get_meta(_META_MEMORY_MODE_START_SEQ)
        return int(stored) if stored else None

    def get_auto_outfit_switch(self) -> bool:
        raw = self._get_meta(_META_AUTO_OUTFIT_SWITCH)
        if raw is None:
            return True
        return str(raw).strip().lower() not in {"0", "false", "no", "off"}

    def set_auto_outfit_switch(self, enabled: bool) -> None:
        self._set_meta(_META_AUTO_OUTFIT_SWITCH, "1" if enabled else "0")

    def get_outfit_state(self, character_name: str) -> OutfitState | None:
        cname = str(character_name or "").strip()
        if not cname:
            return None
        with self._store._borrow_conn() as conn:
            row = conn.execute(
                "SELECT character_name, active_group, locked, updated_at_ms "
                "FROM outfit_states WHERE character_name = ?",
                (cname,),
            ).fetchone()
        if row is None:
            return None
        return OutfitState(
            character_name=str(row["character_name"]),
            active_group=str(row["active_group"] or ""),
            locked=bool(row["locked"]),
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )

    def list_outfit_states(self) -> Mapping[str, OutfitState]:
        with self._store._borrow_conn() as conn:
            return self._read_outfits_conn(conn)

    def set_outfit_state(self, state: OutfitState) -> None:
        cname = str(state.character_name or "").strip()
        if not cname:
            raise ValueError("OutfitState.character_name is required")
        now_ms = int(state.updated_at_ms) if state.updated_at_ms > 0 else int(time.time() * 1000)
        normalized = OutfitState(
            character_name=cname,
            active_group=str(state.active_group or ""),
            locked=bool(state.locked),
            updated_at_ms=now_ms,
        )
        with self._write_lock:
            with self._store._borrow_conn() as conn:
                conn.execute(
                    "INSERT INTO outfit_states(character_name, active_group, locked, updated_at_ms) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(character_name) DO UPDATE SET "
                    "active_group = excluded.active_group, "
                    "locked = excluded.locked, "
                    "updated_at_ms = excluded.updated_at_ms",
                    (
                        cname,
                        normalized.active_group,
                        1 if normalized.locked else 0,
                        normalized.updated_at_ms,
                    ),
                )
                latest_row = conn.execute(
                    "SELECT seq, outfit_snapshot_json FROM turns ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                if latest_row is not None:
                    snap = _deserialize_outfit_snapshot(latest_row["outfit_snapshot_json"])
                    snap[cname] = normalized
                    conn.execute(
                        "UPDATE turns SET outfit_snapshot_json = ? WHERE seq = ?",
                        (_serialize_outfit_snapshot(snap), int(latest_row["seq"])),
                    )
                conn.commit()

    def migrate_from_legacy_files(
        self,
        active_json_path: str | Path,
        *,
        branch_id: str = "main",
    ) -> bool:
        """Import legacy active.json + .tmp into SQLite non-destructively.

        Returns True when `.tmp` was merged and should be written back + unlinked
        by the caller; never marks corrupt JSON as migrated so repairs can retry.
        """
        b = str(branch_id or "main").strip() or "main"
        active_path = Path(active_json_path)
        tmp_path = Path(str(active_path) + ".tmp")
        merged_tmp = False

        with self._write_lock:
            migrated_flag = self._get_meta(_META_LEGACY_MIGRATED) == "1"
            existing_turns = list(self.list_turns(branch_id=b))

            if not migrated_flag and active_path.exists():
                try:
                    loaded = json.loads(active_path.read_text(encoding="utf-8"))
                    if not isinstance(loaded, list):
                        raise ValueError("legacy active history JSON root must be a list")
                except Exception as exc:
                    self._set_meta(_META_LEGACY_ERROR, f"{type(exc).__name__}: {exc}")
                    logger.warning(
                        "Legacy chat history migration deferred due to unreadable %s: %s",
                        active_path,
                        exc,
                    )
                else:
                    if not existing_turns:
                        self.sync_messages(loaded, branch_id=b)
                    else:
                        # Resume an interrupted import if the database already
                        # contains a prefix of the legacy snapshot.
                        original = durable_history_messages(loaded)
                        imported = [dict(t.raw_message) for t in existing_turns]
                        if original[:len(imported)] == imported:
                            for item in original[len(imported):]:
                                self.append_raw_message(item, branch_id=b)
                    self._set_meta(_META_LEGACY_MIGRATED, "1")
                    self._set_meta(_META_LEGACY_ERROR, "")
                    existing_turns = list(self.list_turns(branch_id=b))
            elif not migrated_flag and not active_path.exists() and not tmp_path.exists():
                self._set_meta(_META_LEGACY_MIGRATED, "1")
                self._set_meta(_META_LEGACY_ERROR, "")

            if tmp_path.exists():
                try:
                    size = tmp_path.stat().st_size
                except OSError:
                    size = 0
                if size > 0:
                    try:
                        tmp_messages = read_legacy_history_journal(tmp_path)
                    except Exception as exc:
                        logger.warning(
                            "Temporary chat journal %s could not be decoded; preserving file: %s",
                            tmp_path,
                            exc,
                        )
                    else:
                        clean_tmp = durable_history_messages(tmp_messages)
                        existing_raw = [dict(t.raw_message) for t in existing_turns]
                        snapshot: list[dict[str, Any]] = []
                        if active_path.exists():
                            try:
                                active = json.loads(active_path.read_text(encoding="utf-8"))
                                if not isinstance(active, list):
                                    return False
                                snapshot = durable_history_messages(active)
                            except (OSError, ValueError):
                                return False
                        overlap = legacy_journal_overlap(existing_raw, clean_tmp, snapshot)
                        to_append = clean_tmp[overlap:]
                        for msg in to_append:
                            self.append_raw_message(msg, branch_id=b)
                        if not active_path.exists():
                            self._set_meta(_META_LEGACY_MIGRATED, "1")
                            self._set_meta(_META_LEGACY_ERROR, "")
                        merged_tmp = True
                else:
                    merged_tmp = True

        return merged_tmp

    def get_migration_error(self) -> str:
        return self._get_meta(_META_LEGACY_ERROR) or ""

    def is_legacy_migrated(self) -> bool:
        return self._get_meta(_META_LEGACY_MIGRATED) == "1"

    def close(self) -> None:
        with self._write_lock:
            if self._closed:
                return
            self._closed = True
            self._store.close()
        _evict_open_store_instance(self)


_open_stores_lock = threading.RLock()
_open_stores: dict[str, ConversationSessionPort] = {}
_known_session_db_paths: dict[str, Path] = {}
_default_shared_rollback_lock = threading.Lock()
_default_shared_rollback: Callable[..., int] | None = None


def _register_session_db_path(session_id: str, db_path: Path) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _open_stores_lock:
        _known_session_db_paths[sid] = db_path


def set_default_shared_memory_rollback(
    callback: Callable[..., int] | None,
) -> None:
    """Register the default shared-memory rollback hook used by opened session stores."""
    global _default_shared_rollback
    with _default_shared_rollback_lock:
        _default_shared_rollback = callback
    with _open_stores_lock:
        for store in _open_stores.values():
            if isinstance(store, SqliteSessionStore) and store.shared_memory_rollback is None:
                store.shared_memory_rollback = callback


def get_default_shared_memory_rollback() -> Callable[..., int] | None:
    with _default_shared_rollback_lock:
        return _default_shared_rollback


def _canonical_store_key(session_dir: Path) -> str:
    return os.path.normcase(str(session_dir.resolve(strict=False)))


def _evict_open_store_instance(instance: ConversationSessionPort) -> None:
    with _open_stores_lock:
        stale = [k for k, v in _open_stores.items() if v is instance]
        for k in stale:
            _open_stores.pop(k, None)


def open_session_store_for_dir(
    session_dir: str | Path,
    *,
    shared_memory_rollback: Callable[..., int] | None = None,
) -> ConversationSessionPort:
    """Return a cached or newly opened ConversationSessionPort for session_dir."""
    directory = Path(session_dir)
    key = _canonical_store_key(directory)
    rollback = (
        shared_memory_rollback
        if shared_memory_rollback is not None
        else get_default_shared_memory_rollback()
    )
    with _open_stores_lock:
        existing = _open_stores.get(key)
        if existing is not None:
            if isinstance(existing, SqliteSessionStore) and rollback is not None and existing.shared_memory_rollback is None:
                existing.shared_memory_rollback = rollback
            return existing

        registered = resolve_registered_session_store(str(directory))
        if registered is not None:
            _open_stores[key] = registered
            return registered

        created = SqliteSessionStore(
            directory / HISTORY_DB_FILENAME,
            session_id=canonical_session_id_for_dir(directory),
            shared_memory_rollback=rollback,
        )
        _open_stores[key] = created
        return created


def peek_open_session_store_for_dir(session_dir: str | Path) -> ConversationSessionPort | None:
    key = _canonical_store_key(Path(session_dir))
    with _open_stores_lock:
        return _open_stores.get(key)


def close_session_store_for_dir(session_dir: str | Path) -> None:
    """Close and evict any cached session store for session_dir before file deletion."""
    key = _canonical_store_key(Path(session_dir))
    with _open_stores_lock:
        store = _open_stores.pop(key, None)
    if store is not None:
        store.close()


def close_all_session_stores() -> None:
    """Close all open session stores in this process."""
    with _open_stores_lock:
        stores = list(_open_stores.values())
        _open_stores.clear()
    for store in stores:
        store.close()


def _discover_session_db_path(session_id: str) -> Path | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _open_stores_lock:
        known = _known_session_db_paths.get(sid)
    if known is not None:
        return known
    data_dir = Path.cwd() / "data"
    for root in (data_dir / "chat_history", data_dir / "conversations"):
        if not root.is_dir():
            continue
        try:
            resolved_root = root.resolve()
            for child in root.iterdir():
                if not child.is_dir() or not child.resolve().is_relative_to(resolved_root):
                    continue
                if canonical_session_id_for_dir(child) == sid:
                    db_path = child / HISTORY_DB_FILENAME
                    _register_session_db_path(sid, db_path)
                    return db_path
            for db_candidate in root.rglob(HISTORY_DB_FILENAME):
                parent = db_candidate.parent
                if not parent.resolve().is_relative_to(resolved_root):
                    continue
                if canonical_session_id_for_dir(parent) == sid:
                    _register_session_db_path(sid, db_candidate)
                    return db_candidate
        except OSError:
            continue
    return None


def register_session_db_directory(session_dir: str | Path) -> None:
    """Register a server-approved save before a separate runtime opens it."""
    directory = Path(session_dir).resolve()
    _register_session_db_path(canonical_session_id_for_dir(directory), directory / HISTORY_DB_FILENAME)


@contextmanager
def borrow_session_store_for_dir(
    session_dir: str | Path,
    *,
    create_if_dir_exists: bool = False,
) -> Iterator[ConversationSessionPort | None]:
    """Yield an open or transient ConversationSessionPort for session_dir without leaking handles."""
    directory = Path(session_dir)
    cached = peek_open_session_store_for_dir(directory)
    if cached is not None:
        yield cached
        return
    registered = resolve_registered_session_store(str(directory))
    if registered is not None:
        yield registered
        return
    db_path = directory / HISTORY_DB_FILENAME
    sid = canonical_session_id_for_dir(directory)
    if not db_path.is_file() and not (create_if_dir_exists and directory.is_dir()):
        yield None
        return
    _register_session_db_path(sid, db_path)
    transient = SqliteSessionStore(
        db_path,
        session_id=sid,
        shared_memory_rollback=get_default_shared_memory_rollback(),
        max_pool_size=1,
    )
    try:
        yield transient
    finally:
        transient.close()


@contextmanager
def borrow_session_store_by_id(
    session_id: str,
    *,
    create_if_dir_exists: bool = False,
) -> Iterator[ConversationSessionPort | None]:
    """Yield an open or transient ConversationSessionPort for session_id without leaking handles."""
    sid = str(session_id or "").strip()
    if not sid:
        yield None
        return
    with _open_stores_lock:
        for store in _open_stores.values():
            if getattr(store, "session_id", "") == sid:
                yield store
                return
    db_path = _discover_session_db_path(sid)
    if db_path is None:
        yield None
        return
    if not db_path.is_file() and not (create_if_dir_exists and db_path.parent.is_dir()):
        yield None
        return
    transient = SqliteSessionStore(
        db_path,
        session_id=sid,
        shared_memory_rollback=get_default_shared_memory_rollback(),
        max_pool_size=1,
    )
    try:
        yield transient
    finally:
        transient.close()


def _default_memory_mode_for_dir(directory: Path, raw_mode: str | None = None) -> MemoryMode:
    if raw_mode is not None and str(raw_mode).strip():
        return normalize_memory_mode(raw_mode)
    if (directory / "story-v2.json").is_file() or (
        directory / "story-prompt-binding.json"
    ).is_file():
        return MEMORY_MODE_ISOLATED
    return normalize_memory_mode(raw_mode)


def read_session_preferences_readonly(session_dir: str | Path) -> dict[str, Any]:
    """Read memoryMode, autoOutfitSwitch, and outfit states without leaking SQLite handles."""
    import sqlite3

    directory = Path(session_dir)
    sid = canonical_session_id_for_dir(directory)
    cached = peek_open_session_store_for_dir(directory)
    if cached is not None:
        outfits_map = cached.list_outfit_states()
        return {
            "sessionId": sid,
            "memoryMode": cached.get_memory_mode(),
            "autoOutfitSwitch": bool(cached.get_auto_outfit_switch()),
            "outfits": {
                cname: {
                    "characterName": item.character_name,
                    "activeGroup": item.active_group,
                    "locked": bool(item.locked),
                    "updatedAtMs": int(item.updated_at_ms),
                }
                for cname, item in outfits_map.items()
            },
        }

    db_file = directory / HISTORY_DB_FILENAME
    if directory.is_dir():
        _register_session_db_path(sid, db_file)
    if not db_file.is_file():
        return {
            "sessionId": sid,
            "memoryMode": _default_memory_mode_for_dir(directory, None),
            "autoOutfitSwitch": True,
            "outfits": {},
        }

    conn = sqlite3.connect(str(db_file), timeout=2.0)
    try:
        conn.row_factory = sqlite3.Row
        meta_rows = conn.execute(
            "SELECT key, value FROM session_meta WHERE key IN (?, ?, ?)",
            (_META_MEMORY_MODE, _META_MEMORY_MODE_EXPLICIT, _META_AUTO_OUTFIT_SWITCH),
        ).fetchall()
        meta = {str(r["key"]): str(r["value"]) for r in meta_rows}
        raw_mode = meta.get(_META_MEMORY_MODE)
        if raw_mode == MEMORY_MODE_SHARED and meta.get(_META_MEMORY_MODE_EXPLICIT) != "1":
            raw_mode = None
        raw_auto = meta.get(_META_AUTO_OUTFIT_SWITCH)
        auto_switch = (
            True
            if raw_auto is None
            else str(raw_auto).strip().lower() not in {"0", "false", "no", "off"}
        )
        outfit_rows = conn.execute(
            "SELECT character_name, active_group, locked, updated_at_ms "
            "FROM outfit_states ORDER BY character_name ASC"
        ).fetchall()
        outfits = {
            str(r["character_name"]): {
                "characterName": str(r["character_name"]),
                "activeGroup": str(r["active_group"] or ""),
                "locked": bool(r["locked"]),
                "updatedAtMs": int(r["updated_at_ms"] or 0),
            }
            for r in outfit_rows
            if str(r["character_name"] or "").strip()
        }
        return {
            "sessionId": sid,
            "memoryMode": _default_memory_mode_for_dir(directory, raw_mode),
            "autoOutfitSwitch": auto_switch,
            "outfits": outfits,
        }
    except sqlite3.Error:
        return {
            "sessionId": sid,
            "memoryMode": _default_memory_mode_for_dir(directory, None),
            "autoOutfitSwitch": True,
            "outfits": {},
        }
    finally:
        conn.close()


def read_full_raw_messages_readonly(
    session_dir: str | Path,
    *,
    branch_id: str = "main",
    include_system: bool = True,
) -> list[dict[str, Any]] | None:
    """Read full uncompacted raw messages from history.db without holding file handles."""
    import sqlite3

    directory = Path(session_dir)
    cached = peek_open_session_store_for_dir(directory)
    if cached is not None and hasattr(cached, "build_full_raw_messages"):
        return cached.build_full_raw_messages(  # type: ignore[no-any-return]
            include_system=include_system,
            branch_id=branch_id,
        )
    db_file = directory / HISTORY_DB_FILENAME
    if not db_file.is_file():
        return None
    b = str(branch_id or "main").strip() or "main"
    try:
        conn = sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        messages: list[dict[str, Any]] = []
        if include_system:
            meta_row = conn.execute(
                "SELECT value FROM session_meta WHERE key = ?",
                (f"system_prompt:{b}",),
            ).fetchone()
            if meta_row is not None:
                messages.append({"role": "system", "content": str(meta_row["value"])})
        rows = conn.execute(
            "SELECT raw_message_json FROM turns WHERE branch_id = ? ORDER BY seq ASC",
            (b,),
        ).fetchall()
        for row in rows:
            try:
                parsed = json.loads(row["raw_message_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                messages.append(parsed)
        return messages
    except sqlite3.Error:
        return None
    finally:
        conn.close()


__all__ = [
    "HISTORY_DB_FILENAME",
    "SESSION_SCHEMA_VERSION",
    "SqliteSessionStore",
    "borrow_session_store_by_id",
    "borrow_session_store_for_dir",
    "canonical_session_id_for_dir",
    "close_all_session_stores",
    "close_session_store_for_dir",
    "get_default_shared_memory_rollback",
    "open_session_store_for_dir",
    "peek_open_session_store_for_dir",
    "read_full_raw_messages_readonly",
    "read_session_preferences_readonly",
    "register_session_db_directory",
    "set_default_shared_memory_rollback",
]
