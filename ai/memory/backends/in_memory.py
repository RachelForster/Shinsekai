"""Pure in-memory reference adapters for contract tests and fast sandboxes."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from core.vector_store.fts_tokenizer import build_fts_match_query, tokenize_for_fts
from core.vector_store.sqlite_hybrid_store import normalize_vector
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    CandidateHit,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryScopeFilter,
    ReadinessStatus,
    VectorSliceEntry,
    VectorSliceHit,
)


class DeterministicHashEmbedder:
    """Fast deterministic n-gram hash embedder implementing EmbeddingProvider."""

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = max(8, int(dimensions))

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _encode_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dimensions, dtype=np.float32)
        tokens = tokenize_for_fts(text).split()
        if not tokens:
            tokens = [str(text or "").strip().casefold() or "__empty__"]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimensions
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign
            idx2 = int.from_bytes(digest[8:12], "little") % self._dimensions
            sign2 = 1.0 if (digest[12] & 1) == 0 else -1.0
            vec[idx2] += 0.5 * sign2
        norm = float(np.linalg.norm(vec))
        if norm > 1e-12:
            vec /= norm
        return vec

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode_one(text)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        return np.vstack([self._encode_one(text) for text in texts]).astype(np.float32)

    def status(self) -> ReadinessStatus:
        return ReadinessStatus(state="ready", model_cached=True, message="deterministic")


def _parse_or_terms(keyword_query: str) -> tuple[str, ...]:
    expr = build_fts_match_query(keyword_query)
    if not expr:
        return ()
    parts = [part.strip() for part in expr.split(" OR ")]
    cleaned: list[str] = []
    for part in parts:
        if len(part) >= 2 and part.startswith('"') and part.endswith('"'):
            cleaned.append(part[1:-1].replace('""', '"'))
    return tuple(cleaned)


class InMemoryMemoryRepository:
    """Thread-safe pure in-memory reference implementation of MemoryRepository."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._order: dict[str, int] = {}
        self._seq = 0

    @staticmethod
    def _matches_filter(record: MemoryRecord, f: MemoryScopeFilter) -> bool:
        if f.scopes and record.scope not in f.scopes:
            return False
        if f.owner_ids and record.owner_id not in f.owner_ids:
            return False
        if f.session_id is not None and record.source_session_id != f.session_id:
            return False
        if (
            f.max_turn_seq is not None
            and record.source_turn_seq is not None
            and record.source_turn_seq > int(f.max_turn_seq)
        ):
            return False
        if not f.include_superseded and record.superseded_by is not None:
            return False
        effective_pinned = record.pinned or record.scope == SCOPE_CHAR_CANON
        if f.only_pinned is True and not effective_pinned:
            return False
        if f.only_pinned is False and effective_pinned:
            return False
        ts = record.event_at if record.event_at is not None else record.created_at
        if f.event_from is not None and ts < float(f.event_from):
            return False
        if f.event_to is not None and ts > float(f.event_to):
            return False
        return True

    def upsert(self, record: MemoryRecord) -> str:
        memory_id = str(record.id or "").strip() or str(uuid.uuid4())
        now = time.time()
        created_at = float(record.created_at) if record.created_at > 0 else now
        last_recalled = float(record.last_recalled_at) if record.last_recalled_at > 0 else created_at
        detail_text = str(record.detail_text or "").strip()
        if not detail_text:
            raise ValueError("detail_text is required")
        gist_text = str(record.gist_text or "").strip() or detail_text
        scope = str(record.scope or "").strip()
        owner_id = str(record.owner_id or "").strip()
        if not scope or not owner_id:
            raise ValueError("scope and owner_id are required")
        slot_key = str(record.slot_key or "").strip()
        topics = tuple(dict.fromkeys(str(t).strip() for t in record.topic_tags if str(t).strip()))
        entities = tuple(dict.fromkeys(str(e).strip() for e in record.entities if str(e).strip()))
        vec = normalize_vector(record.embedding)

        with self._lock:
            existing = self._records.get(memory_id)
            if vec is None and existing is not None:
                vec = normalize_vector(existing.embedding)

            if slot_key and record.superseded_by is None:
                for other_id, other in list(self._records.items()):
                    if (
                        other_id != memory_id
                        and other.scope == scope
                        and other.owner_id == owner_id
                        and other.slot_key == slot_key
                        and other.superseded_by is None
                        and (
                            scope != "save_isolated"
                            or not record.source_session_id
                            or other.source_session_id == record.source_session_id
                        )
                    ):
                        self._records[other_id] = replace(other, superseded_by=memory_id)

            if memory_id not in self._order:
                self._seq += 1
                self._order[memory_id] = self._seq

            self._records[memory_id] = replace(
                record,
                id=memory_id,
                scope=scope,
                owner_id=owner_id,
                slot_key=slot_key,
                kind=str(record.kind or "episodic"),
                detail_text=detail_text,
                gist_text=gist_text,
                topic_tags=topics,
                entities=entities,
                importance=float(max(0.0, min(1.0, float(record.importance)))),
                pinned=bool(record.pinned),
                created_at=created_at,
                last_recalled_at=last_recalled,
                recall_count=int(record.recall_count),
                source_session_id=str(record.source_session_id or ""),
                embedding=vec,
            )
        return memory_id

    def get(self, memory_id: str) -> MemoryRecord | None:
        mid = str(memory_id or "").strip()
        with self._lock:
            return self._records.get(mid)

    def search_candidates(self, query: MemoryCandidateQuery) -> Sequence[CandidateHit]:
        limit = max(1, int(query.limit))
        q_vecs = [
            vec
            for raw in query.query_vectors
            if (vec := normalize_vector(raw)) is not None
        ]
        terms = _parse_or_terms(query.keyword_query)

        with self._lock:
            candidates = [
                rec
                for rec in self._records.values()
                if self._matches_filter(rec, query.scope_filter)
            ]
            candidates.sort(
                key=lambda r: (r.created_at, self._order.get(r.id, 0)),
                reverse=True,
            )

        if not candidates:
            return ()

        if not q_vecs and not terms:
            return tuple(
                CandidateHit(record=replace(r, embedding=None), vector_score=0.0, fts_score=0.0)
                for r in candidates[:limit]
            )

        scored: list[tuple[float, CandidateHit]] = []
        for rec in candidates:
            v_score = 0.0
            has_vec = rec.embedding is not None
            if q_vecs and has_vec:
                r_vec = normalize_vector(rec.embedding)
                if r_vec is not None:
                    sims = [float(np.dot(r_vec, qv)) for qv in q_vecs if qv.shape == r_vec.shape]
                    if sims:
                        v_score = max(sims)

            f_score = 0.0
            if terms:
                doc_tokens = set(
                    tokenize_for_fts(
                        " ".join(
                            (
                                rec.detail_text,
                                rec.gist_text,
                                " ".join(rec.topic_tags),
                                " ".join(rec.entities),
                            )
                        )
                    ).split()
                )
                hit_count = sum(1 for term in terms if term in doc_tokens)
                if hit_count > 0:
                    f_score = hit_count / (1.0 + hit_count)

            if q_vecs and v_score <= 0.0 and f_score <= 0.0 and not has_vec:
                continue
            if not q_vecs and f_score <= 0.0:
                continue

            combined = (max(0.0, v_score) * 0.8 + f_score * 0.2) if q_vecs else f_score
            scored.append(
                (
                    combined,
                    CandidateHit(
                        record=replace(rec, embedding=None),
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
        norm_targets = {str(e).strip().casefold() for e in entities if str(e).strip()}
        if not norm_targets:
            return ()
        bounded = max(1, int(limit))
        matched: list[tuple[int, MemoryRecord]] = []
        with self._lock:
            for rec in self._records.values():
                if not self._matches_filter(rec, scope_filter):
                    continue
                rec_ents = {e.casefold() for e in rec.entities}
                overlap = len(norm_targets & rec_ents)
                if overlap > 0:
                    matched.append((overlap, replace(rec, embedding=None)))
        matched.sort(
            key=lambda item: (item[0], item[1].importance, item[1].created_at),
            reverse=True,
        )
        return tuple(rec for _cnt, rec in matched[:bounded])

    def list_by_scope(
        self,
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 200,
    ) -> Sequence[MemoryRecord]:
        bounded = max(1, int(limit))
        with self._lock:
            rows = [
                replace(rec, embedding=None)
                for rec in self._records.values()
                if self._matches_filter(rec, scope_filter)
            ]
            rows.sort(
                key=lambda r: (1 if r.pinned else 0, r.created_at, self._order.get(r.id, 0)),
                reverse=True,
            )
        return tuple(rows[:bounded])

    def record_recall(self, memory_ids: Sequence[str], *, recalled_at: float) -> int:
        ts = float(recalled_at)
        updated = 0
        with self._lock:
            for raw_id in dict.fromkeys(str(m).strip() for m in memory_ids if str(m).strip()):
                rec = self._records.get(raw_id)
                if rec is None:
                    continue
                self._records[raw_id] = replace(
                    rec,
                    recall_count=rec.recall_count + 1,
                    last_recalled_at=max(rec.last_recalled_at, ts),
                )
                updated += 1
        return updated

    def _splice_and_delete(self, deleting_ids: set[str]) -> int:
        if not deleting_ids:
            return 0
        deleting_map = {
            mid: self._records[mid].superseded_by
            for mid in deleting_ids
            if mid in self._records
        }

        def _surviving_target(start: str | None) -> str | None:
            curr = start
            seen: set[str] = set()
            while curr is not None and curr in deleting_map:
                if curr in seen:
                    return None
                seen.add(curr)
                curr = deleting_map[curr]
            return curr

        for mid, rec in list(self._records.items()):
            if mid not in deleting_map and rec.superseded_by in deleting_map:
                self._records[mid] = replace(
                    rec,
                    superseded_by=_surviving_target(rec.superseded_by),
                )

        removed = 0
        for mid in deleting_map:
            if self._records.pop(mid, None) is not None:
                self._order.pop(mid, None)
                removed += 1
        return removed

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        sid = str(session_id or "").strip()
        if not sid:
            return 0
        cutoff = int(turn_seq)
        with self._lock:
            to_delete = {
                mid
                for mid, rec in self._records.items()
                if rec.source_session_id == sid
                and rec.source_turn_seq is not None
                and rec.source_turn_seq > cutoff
                and not rec.pinned
                and rec.scope != SCOPE_CHAR_CANON
            }
            return self._splice_and_delete(to_delete)

    def set_pinned(self, memory_id: str, pinned: bool) -> bool:
        mid = str(memory_id or "").strip()
        with self._lock:
            rec = self._records.get(mid)
            if rec is None:
                return False
            self._records[mid] = replace(rec, pinned=bool(pinned))
            return True

    def delete(self, memory_id: str) -> bool:
        mid = str(memory_id or "").strip()
        if not mid:
            return False
        with self._lock:
            if mid not in self._records:
                return False
            return self._splice_and_delete({mid}) > 0


class InMemoryStaticVectorStore:
    """Pure in-memory implementation of StaticVectorStorePort."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._slices: dict[tuple[str, str], VectorSliceEntry] = {}

    def upsert_slices(self, entries: Sequence[VectorSliceEntry]) -> int:
        now = time.time()
        count = 0
        with self._lock:
            for entry in entries:
                ns = str(entry.namespace or "").strip()
                sid = str(entry.id or "").strip() or str(uuid.uuid4())
                scope_id = str(entry.scope_id or "").strip()
                text = str(entry.text or "").strip()
                if not ns or not scope_id or not text:
                    raise ValueError("namespace, scope_id, and text are required")
                existing = self._slices.get((ns, sid))
                vec = normalize_vector(entry.embedding)
                if vec is None and existing is not None:
                    vec = normalize_vector(existing.embedding)
                self._slices[(ns, sid)] = VectorSliceEntry(
                    id=sid,
                    namespace=ns,
                    scope_id=scope_id,
                    text=text,
                    metadata=dict(entry.metadata or {}),
                    created_at=float(entry.created_at) if entry.created_at > 0 else now,
                    embedding=vec,
                )
                count += 1
        return count

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
        scopes = {str(s).strip() for s in scope_ids if str(s).strip()}
        if not ns or not scopes:
            return ()
        q_vec = normalize_vector(query_vector)
        terms = _parse_or_terms(keyword_query)
        bounded = max(1, int(limit))

        hits: list[VectorSliceHit] = []
        with self._lock:
            entries = [
                e
                for (entry_ns, _sid), e in self._slices.items()
                if entry_ns == ns and e.scope_id in scopes
            ]

        for entry in entries:
            if metadata_filter and not all(entry.metadata.get(k) == v for k, v in metadata_filter.items()):
                continue
            e_vec = normalize_vector(entry.embedding)
            v_score = (
                float(np.dot(e_vec, q_vec))
                if q_vec is not None and e_vec is not None and e_vec.shape == q_vec.shape
                else 0.0
            )
            f_score = 0.0
            if terms:
                doc_tokens = set(tokenize_for_fts(entry.text).split())
                matched = sum(1 for t in terms if t in doc_tokens)
                if matched > 0:
                    f_score = matched / (1.0 + matched)
            if q_vec is not None:
                if e_vec is None and f_score <= 0.0:
                    continue
                score = v_score if f_score <= 0.0 else max(v_score, 0.85 * v_score + 0.15 * f_score)
            else:
                if f_score <= 0.0:
                    continue
                score = f_score
            hits.append(
                VectorSliceHit(
                    entry=replace(entry, embedding=None),
                    vector_score=v_score,
                    fts_score=f_score,
                    score=score,
                )
            )
        hits.sort(key=lambda h: (h.score, h.vector_score, h.fts_score, h.entry.created_at), reverse=True)
        return tuple(hits[:bounded])

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
        with self._lock:
            items = [
                replace(e, embedding=None)
                for (entry_ns, _sid), e in self._slices.items()
                if entry_ns == ns
                and (scope_id is None or e.scope_id == str(scope_id).strip())
                and (not metadata_filter or all(e.metadata.get(k) == v for k, v in metadata_filter.items()))
            ]
        items.sort(key=lambda e: e.created_at)
        start = max(0, int(offset))
        return tuple(items[start : start + max(1, int(limit))])

    def count_by_scope(self, *, namespace: str) -> Mapping[str, int]:
        ns = str(namespace or "").strip()
        counts: dict[str, int] = {}
        with self._lock:
            for (entry_ns, _sid), e in self._slices.items():
                if entry_ns == ns and e.scope_id:
                    counts[e.scope_id] = counts.get(e.scope_id, 0) + 1
        return counts

    def delete_slice(self, *, namespace: str, slice_id: str) -> bool:
        key = (str(namespace or "").strip(), str(slice_id or "").strip())
        with self._lock:
            return self._slices.pop(key, None) is not None

    def delete_scope(self, *, namespace: str, scope_id: str) -> int:
        ns = str(namespace or "").strip()
        sc = str(scope_id or "").strip()
        removed = 0
        with self._lock:
            for key in [k for k, e in self._slices.items() if k[0] == ns and e.scope_id == sc]:
                self._slices.pop(key, None)
                removed += 1
        return removed
