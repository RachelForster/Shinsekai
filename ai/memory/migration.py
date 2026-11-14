"""Zero-dependency migration from legacy local Qdrant SQLite storage."""

from __future__ import annotations

import datetime as _dt
import io
import logging
import pickle
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.vector_store.sqlite_hybrid_store import SqliteHybridStore, normalize_vector
from sdk.adapters.memory import (
    NAMESPACE_KNOWLEDGE,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    MemoryRecord,
    MemoryRepository,
    StaticVectorStorePort,
    VectorSliceEntry,
)

logger = logging.getLogger(__name__)

_MEMORY_MIGRATION_META_KEY = "migration.qdrant_memory.v1"
_KNOWLEDGE_MIGRATION_META_KEY = "migration.qdrant_knowledge.v1"

_SAFE_PICKLE_MODULES = frozenset(
    {
        "builtins",
        "__builtin__",
        "collections",
        "datetime",
        "uuid",
        "_codecs",
        "copyreg",
    }
)


class _QdrantPointStub:
    """Harmless placeholder for pickled qdrant_client / pydantic model instances."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.state: Any = None

    def __setstate__(self, state: Any) -> None:
        self.state = state


class _QdrantSafeUnpickler(pickle.Unpickler):
    """Restricted unpickler reading Qdrant PointStruct blobs without qdrant_client."""

    def find_class(self, module: str, name: str) -> Any:
        if module.startswith("qdrant_client") or module.startswith("pydantic"):
            return _QdrantPointStub
        if module in _SAFE_PICKLE_MODULES:
            return super().find_class(module, name)
        if module.startswith("numpy"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"Blocked unsafe pickle import: {module}.{name}")


def _unwrap_point_dict(raw_obj: Any) -> dict[str, Any]:
    if isinstance(raw_obj, dict):
        return raw_obj
    state = getattr(raw_obj, "state", None)
    if isinstance(state, dict):
        inner = state.get("__dict__")
        if isinstance(inner, dict):
            return inner
        return state
    obj_dict = getattr(raw_obj, "__dict__", None)
    if isinstance(obj_dict, dict):
        return obj_dict
    return {}


def _extract_vector_from_point(raw_vector: Any, *, expected_dims: int = 384) -> Any | None:
    candidate = raw_vector
    if isinstance(candidate, dict):
        if "" in candidate:
            candidate = candidate[""]
        elif candidate:
            candidate = next(iter(candidate.values()))
        else:
            return None
    if candidate is None:
        return None
    arr = normalize_vector(candidate)
    if arr is None or arr.shape[0] != expected_dims:
        return None
    return arr


def _parse_timestamp(value: Any, *, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(text).timestamp()
    except Exception:
        return fallback


def iter_legacy_qdrant_points(
    storage_sqlite_path: str | Path,
    *,
    expected_dims: int = 384,
) -> list[dict[str, Any]]:
    """Read all valid points from a Qdrant collection storage.sqlite file."""
    path = Path(storage_sqlite_path)
    if not path.is_file():
        return []

    points: list[dict[str, Any]] = []
    uri = f"file:{path.as_posix()}?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=3.0)
        except sqlite3.OperationalError:
            conn = sqlite3.connect(str(path), timeout=3.0)

        table_check = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='points'"
        ).fetchone()
        if table_check is None:
            return []

        for row_key, blob in conn.execute("SELECT id, point FROM points"):
            if not isinstance(blob, (bytes, bytearray, memoryview)):
                continue
            try:
                decoded = _QdrantSafeUnpickler(io.BytesIO(bytes(blob))).load()
            except Exception:
                logger.debug("Skipping unreadable Qdrant point row %r in %s", row_key, path, exc_info=True)
                continue
            data = _unwrap_point_dict(decoded)
            point_id = str(data.get("id") if data.get("id") is not None else row_key or "").strip()
            payload = data.get("payload")
            if not point_id or not isinstance(payload, dict):
                continue
            vector = _extract_vector_from_point(data.get("vector"), expected_dims=expected_dims)
            points.append(
                {
                    "id": point_id,
                    "payload": payload,
                    "vector": vector,
                }
            )
    except Exception:
        logger.warning("Failed to inspect legacy Qdrant storage at %s", path, exc_info=True)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return points


def migrate_legacy_memory_qdrant(
    qdrant_root: str | Path,
    repo: MemoryRepository,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
) -> int:
    """Import legacy character/user memories from local Qdrant once."""
    if meta_store is not None and meta_store.get_meta(_MEMORY_MIGRATION_META_KEY):
        return 0

    root = Path(qdrant_root)
    collections_dir = root / "collection"
    if not collections_dir.is_dir():
        if meta_store is not None:
            meta_store.set_meta(_MEMORY_MIGRATION_META_KEY, "empty")
        return 0

    # Prefer the multilingual collection first, then any older 384-dim collection.
    preferred_order = [
        collections_dir / "character_memories_multilingual_minilm" / "storage.sqlite",
        collections_dir / "character_memories" / "storage.sqlite",
    ]
    for extra in sorted(collections_dir.glob("*/storage.sqlite")):
        if extra not in preferred_order and not extra.parent.name.endswith("_entities"):
            preferred_order.append(extra)

    migrated = 0
    seen_ids: set[str] = set()
    now = time.time()

    for sqlite_file in preferred_order:
        for item in iter_legacy_qdrant_points(sqlite_file, expected_dims=expected_dims):
            pid = item["id"]
            if pid in seen_ids:
                continue
            payload = item["payload"]
            user_id = str(payload.get("user_id") or "").strip()
            agent_id = str(payload.get("agent_id") or "").strip()
            if not user_id or user_id.startswith("__shinsekai_media__:") or agent_id == "semantic-media":
                continue
            text = str(
                payload.get("data")
                or payload.get("memory")
                or payload.get("content")
                or ""
            ).strip()
            if not text:
                continue

            seen_ids.add(pid)
            if repo.get(pid) is not None:
                continue

            if user_id.lower() in {"user", "__self__"}:
                scope = SCOPE_SELF_PUBLIC
                owner_id = "__self__"
            else:
                scope = SCOPE_CHAR_CROSS_SAVE
                owner_id = user_id

            created_ts = _parse_timestamp(payload.get("created_at"), fallback=now)
            updated_ts = _parse_timestamp(payload.get("updated_at"), fallback=created_ts)
            repo.upsert(
                MemoryRecord(
                    id=pid,
                    scope=scope,
                    owner_id=owner_id,
                    detail_text=text,
                    gist_text=text,
                    kind="episodic",
                    importance=0.5,
                    pinned=False,
                    created_at=created_ts,
                    last_recalled_at=updated_ts,
                    embedding=item["vector"],
                )
            )
            migrated += 1

    if meta_store is not None:
        meta_store.set_meta(_MEMORY_MIGRATION_META_KEY, f"migrated:{migrated}")
    if migrated:
        logger.info("Migrated %d legacy Qdrant memories into SQLite hybrid store", migrated)
    return migrated


def migrate_legacy_knowledge_qdrant(
    qdrant_root: str | Path,
    vector_store: StaticVectorStorePort,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
) -> int:
    """Import legacy knowledge base slices from local Qdrant once."""
    if meta_store is not None and meta_store.get_meta(_KNOWLEDGE_MIGRATION_META_KEY):
        return 0

    root = Path(qdrant_root)
    collections_dir = root / "collection"
    if not collections_dir.is_dir():
        if meta_store is not None:
            meta_store.set_meta(_KNOWLEDGE_MIGRATION_META_KEY, "empty")
        return 0

    preferred_order = [
        collections_dir / "character_knowledge_settings_rag_minilm" / "storage.sqlite",
    ]
    for extra in sorted(collections_dir.glob("*/storage.sqlite")):
        if extra not in preferred_order and not extra.parent.name.endswith("_entities"):
            preferred_order.append(extra)

    batch: list[VectorSliceEntry] = []
    seen_ids: set[str] = set()
    now = time.time()

    for sqlite_file in preferred_order:
        for item in iter_legacy_qdrant_points(sqlite_file, expected_dims=expected_dims):
            pid = item["id"]
            if pid in seen_ids:
                continue
            payload = item["payload"]
            knowledge_id = str(payload.get("user_id") or "").strip()
            text = str(
                payload.get("data")
                or payload.get("memory")
                or payload.get("content")
                or payload.get("text")
                or ""
            ).strip()
            if not knowledge_id or not text:
                continue
            seen_ids.add(pid)
            created_ts = _parse_timestamp(payload.get("created_at"), fallback=now)
            batch.append(
                VectorSliceEntry(
                    id=pid,
                    namespace=NAMESPACE_KNOWLEDGE,
                    scope_id=knowledge_id,
                    text=text,
                    metadata={"user_id": knowledge_id},
                    created_at=created_ts,
                    embedding=item["vector"],
                )
            )

    migrated = vector_store.upsert_slices(batch) if batch else 0
    if meta_store is not None:
        meta_store.set_meta(_KNOWLEDGE_MIGRATION_META_KEY, f"migrated:{migrated}")
    if migrated:
        logger.info("Migrated %d legacy Qdrant knowledge entries into SQLite hybrid store", migrated)
    return migrated
