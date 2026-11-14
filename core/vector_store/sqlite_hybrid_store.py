"""SQLite (WAL + FTS5) + NumPy hybrid store for memories and static slices."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from core.vector_store.fts_tokenizer import build_fts_match_query, tokenize_for_fts
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    CandidateHit,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryScopeFilter,
    VectorSliceEntry,
    VectorSliceHit,
)


def normalize_vector(vector: Any) -> np.ndarray | None:
    """Convert a 1D array-like or float32 buffer into an L2-normalized float32 ndarray."""
    if vector is None:
        return None
    if isinstance(vector, (bytes, bytearray, memoryview)):
        if len(vector) == 0:
            return None
        arr = np.frombuffer(vector, dtype=np.float32).copy()
    else:
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return None
    norm = float(np.linalg.norm(arr))
    if norm > 1e-12:
        arr = arr / norm
    return np.ascontiguousarray(arr, dtype=np.float32)


def to_normalized_float32_blob(vector: Any) -> bytes | None:
    """Serialize an array-like vector as normalized little-endian float32 bytes."""
    arr = normalize_vector(vector)
    return None if arr is None else arr.tobytes()


def from_float32_blob(blob: bytes | None) -> np.ndarray | None:
    """Zero-copy/lightweight float32 ndarray view over a SQLite BLOB."""
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32).copy()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    slot_key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'episodic',
    detail_text TEXT NOT NULL,
    gist_text TEXT NOT NULL DEFAULT '',
    topic_tags_json TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    event_at REAL,
    last_recalled_at REAL NOT NULL,
    recall_count INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    source_session_id TEXT NOT NULL DEFAULT '',
    source_turn_seq INTEGER,
    embedding BLOB
);

CREATE INDEX IF NOT EXISTS idx_memories_scope_owner
    ON memories(scope, owner_id, superseded_by, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_slot
    ON memories(scope, owner_id, slot_key)
    WHERE slot_key != '' AND superseded_by IS NULL;

CREATE INDEX IF NOT EXISTS idx_memories_session_turn
    ON memories(source_session_id, source_turn_seq)
    WHERE source_session_id != '';

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    fts_tokens,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL,
    entity_norm TEXT NOT NULL,
    scope TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    PRIMARY KEY (memory_id, entity_norm)
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_lookup
    ON memory_entities(entity_norm, scope, owner_id);

CREATE TABLE IF NOT EXISTS vector_entries (
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    embedding BLOB,
    PRIMARY KEY (namespace, id)
);

CREATE INDEX IF NOT EXISTS idx_vector_entries_ns_scope
    ON vector_entries(namespace, scope_id, created_at ASC);

CREATE VIRTUAL TABLE IF NOT EXISTS vector_entries_fts USING fts5(
    namespace UNINDEXED,
    slice_id UNINDEXED,
    scope_id UNINDEXED,
    fts_tokens,
    tokenize='unicode61'
);
"""


class _SliceMatrixCacheEntry:
    __slots__ = ("epoch", "data_version", "entries", "matrix", "has_vectors")

    def __init__(
        self,
        *,
        epoch: int,
        data_version: int,
        entries: tuple[VectorSliceEntry, ...],
        matrix: np.ndarray | None,
        has_vectors: np.ndarray,
    ) -> None:
        self.epoch = epoch
        self.data_version = data_version
        self.entries = entries
        self.matrix = matrix
        self.has_vectors = has_vectors


