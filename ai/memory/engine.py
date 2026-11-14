"""SOLID hybrid memory engine wiring EmbeddingProvider + MemoryRepository + StaticVectorStorePort."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ai.memory.backends.in_memory import InMemoryStaticVectorStore
from ai.memory.backends.onnx_embedder import OnnxMiniLmEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.constants import EMBEDDING_DIMS, MEMORY_STORE_FILENAME
from ai.memory.migration import migrate_legacy_memory_qdrant
from ai.memory.ports import (
    resolve_registered_embedding_provider,
    resolve_registered_memory_repository,
)
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    NAMESPACE_MEDIA_ASSET,
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    EmbeddingProvider,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryRepository,
    MemoryScopeFilter,
    StaticVectorStorePort,
    VectorSliceEntry,
)

_embedder_lock = threading.Lock()
_shared_embedders: dict[str, EmbeddingProvider] = {}
_MEDIA_PREFIX = "__shinsekai_media__:"


def get_shared_onnx_embedder(
    snapshot_path: str | Path,
    *,
    dimensions: int = EMBEDDING_DIMS,
) -> EmbeddingProvider:
    """Return a process-wide shared ONNX embedder (or custom registered provider)."""
    registered = resolve_registered_embedding_provider()
    if registered is not None:
        return registered

    key = str(Path(snapshot_path))
    with _embedder_lock:
        existing = _shared_embedders.get(key)
        if existing is not None:
            return existing
        created = OnnxMiniLmEmbedder(snapshot_path, dimensions=dimensions)
        _shared_embedders[key] = created
        return created


def clear_shared_onnx_embedders() -> None:
    """Clear cached shared embedder instances (for tests)."""
    with _embedder_lock:
        _shared_embedders.clear()


def resolve_memory_write_target(agent_id: str | None) -> tuple[str, str]:
    """Map user/character identifier to canonical (scope, owner_id) write target."""
    normalized = str(agent_id or "").strip()
    if normalized.lower() in {"", "user", "__self__"}:
        return (SCOPE_SELF_PUBLIC, "__self__")
    return (SCOPE_CHAR_CROSS_SAVE, normalized)


def resolve_memory_read_filter(agent_id: str | None) -> MemoryScopeFilter:
    """Map user/character identifier to orthogonal scope filter for reads/searches."""
    normalized = str(agent_id or "").strip()
    if normalized.lower() in {"", "user", "__self__"}:
        return MemoryScopeFilter(scopes=(SCOPE_SELF_PUBLIC,), owner_ids=("__self__",))
    return MemoryScopeFilter(
        scopes=(SCOPE_CHAR_CANON, SCOPE_CHAR_CROSS_SAVE),
        owner_ids=(normalized,),
    )


class HybridMemoryEngine:
    """Production memory engine composing narrow SOLID ports over SQLite + ONNX."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        repo: MemoryRepository,
        vector_store: StaticVectorStorePort,
        store: SqliteHybridStore | None = None,
    ) -> None:
        self.embedder = embedder
        self.repo = repo
        self.vector_store = vector_store
        self.store = store

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> HybridMemoryEngine:
        embedder_cfg = (config.get("embedder") or {}).get("config") or {}
        snapshot_path = str(embedder_cfg.get("model") or "").strip()
        dims = int(embedder_cfg.get("embedding_dims") or EMBEDDING_DIMS)
        if not snapshot_path:
            raise ValueError("embedder.config.model snapshot path is required")

        vs_cfg = (config.get("vector_store") or {}).get("config") or {}
        raw_db_path = str(vs_cfg.get("path") or "").strip()
        db_path = (
            Path(raw_db_path)
            if raw_db_path
            else (Path.cwd() / "data" / "memory" / MEMORY_STORE_FILENAME)
        )
        if db_path.suffix.lower() != ".db" and db_path.name != ":memory:":
            # Handle legacy configs passing a directory path gracefully
            db_path = db_path / MEMORY_STORE_FILENAME

        embedder = get_shared_onnx_embedder(snapshot_path, dimensions=dims)
        store = SqliteHybridStore(db_path)
        registered_repo = resolve_registered_memory_repository()
        repo: MemoryRepository = (
            registered_repo if registered_repo is not None else SqliteHybridMemoryRepo(store)
        )

        legacy_qdrant = str(vs_cfg.get("legacy_qdrant_path") or "").strip()
        qdrant_dir = (
            Path(legacy_qdrant)
            if legacy_qdrant
            else (db_path.parent / "qdrant")
        )
        migrate_legacy_memory_qdrant(
            qdrant_dir,
            repo,
            meta_store=store,
            expected_dims=dims,
        )
        return cls(
            embedder=embedder,
            repo=repo,
            vector_store=store if isinstance(store, StaticVectorStorePort) else InMemoryStaticVectorStore(),
            store=store,
        )

    def close(self) -> None:
        if self.store is not None:
            self.store.close()

    # ------------------------------------------------------------------
    # Compatibility facade for legacy callers expecting Mem0-style APIs
    # ------------------------------------------------------------------
    def get_all(
        self,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int | None = None,
        top_k: int | None = None,
        **_kwargs: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        resolved_limit = max(1, int(top_k if top_k is not None else (limit if limit is not None else 200)))
        flt = dict(filters or {})
        user_id = str(flt.get("user_id") or "").strip()
        agent_id = str(flt.get("agent_id") or "").strip()
        run_id = str(flt.get("run_id") or "").strip()

        if user_id.startswith(_MEDIA_PREFIX) or agent_id == "semantic-media":
            meta_filter = {"catalog_fingerprint": run_id} if run_id else None
            slices = self.vector_store.list_slices(
                namespace=NAMESPACE_MEDIA_ASSET,
                scope_id=user_id,
                metadata_filter=meta_filter,
                limit=resolved_limit,
            )
            return {
                "results": [
                    {
                        "id": entry.id,
                        "memory": entry.text,
                        "metadata": dict(entry.metadata),
                    }
                    for entry in slices
                ]
            }

        records = self.repo.list_by_scope(
            resolve_memory_read_filter(user_id),
            limit=resolved_limit,
        )
        return {
            "results": [
                {"id": rec.id, "memory": rec.detail_text}
                for rec in records
            ]
        }

    def search(
        self,
        query: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int | None = None,
        top_k: int | None = None,
        **_kwargs: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        q = str(query or "").strip()
        if not q:
            return {"results": []}
        resolved_limit = max(1, int(top_k if top_k is not None else (limit if limit is not None else 10)))
        flt = dict(filters or {})
        user_id = str(flt.get("user_id") or "").strip()
        agent_id = str(flt.get("agent_id") or "").strip()
        run_id = str(flt.get("run_id") or "").strip()
        q_vec = self.embedder.embed_query(q)

        if user_id.startswith(_MEDIA_PREFIX) or agent_id == "semantic-media":
            meta_filter = {"catalog_fingerprint": run_id} if run_id else None
            hits = self.vector_store.search_slices(
                namespace=NAMESPACE_MEDIA_ASSET,
                scope_ids=(user_id,),
                query_vector=q_vec,
                keyword_query=q,
                metadata_filter=meta_filter,
                limit=resolved_limit,
            )
            return {
                "results": [
                    {
                        "id": hit.entry.id,
                        "memory": hit.entry.text,
                        "metadata": dict(hit.entry.metadata),
                        "score": hit.score,
                    }
                    for hit in hits
                ]
            }

        cand_hits = self.repo.search_candidates(
            MemoryCandidateQuery(
                scope_filter=resolve_memory_read_filter(user_id),
                query_vectors=(q_vec,),
                keyword_query=q,
                limit=resolved_limit,
            )
        )
        return {
            "results": [
                {
                    "id": hit.record.id,
                    "memory": hit.record.detail_text,
                    "score": max(0.0, min(1.0, float(hit.vector_score if hit.vector_score > 0 else hit.fts_score))),
                }
                for hit in cand_hits
            ]
        }

    def add(
        self,
        content: str,
        *,
        user_id: str = "user",
        agent_id: str | None = None,
        run_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        infer: bool = False,
        **_kwargs: Any,
    ) -> dict[str, list[dict[str, str]]]:
        del infer
        text = str(content or "").strip()
        if not text:
            return {"results": []}
        vec = self.embedder.embed_query(text)

        if user_id.startswith(_MEDIA_PREFIX) or agent_id == "semantic-media":
            meta = dict(metadata or {})
            if run_id and "catalog_fingerprint" not in meta:
                meta["catalog_fingerprint"] = run_id
            asset_id = str(meta.get("asset_id") or uuid.uuid4().hex)
            slice_id = f"{run_id}:{asset_id}" if run_id else asset_id
            self.vector_store.upsert_slices(
                (
                    VectorSliceEntry(
                        id=slice_id,
                        namespace=NAMESPACE_MEDIA_ASSET,
                        scope_id=user_id,
                        text=text,
                        metadata=meta,
                        embedding=vec,
                    ),
                )
            )
            return {"results": [{"id": slice_id}]}

        scope, owner_id = resolve_memory_write_target(user_id)
        mid = self.repo.upsert(
            MemoryRecord(
                id="",
                scope=scope,
                owner_id=owner_id,
                detail_text=text,
                gist_text=text,
                kind="episodic",
                embedding=vec,
            )
        )
        return {"results": [{"id": mid}]}

    def delete(self, memory_id: str) -> bool:
        return self.repo.delete(memory_id)
