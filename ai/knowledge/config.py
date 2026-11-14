"""Hybrid SQLite + ONNX configuration for the isolated knowledge store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import Any
import uuid

from ai.knowledge.constants import KNOWLEDGE_STORE_FILENAME, VECTOR_COLLECTION
from ai.memory.config import build_mem0_config
from ai.memory.constants import EMBEDDING_DIMS
from ai.memory.engine import get_shared_onnx_embedder
from ai.memory.migration import migrate_legacy_knowledge_qdrant
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    NAMESPACE_KNOWLEDGE,
    EmbeddingProvider,
    StaticVectorStorePort,
    VectorSliceEntry,
    VectorSliceHit,
)


def configure_mem0_environment() -> None:
    """Default telemetry off while preserving explicitly configured values."""
    os.environ.setdefault("MEM0_TELEMETRY", "False")


class KnowledgeVectorStoreAdapter:
    """Adapter implementing StaticVectorStorePort and exposing .client/.collection_name."""

    def __init__(
        self,
        port: StaticVectorStorePort,
        *,
        collection_name: str = NAMESPACE_KNOWLEDGE,
    ) -> None:
        self._port = port
        self.collection_name = collection_name

    @property
    def client(self) -> StaticVectorStorePort:
        return self._port

    def upsert_slices(self, entries: Sequence[VectorSliceEntry]) -> int:
        return self._port.upsert_slices(entries)

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
        return self._port.search_slices(
            namespace=namespace,
            scope_ids=scope_ids,
            query_vector=query_vector,
            keyword_query=keyword_query,
            metadata_filter=metadata_filter,
            limit=limit,
        )

    def list_slices(
        self,
        *,
        namespace: str,
        scope_id: str | None = None,
        metadata_filter: Mapping[str, Any] | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> Sequence[VectorSliceEntry]:
        return self._port.list_slices(
            namespace=namespace,
            scope_id=scope_id,
            metadata_filter=metadata_filter,
            offset=offset,
            limit=limit,
        )

    def count_by_scope(self, *, namespace: str) -> Mapping[str, int]:
        return self._port.count_by_scope(namespace=namespace)

    def delete_slice(self, *, namespace: str, slice_id: str) -> bool:
        return self._port.delete_slice(namespace=namespace, slice_id=slice_id)

    def delete_scope(self, *, namespace: str, scope_id: str) -> int:
        return self._port.delete_scope(namespace=namespace, scope_id=scope_id)


class HybridKnowledgeStore:
    """Isolated knowledge vector store backed by SqliteHybridStore and shared ONNX embedder."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        port: StaticVectorStorePort,
        store: SqliteHybridStore | None = None,
        namespace: str = NAMESPACE_KNOWLEDGE,
    ) -> None:
        self.embedder = embedder
        self.port = port
        self.store = store
        self.namespace = namespace
        self.vector_store = KnowledgeVectorStoreAdapter(port, collection_name=namespace)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> HybridKnowledgeStore:
        embedder_cfg = (config.get("embedder") or {}).get("config") or {}
        snapshot_path = str(embedder_cfg.get("model") or "").strip()
        dims = int(embedder_cfg.get("embedding_dims") or EMBEDDING_DIMS)
        if not snapshot_path:
            raise ValueError("embedder.config.model snapshot path is required")

        vs_cfg = (config.get("vector_store") or {}).get("config") or {}
        raw_path = str(vs_cfg.get("path") or "").strip()
        db_path = (
            Path(raw_path)
            if raw_path
            else (Path.cwd() / "data" / "knowledge" / KNOWLEDGE_STORE_FILENAME)
        )
        if db_path.suffix.lower() != ".db" and db_path.name != ":memory:":
            db_path = db_path / KNOWLEDGE_STORE_FILENAME

        embedder = get_shared_onnx_embedder(snapshot_path, dimensions=dims)
        store = SqliteHybridStore(db_path)

        legacy_qdrant = str(vs_cfg.get("legacy_qdrant_path") or "").strip()
        qdrant_dir = (
            Path(legacy_qdrant)
            if legacy_qdrant
            else (db_path.parent / "qdrant")
        )
        migrate_legacy_knowledge_qdrant(
            qdrant_dir,
            store,
            meta_store=store,
            expected_dims=dims,
        )
        return cls(
            embedder=embedder,
            port=store,
            store=store,
            namespace=NAMESPACE_KNOWLEDGE,
        )

    def close(self) -> None:
        if self.store is not None:
            self.store.close()

    def get_all(
        self,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int | None = None,
        top_k: int | None = None,
        **_kwargs: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        resolved_limit = max(1, int(top_k if top_k is not None else (limit if limit is not None else 200)))
        knowledge_id = str((filters or {}).get("user_id") or "").strip()
        slices = self.port.list_slices(
            namespace=self.namespace,
            scope_id=knowledge_id or None,
            limit=resolved_limit,
        )
        return {
            "results": [
                {"id": entry.id, "memory": entry.text}
                for entry in slices
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
        knowledge_id = str((filters or {}).get("user_id") or "").strip()
        if not q or not knowledge_id:
            return {"results": []}
        resolved_limit = max(1, int(top_k if top_k is not None else (limit if limit is not None else 10)))
        q_vec = self.embedder.embed_query(q)
        hits = self.port.search_slices(
            namespace=self.namespace,
            scope_ids=(knowledge_id,),
            query_vector=q_vec,
            keyword_query=q,
            limit=resolved_limit,
        )
        return {
            "results": [
                {
                    "id": hit.entry.id,
                    "memory": hit.entry.text,
                    "score": hit.score,
                }
                for hit in hits
            ]
        }

    def add(
        self,
        content: str,
        *,
        user_id: str,
        infer: bool = False,
        **_kwargs: Any,
    ) -> dict[str, list[dict[str, str]]]:
        del infer
        text = str(content or "").strip()
        knowledge_id = str(user_id or "").strip()
        if not text or not knowledge_id:
            return {"results": []}
        sid = uuid.uuid4().hex
        vec = self.embedder.embed_query(text)
        self.port.upsert_slices(
            (
                VectorSliceEntry(
                    id=sid,
                    namespace=self.namespace,
                    scope_id=knowledge_id,
                    text=text,
                    metadata={"user_id": knowledge_id},
                    embedding=vec,
                ),
            )
        )
        return {"results": [{"id": sid}]}

    def delete(self, memory_id: str) -> bool:
        return self.port.delete_slice(namespace=self.namespace, slice_id=memory_id)


def build_knowledge_mem0_config() -> dict[str, Any]:
    config = build_mem0_config()
    root = Path.cwd() / "data" / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    config["vector_store"]["config"].update(
        {
            "path": (root / KNOWLEDGE_STORE_FILENAME).as_posix(),
            "legacy_qdrant_path": (root / "qdrant").as_posix(),
            "collection_name": VECTOR_COLLECTION,
        }
    )
    config["history_db_path"] = str(root / "knowledge_history.db")
    return config


def create_knowledge_mem0(engine_type: Any, snapshot_path: str) -> Any:
    """Create the isolated knowledge store with an already prepared embedding snapshot."""
    configure_mem0_environment()
    config = build_knowledge_mem0_config()
    config["embedder"]["config"]["model"] = snapshot_path
    return engine_type.from_config(config)