class SqliteHybridStore:
    """Thread-safe SQLite (WAL + FTS5) + NumPy hybrid engine."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._is_memory = str(db_path) == ":memory:"
        if self._is_memory:
            self._db_target = f"file:shinsekai_mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._use_uri = True
            self._path: Path | None = None
        else:
            resolved = Path(db_path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._db_target = str(resolved)
            self._use_uri = False
            self._path = resolved

        self._lock = threading.RLock()
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._anchor_conn: sqlite3.Connection | None = None
        self._epoch = 0
        self._slice_cache: dict[tuple[str, str], _SliceMatrixCacheEntry] = {}
        self._closed = False

        if self._is_memory:
            # Keep shared in-memory DB alive across thread connections until close().
            self._anchor_conn = self._open_connection()
        with self._lock:
            conn = self._conn()
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    @property
    def db_path(self) -> Path | None:
        return self._path

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_target,
            uri=self._use_uri,
            timeout=5.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _conn(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("SqliteHybridStore is closed")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open_connection()
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    def _data_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA data_version").fetchone()
        return int(row[0]) if row is not None else 0

    def _bump_epoch(self) -> None:
        self._epoch += 1
        self._slice_cache.clear()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._slice_cache.clear()
            conns = list(self._connections)
            self._connections.clear()
            if self._anchor_conn is not None:
                conns.append(self._anchor_conn)
                self._anchor_conn = None
        seen: set[int] = set()
        for conn in conns:
            if id(conn) in seen:
                continue
            seen.add(id(conn))
            try:
                conn.close()
            except Exception:
                pass
        if hasattr(self._local, "conn"):
            delattr(self._local, "conn")

    # ------------------------------------------------------------------
    # Metadata helpers (migration flags, schema info)
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?",
            (str(key),),
        ).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO store_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # MemoryRepository implementation
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_memory_record(
        row: sqlite3.Row,
        *,
        include_embedding: bool = False,
    ) -> MemoryRecord:
        try:
            topics = tuple(str(x) for x in json.loads(row["topic_tags_json"] or "[]") if str(x).strip())
        except Exception:
            topics = ()
        try:
            entities = tuple(str(x) for x in json.loads(row["entities_json"] or "[]") if str(x).strip())
        except Exception:
            entities = ()
        return MemoryRecord(
            id=str(row["id"]),
            scope=str(row["scope"]),
            owner_id=str(row["owner_id"]),
            slot_key=str(row["slot_key"] or ""),
            kind=str(row["kind"] or "episodic"),
            detail_text=str(row["detail_text"] or ""),
            gist_text=str(row["gist_text"] or ""),
            topic_tags=topics,
            entities=entities,
            importance=float(row["importance"]),
            pinned=bool(row["pinned"]),
            created_at=float(row["created_at"]),
            event_at=None if row["event_at"] is None else float(row["event_at"]),
            last_recalled_at=float(row["last_recalled_at"]),
            recall_count=int(row["recall_count"]),
            superseded_by=None if row["superseded_by"] is None else str(row["superseded_by"]),
            source_session_id=str(row["source_session_id"] or ""),
            source_turn_seq=None if row["source_turn_seq"] is None else int(row["source_turn_seq"]),
            embedding=from_float32_blob(row["embedding"]) if include_embedding else None,
        )

    @staticmethod
    def _memory_fts_source(record: MemoryRecord) -> str:
        parts = [
            record.detail_text,
            record.gist_text,
            " ".join(record.topic_tags),
            " ".join(record.entities),
        ]
        return " ".join(p for p in parts if p)

    @staticmethod
    def _build_scope_where(
        scope_filter: MemoryScopeFilter,
        *,
        table_alias: str = "m",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        p = f"{table_alias}." if table_alias else ""

        if scope_filter.scopes:
            placeholders = ",".join("?" for _ in scope_filter.scopes)
            clauses.append(f"{p}scope IN ({placeholders})")
            params.extend(scope_filter.scopes)

        if scope_filter.owner_ids:
            placeholders = ",".join("?" for _ in scope_filter.owner_ids)
            clauses.append(f"{p}owner_id IN ({placeholders})")
            params.extend(scope_filter.owner_ids)

        if scope_filter.session_id is not None:
            clauses.append(f"{p}source_session_id = ?")
            params.append(scope_filter.session_id)

        if scope_filter.max_turn_seq is not None:
            clauses.append(f"({p}source_turn_seq IS NULL OR {p}source_turn_seq <= ?)")
            params.append(int(scope_filter.max_turn_seq))

        if not scope_filter.include_superseded:
            clauses.append(f"{p}superseded_by IS NULL")

        if scope_filter.only_pinned is True:
            clauses.append(f"({p}pinned = 1 OR {p}scope = ?)")
            params.append(SCOPE_CHAR_CANON)
        elif scope_filter.only_pinned is False:
            clauses.append(f"({p}pinned = 0 AND {p}scope != ?)")
            params.append(SCOPE_CHAR_CANON)

        if scope_filter.event_from is not None:
            clauses.append(f"COALESCE({p}event_at, {p}created_at) >= ?")
            params.append(float(scope_filter.event_from))

        if scope_filter.event_to is not None:
            clauses.append(f"COALESCE({p}event_at, {p}created_at) <= ?")
            params.append(float(scope_filter.event_to))

        where_sql = " AND ".join(clauses) if clauses else "1=1"
        return where_sql, params

    def upsert(self, record: MemoryRecord) -> str:
        memory_id = str(record.id or "").strip() or str(uuid.uuid4())
        now = time.time()
        created_at = float(record.created_at) if record.created_at > 0 else now
        last_recalled = float(record.last_recalled_at) if record.last_recalled_at > 0 else created_at
        detail_text = str(record.detail_text or "").strip()
        if not detail_text:
            raise ValueError("detail_text is required")
        gist_text = str(record.gist_text or "").strip() or detail_text
        slot_key = str(record.slot_key or "").strip()
        scope = str(record.scope or "").strip()
        owner_id = str(record.owner_id or "").strip()
        if not scope or not owner_id:
            raise ValueError("scope and owner_id are required")

        topics = tuple(dict.fromkeys(str(t).strip() for t in record.topic_tags if str(t).strip()))
        entities = tuple(dict.fromkeys(str(e).strip() for e in record.entities if str(e).strip()))
        blob = to_normalized_float32_blob(record.embedding)

        normalized_record = replace(
            record,
            id=memory_id,
            scope=scope,
            owner_id=owner_id,
            slot_key=slot_key,
            detail_text=detail_text,
            gist_text=gist_text,
            topic_tags=topics,
            entities=entities,
            created_at=created_at,
            last_recalled_at=last_recalled,
        )
        fts_tokens = tokenize_for_fts(self._memory_fts_source(normalized_record))

        with self._lock:
            conn = self._conn()
            with conn:
                if slot_key and normalized_record.superseded_by is None:
                    if normalized_record.source_session_id and scope == "save_isolated":
                        conn.execute(
                            "UPDATE memories SET superseded_by = ? "
                            "WHERE scope = ? AND owner_id = ? AND slot_key = ? "
                            "AND source_session_id = ? AND superseded_by IS NULL AND id != ?",
                            (
                                memory_id,
                                scope,
                                owner_id,
                                slot_key,
                                normalized_record.source_session_id,
                                memory_id,
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE memories SET superseded_by = ? "
                            "WHERE scope = ? AND owner_id = ? AND slot_key = ? "
                            "AND superseded_by IS NULL AND id != ?",
                            (memory_id, scope, owner_id, slot_key, memory_id),
                        )

                conn.execute(
                    """
                    INSERT INTO memories (
                        id, scope, owner_id, slot_key, kind,
                        detail_text, gist_text, topic_tags_json, entities_json,
                        importance, pinned, created_at, event_at,
                        last_recalled_at, recall_count, superseded_by,
                        source_session_id, source_turn_seq, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        scope = excluded.scope,
                        owner_id = excluded.owner_id,
                        slot_key = excluded.slot_key,
                        kind = excluded.kind,
                        detail_text = excluded.detail_text,
                        gist_text = excluded.gist_text,
                        topic_tags_json = excluded.topic_tags_json,
                        entities_json = excluded.entities_json,
                        importance = excluded.importance,
                        pinned = excluded.pinned,
                        created_at = excluded.created_at,
                        event_at = excluded.event_at,
                        last_recalled_at = excluded.last_recalled_at,
                        recall_count = excluded.recall_count,
                        superseded_by = excluded.superseded_by,
                        source_session_id = excluded.source_session_id,
                        source_turn_seq = excluded.source_turn_seq,
                        embedding = COALESCE(excluded.embedding, memories.embedding)
                    """,
                    (
                        memory_id,
                        scope,
                        owner_id,
                        slot_key,
                        str(normalized_record.kind or "episodic"),
                        detail_text,
                        gist_text,
                        json.dumps(topics, ensure_ascii=False),
                        json.dumps(entities, ensure_ascii=False),
                        float(max(0.0, min(1.0, float(normalized_record.importance)))),
                        1 if normalized_record.pinned else 0,
                        created_at,
                        normalized_record.event_at,
                        last_recalled,
                        int(normalized_record.recall_count),
                        normalized_record.superseded_by,
                        str(normalized_record.source_session_id or ""),
                        normalized_record.source_turn_seq,
                        blob,
                    ),
                )

                conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
                if fts_tokens:
                    conn.execute(
                        "INSERT INTO memories_fts(memory_id, fts_tokens) VALUES (?, ?)",
                        (memory_id, fts_tokens),
                    )

                conn.execute("DELETE FROM memory_entities WHERE memory_id = ?", (memory_id,))
                if entities:
                    conn.executemany(
                        "INSERT OR IGNORE INTO memory_entities(memory_id, entity_norm, scope, owner_id) "
                        "VALUES (?, ?, ?, ?)",
                        [(memory_id, ent.casefold(), scope, owner_id) for ent in entities],
                    )
            self._bump_epoch()
        return memory_id

    def get(self, memory_id: str) -> MemoryRecord | None:
        mid = str(memory_id or "").strip()
        if not mid:
            return None
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ?",
            (mid,),
        ).fetchone()
        return None if row is None else self._row_to_memory_record(row, include_embedding=True)

    def search_candidates(self, query: MemoryCandidateQuery) -> Sequence[CandidateHit]:
        limit = max(1, int(query.limit))
        conn = self._conn()
        where_sql, params = self._build_scope_where(query.scope_filter, table_alias="m")

        rows = conn.execute(
            f"SELECT m.* FROM memories m WHERE {where_sql} ORDER BY m.created_at DESC, m.rowid DESC",
            params,
        ).fetchall()
        if not rows:
            return ()

        q_vecs = [
            vec
            for raw in query.query_vectors
            if (vec := normalize_vector(raw)) is not None
        ]
        fts_scores: dict[str, float] = {}
        match_expr = build_fts_match_query(query.keyword_query)
        if match_expr:
            fts_rows = conn.execute(
                f"""
                SELECT f.memory_id, bm25(memories_fts) AS rank_score
                FROM memories_fts f
                JOIN memories m ON m.id = f.memory_id
                WHERE memories_fts MATCH ? AND {where_sql}
                ORDER BY rank_score ASC
                LIMIT ?
                """,
                [match_expr, *params, max(limit * 4, 40)],
            ).fetchall()
            for row in fts_rows:
                raw_bm25 = abs(float(row["rank_score"] or 0.0))
                # SQLite bm25() returns negative scores (more negative = better match).
                fts_scores[str(row["memory_id"])] = raw_bm25 / (1.0 + raw_bm25)

        vec_scores = np.zeros(len(rows), dtype=np.float32)
        if q_vecs:
            target_dim = q_vecs[0].shape[0]
            q_mat = np.vstack([v for v in q_vecs if v.shape[0] == target_dim])
            valid_indices: list[int] = []
            valid_vecs: list[np.ndarray] = []
            for idx, row in enumerate(rows):
                blob = row["embedding"]
                if blob and len(blob) == target_dim * 4:
                    valid_indices.append(idx)
                    valid_vecs.append(np.frombuffer(blob, dtype=np.float32))
            if valid_vecs:
                doc_mat = np.vstack(valid_vecs)
                sims = doc_mat @ q_mat.T  # shape (M, Q)
                max_sims = np.max(sims, axis=1)
                for pos, row_idx in enumerate(valid_indices):
                    vec_scores[row_idx] = float(max_sims[pos])

        if not q_vecs and not match_expr:
            return tuple(
                CandidateHit(record=self._row_to_memory_record(row), vector_score=0.0, fts_score=0.0)
                for row in rows[:limit]
            )

        scored: list[tuple[float, CandidateHit]] = []
        for idx, row in enumerate(rows):
            mid = str(row["id"])
            v_score = float(vec_scores[idx])
            f_score = float(fts_scores.get(mid, 0.0))
            if q_vecs and v_score <= 0.0 and f_score <= 0.0:
                # Still include low/negative cosine candidates only when FTS didn't match if needed,
                # or rank all vector-bearing candidates by cosine similarity.
                if row["embedding"] is None:
                    continue
            elif not q_vecs and f_score <= 0.0:
                continue
            combined = (max(0.0, v_score) * 0.8 + f_score * 0.2) if q_vecs else f_score
            scored.append(
                (
                    combined,
                    CandidateHit(
                        record=self._row_to_memory_record(row),
                        vector_score=v_score,
                        fts_score=f_score,
                    ),
                )
            )

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].vector_score,
                item[1].fts_score,
                item[1].record.created_at,
            ),
            reverse=True,
        )
        return tuple(hit for _score, hit in scored[:limit])

    def expand_entities(
        self,
        entities: Sequence[str],
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 10,
    ) -> Sequence[MemoryRecord]:
        norm_entities = tuple(
            dict.fromkeys(str(e).strip().casefold() for e in entities if str(e).strip())
        )
        if not norm_entities:
            return ()
        bounded_limit = max(1, int(limit))
        where_sql, params = self._build_scope_where(scope_filter, table_alias="m")
        ent_placeholders = ",".join("?" for _ in norm_entities)
        conn = self._conn()
        rows = conn.execute(
            f"""
            SELECT m.*, COUNT(DISTINCT e.entity_norm) AS hit_count
            FROM memory_entities e
            JOIN memories m ON m.id = e.memory_id
            WHERE e.entity_norm IN ({ent_placeholders}) AND {where_sql}
            GROUP BY m.id
            ORDER BY hit_count DESC, m.importance DESC, m.created_at DESC
            LIMIT ?
            """,
            [*norm_entities, *params, bounded_limit],
        ).fetchall()
        return tuple(self._row_to_memory_record(row) for row in rows)

    def list_by_scope(
        self,
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 200,
    ) -> Sequence[MemoryRecord]:
        bounded_limit = max(1, int(limit))
        where_sql, params = self._build_scope_where(scope_filter, table_alias="m")
        conn = self._conn()
        rows = conn.execute(
            f"""
            SELECT m.* FROM memories m
            WHERE {where_sql}
            ORDER BY m.pinned DESC, m.created_at DESC, m.rowid DESC
            LIMIT ?
            """,
            [*params, bounded_limit],
        ).fetchall()
        return tuple(self._row_to_memory_record(row) for row in rows)

    def record_recall(self, memory_ids: Sequence[str], *, recalled_at: float) -> int:
        ids = tuple(dict.fromkeys(str(mid).strip() for mid in memory_ids if str(mid).strip()))
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        ts = float(recalled_at)
        with self._lock:
            conn = self._conn()
            with conn:
                cur = conn.execute(
                    f"""
                    UPDATE memories
                    SET recall_count = recall_count + 1,
                        last_recalled_at = CASE
                            WHEN last_recalled_at > ? THEN last_recalled_at
                            ELSE ?
                        END
                    WHERE id IN ({placeholders})
                    """,
                    [ts, ts, *ids],
                )
            self._bump_epoch()
            return int(cur.rowcount or 0)

    @staticmethod
    def _splice_deleted_supersede_links(
        conn: sqlite3.Connection,
        deleting_map: Mapping[str, str | None],
    ) -> None:
        """Restore or splice superseded_by pointers before deleting a set of IDs."""
        if not deleting_map:
            return
        deleting_ids = set(deleting_map.keys())

        def _resolve_surviving_target(start_id: str) -> str | None:
            curr: str | None = start_id
            visited: set[str] = set()
            while curr is not None and curr in deleting_ids:
                if curr in visited:
                    return None
                visited.add(curr)
                curr = deleting_map.get(curr)
            return curr

        placeholders = ",".join("?" for _ in deleting_ids)
        affected = conn.execute(
            f"SELECT id, superseded_by FROM memories "
            f"WHERE superseded_by IN ({placeholders}) AND id NOT IN ({placeholders})",
            [*deleting_ids, *deleting_ids],
        ).fetchall()
        for row in affected:
            surviving = _resolve_surviving_target(str(row["superseded_by"]))
            conn.execute(
                "UPDATE memories SET superseded_by = ? WHERE id = ?",
                (surviving, str(row["id"])),
            )

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        sid = str(session_id or "").strip()
        if not sid:
            return 0
        cutoff = int(turn_seq)
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                """
                SELECT id, superseded_by FROM memories
                WHERE source_session_id = ?
                  AND source_turn_seq IS NOT NULL
                  AND source_turn_seq > ?
                  AND pinned = 0
                  AND scope != ?
                """,
                (sid, cutoff, SCOPE_CHAR_CANON),
            ).fetchall()
            if not rows:
                return 0
            deleting_map = {
                str(row["id"]): (None if row["superseded_by"] is None else str(row["superseded_by"]))
                for row in rows
            }
            deleting_ids = tuple(deleting_map.keys())
            placeholders = ",".join("?" for _ in deleting_ids)
            with conn:
                self._splice_deleted_supersede_links(conn, deleting_map)
                conn.execute(
                    f"DELETE FROM memories_fts WHERE memory_id IN ({placeholders})",
                    deleting_ids,
                )
                conn.execute(
                    f"DELETE FROM memory_entities WHERE memory_id IN ({placeholders})",
                    deleting_ids,
                )
                cur = conn.execute(
                    f"DELETE FROM memories WHERE id IN ({placeholders})",
                    deleting_ids,
                )
            self._bump_epoch()
            return int(cur.rowcount or 0)

    def set_pinned(self, memory_id: str, pinned: bool) -> bool:
        mid = str(memory_id or "").strip()
        if not mid:
            return False
        with self._lock:
            conn = self._conn()
            with conn:
                cur = conn.execute(
                    "UPDATE memories SET pinned = ? WHERE id = ?",
                    (1 if pinned else 0, mid),
                )
            self._bump_epoch()
            return int(cur.rowcount or 0) > 0

    def delete(self, memory_id: str) -> bool:
        mid = str(memory_id or "").strip()
        if not mid:
            return False
        with self._lock:
            conn = self._conn()
            row = conn.execute(
                "SELECT id, superseded_by FROM memories WHERE id = ?",
                (mid,),
            ).fetchone()
            if row is None:
                return False
            deleting_map = {
                mid: None if row["superseded_by"] is None else str(row["superseded_by"])
            }
            with conn:
                self._splice_deleted_supersede_links(conn, deleting_map)
                conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (mid,))
                conn.execute("DELETE FROM memory_entities WHERE memory_id = ?", (mid,))
                cur = conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
            self._bump_epoch()
            return int(cur.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # StaticVectorStorePort implementation (knowledge + media_asset)
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata_matches(
        metadata: Mapping[str, Any],
        metadata_filter: Mapping[str, Any] | None,
    ) -> bool:
        if not metadata_filter:
            return True
        return all(metadata.get(key) == value for key, value in metadata_filter.items())

    @staticmethod
    def _row_to_slice_entry(
        row: sqlite3.Row,
        *,
        include_embedding: bool = False,
    ) -> VectorSliceEntry:
        try:
            meta = json.loads(row["metadata_json"] or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        return VectorSliceEntry(
            id=str(row["id"]),
            namespace=str(row["namespace"]),
            scope_id=str(row["scope_id"]),
            text=str(row["text"] or ""),
            metadata=meta,
            created_at=float(row["created_at"]),
            embedding=from_float32_blob(row["embedding"]) if include_embedding else None,
        )

    def upsert_slices(self, entries: Sequence[VectorSliceEntry]) -> int:
        if not entries:
            return 0
        now = time.time()
        with self._lock:
            conn = self._conn()
            count = 0
            with conn:
                for entry in entries:
                    ns = str(entry.namespace or "").strip()
                    sid = str(entry.id or "").strip() or str(uuid.uuid4())
                    scope_id = str(entry.scope_id or "").strip()
                    text = str(entry.text or "").strip()
                    if not ns or not scope_id or not text:
                        raise ValueError("namespace, scope_id, and text are required for VectorSliceEntry")
                    created_at = float(entry.created_at) if entry.created_at > 0 else now
                    meta_json = json.dumps(dict(entry.metadata or {}), ensure_ascii=False, sort_keys=True)
                    blob = to_normalized_float32_blob(entry.embedding)
                    fts_tokens = tokenize_for_fts(text)

                    conn.execute(
                        """
                        INSERT INTO vector_entries(
                            namespace, id, scope_id, text, metadata_json, created_at, embedding
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(namespace, id) DO UPDATE SET
                            scope_id = excluded.scope_id,
                            text = excluded.text,
                            metadata_json = excluded.metadata_json,
                            created_at = excluded.created_at,
                            embedding = COALESCE(excluded.embedding, vector_entries.embedding)
                        """,
                        (ns, sid, scope_id, text, meta_json, created_at, blob),
                    )
                    conn.execute(
                        "DELETE FROM vector_entries_fts WHERE namespace = ? AND slice_id = ?",
                        (ns, sid),
                    )
                    if fts_tokens:
                        conn.execute(
                            "INSERT INTO vector_entries_fts(namespace, slice_id, scope_id, fts_tokens) "
                            "VALUES (?, ?, ?, ?)",
                            (ns, sid, scope_id, fts_tokens),
                        )
                    count += 1
            self._bump_epoch()
            return count

    def _get_scope_matrix_cache(
        self,
        conn: sqlite3.Connection,
        namespace: str,
        scope_id: str,
        data_version: int,
    ) -> _SliceMatrixCacheEntry:
        key = (namespace, scope_id)
        with self._lock:
            cached = self._slice_cache.get(key)
            if (
                cached is not None
                and cached.epoch == self._epoch
                and cached.data_version == data_version
            ):
                return cached

        rows = conn.execute(
            "SELECT * FROM vector_entries WHERE namespace = ? AND scope_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (namespace, scope_id),
        ).fetchall()
        entries = tuple(self._row_to_slice_entry(row, include_embedding=False) for row in rows)
        if not rows:
            built = _SliceMatrixCacheEntry(
                epoch=self._epoch,
                data_version=data_version,
                entries=(),
                matrix=None,
                has_vectors=np.zeros(0, dtype=bool),
            )
        else:
            vecs: list[np.ndarray | None] = []
            dim = 0
            for row in rows:
                blob = row["embedding"]
                if blob and len(blob) % 4 == 0 and len(blob) > 0:
                    arr = np.frombuffer(blob, dtype=np.float32)
                    if dim == 0:
                        dim = arr.shape[0]
                    if arr.shape[0] == dim:
                        vecs.append(arr)
                        continue
                vecs.append(None)

            has_vectors = np.array([v is not None for v in vecs], dtype=bool)
            if dim > 0 and np.any(has_vectors):
                matrix = np.zeros((len(rows), dim), dtype=np.float32)
                for idx, v in enumerate(vecs):
                    if v is not None:
                        matrix[idx] = v
            else:
                matrix = None
            built = _SliceMatrixCacheEntry(
                epoch=self._epoch,
                data_version=data_version,
                entries=entries,
                matrix=matrix,
                has_vectors=has_vectors,
            )

        with self._lock:
            self._slice_cache[key] = built
        return built

    def search_slices(
        self,
        *,
        namespace: str,
        scope_ids: Sequence[str],
        query_vector: Any | None = None,
        keyword_query: str = "",
        metadata_filter: Mapping[str, Any] | None = None,
        limit: int = 10,
    ) -> Sequence[VectorSliceHit]:
        ns = str(namespace or "").strip()
        scopes = tuple(dict.fromkeys(str(s).strip() for s in scope_ids if str(s).strip()))
        if not ns or not scopes:
            return ()
        bounded_limit = max(1, int(limit))
        q_vec = normalize_vector(query_vector)

        conn = self._conn()
        dv = self._data_version(conn)

        fts_scores: dict[str, float] = {}
        match_expr = build_fts_match_query(keyword_query)
        if match_expr:
            scope_placeholders = ",".join("?" for _ in scopes)
            fts_rows = conn.execute(
                f"""
                SELECT slice_id, bm25(vector_entries_fts) AS rank_score
                FROM vector_entries_fts
                WHERE vector_entries_fts MATCH ?
                  AND namespace = ?
                  AND scope_id IN ({scope_placeholders})
                ORDER BY rank_score ASC
                LIMIT ?
                """,
                [match_expr, ns, *scopes, max(bounded_limit * 5, 50)],
            ).fetchall()
            for row in fts_rows:
                raw_bm25 = abs(float(row["rank_score"] or 0.0))
                fts_scores[str(row["slice_id"])] = raw_bm25 / (1.0 + raw_bm25)

        hits: list[VectorSliceHit] = []
        for scope_id in scopes:
            cached = self._get_scope_matrix_cache(conn, ns, scope_id, dv)
            if not cached.entries:
                continue
            if (
                q_vec is not None
                and cached.matrix is not None
                and cached.matrix.shape[1] == q_vec.shape[0]
            ):
                sims = cached.matrix @ q_vec
            else:
                sims = None

            for idx, entry in enumerate(cached.entries):
                if not self._metadata_matches(entry.metadata, metadata_filter):
                    continue
                v_score = (
                    float(sims[idx])
                    if sims is not None and bool(cached.has_vectors[idx])
                    else 0.0
                )
                f_score = float(fts_scores.get(entry.id, 0.0))
                if q_vec is not None:
                    if not bool(cached.has_vectors[idx]) and f_score <= 0.0:
                        continue
                    # Preserve high cosine fidelity (needed for semantic dedup threshold ~0.92)
                    # while giving exact keyword matches a gentle tie-breaking lift.
                    final_score = v_score if f_score <= 0.0 else max(v_score, 0.85 * v_score + 0.15 * f_score)
                else:
                    if f_score <= 0.0:
                        continue
                    final_score = f_score
                hits.append(
                    VectorSliceHit(
                        entry=entry,
                        vector_score=v_score,
                        fts_score=f_score,
                        score=final_score,
                    )
                )

        hits.sort(
            key=lambda h: (h.score, h.vector_score, h.fts_score, h.entry.created_at),
            reverse=True,
        )
        return tuple(hits[:bounded_limit])

    def list_slices(
        self,
        *,
        namespace: str,
        scope_id: str | None = None,
        metadata_filter: Mapping[str, Any] | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> Sequence[VectorSliceEntry]:
        ns = str(namespace or "").strip()
        if not ns:
            return ()
        bounded_offset = max(0, int(offset))
        bounded_limit = max(1, int(limit))
        conn = self._conn()

        if metadata_filter:
            if scope_id is not None:
                rows = conn.execute(
                    "SELECT * FROM vector_entries WHERE namespace = ? AND scope_id = ? "
                    "ORDER BY created_at ASC, rowid ASC",
                    (ns, str(scope_id).strip()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM vector_entries WHERE namespace = ? "
                    "ORDER BY created_at ASC, rowid ASC",
                    (ns,),
                ).fetchall()
            filtered = [
                entry
                for row in rows
                if self._metadata_matches(
                    (entry := self._row_to_slice_entry(row)).metadata,
                    metadata_filter,
                )
            ]
            return tuple(filtered[bounded_offset : bounded_offset + bounded_limit])

        if scope_id is not None:
            rows = conn.execute(
                "SELECT * FROM vector_entries WHERE namespace = ? AND scope_id = ? "
                "ORDER BY created_at ASC, rowid ASC LIMIT ? OFFSET ?",
                (ns, str(scope_id).strip(), bounded_limit, bounded_offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vector_entries WHERE namespace = ? "
                "ORDER BY created_at ASC, rowid ASC LIMIT ? OFFSET ?",
                (ns, bounded_limit, bounded_offset),
            ).fetchall()
        return tuple(self._row_to_slice_entry(row) for row in rows)

    def count_by_scope(self, *, namespace: str) -> Mapping[str, int]:
        ns = str(namespace or "").strip()
        if not ns:
            return {}
        conn = self._conn()
        rows = conn.execute(
            "SELECT scope_id, COUNT(*) AS cnt FROM vector_entries "
            "WHERE namespace = ? GROUP BY scope_id",
            (ns,),
        ).fetchall()
        return {
            str(row["scope_id"]): int(row["cnt"])
            for row in rows
            if str(row["scope_id"]).strip()
        }

    def delete_slice(self, *, namespace: str, slice_id: str) -> bool:
        ns = str(namespace or "").strip()
        sid = str(slice_id or "").strip()
        if not ns or not sid:
            return False
        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "DELETE FROM vector_entries_fts WHERE namespace = ? AND slice_id = ?",
                    (ns, sid),
                )
                cur = conn.execute(
                    "DELETE FROM vector_entries WHERE namespace = ? AND id = ?",
                    (ns, sid),
                )
            self._bump_epoch()
            return int(cur.rowcount or 0) > 0

    def delete_scope(self, *, namespace: str, scope_id: str) -> int:
        ns = str(namespace or "").strip()
        sc = str(scope_id or "").strip()
        if not ns or not sc:
            return 0
        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "DELETE FROM vector_entries_fts WHERE namespace = ? AND scope_id = ?",
                    (ns, sc),
                )
                cur = conn.execute(
                    "DELETE FROM vector_entries WHERE namespace = ? AND scope_id = ?",
                    (ns, sc),
                )
            self._bump_epoch()
            return int(cur.rowcount or 0)
