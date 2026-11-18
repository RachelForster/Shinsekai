"""Migration runner for legacy Qdrant knowledge-base slices."""

from __future__ import annotations

import logging
from pathlib import Path
import time

from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    NAMESPACE_KNOWLEDGE,
    StaticVectorStorePort,
    VectorSliceEntry,
)

from ai.memory.migration.errors import LegacyQdrantMigrationError
from ai.memory.migration.qdrant_reader import (
    _KNOWLEDGE_MIGRATION_META_KEY,
    _KNOWLEDGE_MIGRATION_STATUS_META_KEY,
    _discover_collection_sqlite_files,
    _record_migration_status,
    get_knowledge_migration_status,
    read_legacy_qdrant_collection,
)
from ai.memory.migration.unpickler import _parse_timestamp

logger = logging.getLogger(__name__)


def _collect_existing_knowledge_slice_ids(vector_store: StaticVectorStorePort) -> set[str]:
    existing: set[str] = set()
    offset = 0
    page_size = 500
    while True:
        page = vector_store.list_slices(
            namespace=NAMESPACE_KNOWLEDGE,
            offset=offset,
            limit=page_size,
        )
        if not page:
            break
        for entry in page:
            existing.add(entry.id)
        if len(page) < page_size:
            break
        offset += len(page)
    return existing


def _run_knowledge_qdrant_migration(
    qdrant_root: str | Path,
    vector_store: StaticVectorStorePort,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> int:
    if meta_store is not None and meta_store.get_meta(_KNOWLEDGE_MIGRATION_META_KEY):
        return 0

    root = Path(qdrant_root)
    try:
        if not root.exists():
            return 0
        if not root.is_dir():
            _record_migration_status(
                meta_store,
                done_key=_KNOWLEDGE_MIGRATION_META_KEY,
                status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
                completed=False,
                status="read_failed",
                migrated=0,
                empty_source=False,
                read_errors=[f"Legacy Qdrant path is not a directory: {root}"],
                decode_errors=[],
                write_errors=[],
            )
            return 0
    except OSError as exc:
        _record_migration_status(
            meta_store,
            done_key=_KNOWLEDGE_MIGRATION_META_KEY,
            status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
            completed=False,
            status="read_failed",
            migrated=0,
            empty_source=False,
            read_errors=[f"{root}: {type(exc).__name__}: {exc}"],
            decode_errors=[],
            write_errors=[],
        )
        return 0

    collections_dir = root / "collection"
    try:
        if not collections_dir.exists():
            return 0
        if not collections_dir.is_dir():
            _record_migration_status(
                meta_store,
                done_key=_KNOWLEDGE_MIGRATION_META_KEY,
                status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
                completed=False,
                status="read_failed",
                migrated=0,
                empty_source=False,
                read_errors=[f"Legacy Qdrant collection path is not a directory: {collections_dir}"],
                decode_errors=[],
                write_errors=[],
            )
            return 0
    except OSError as exc:
        _record_migration_status(
            meta_store,
            done_key=_KNOWLEDGE_MIGRATION_META_KEY,
            status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
            completed=False,
            status="read_failed",
            migrated=0,
            empty_source=False,
            read_errors=[f"{collections_dir}: {type(exc).__name__}: {exc}"],
            decode_errors=[],
            write_errors=[],
        )
        return 0

    sqlite_files, read_errors = _discover_collection_sqlite_files(
        collections_dir,
        ("character_knowledge_settings_rag_minilm",),
    )
    decode_errors: list[str] = []
    write_errors: list[str] = []
    batch: list[VectorSliceEntry] = []
    total_points_seen = 0
    now = time.time()

    try:
        existing_ids = _collect_existing_knowledge_slice_ids(vector_store)
    except Exception as exc:
        _record_migration_status(
            meta_store,
            done_key=_KNOWLEDGE_MIGRATION_META_KEY,
            status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
            completed=False,
            status="write_failed",
            migrated=0,
            empty_source=False,
            read_errors=[],
            decode_errors=[],
            write_errors=[f"Failed to inspect target knowledge store: {type(exc).__name__}: {exc}"],
        )
        return 0

    seen_ids = set(existing_ids)

    for sqlite_file in sqlite_files:
        read_res = read_legacy_qdrant_collection(
            sqlite_file,
            expected_dims=expected_dims,
            trusted_source=trusted_source,
        )
        if read_res.status == "missing":
            read_errors.append(
                f"{sqlite_file}: missing storage.sqlite inside collection directory"
            )
            continue
        if read_res.status == "read_error":
            read_errors.append(f"{sqlite_file}: {read_res.error}")
            continue
        if read_res.decode_errors:
            for row_id, detail in read_res.decode_errors:
                decode_errors.append(f"{sqlite_file} [row {row_id}]: {detail}")

        for item in read_res.points:
            total_points_seen += 1
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

    migrated = 0
    if batch:
        try:
            migrated = vector_store.upsert_slices(batch)
        except Exception as exc:
            write_errors.append(f"{type(exc).__name__}: {exc}")

    has_errors = bool(read_errors or decode_errors or write_errors)
    if has_errors:
        if write_errors:
            status_label = "write_failed"
        elif read_errors and not decode_errors and migrated == 0:
            status_label = "read_failed"
        elif decode_errors and not read_errors and migrated == 0:
            status_label = "decode_failed"
        else:
            status_label = "partial_error"
        _record_migration_status(
            meta_store,
            done_key=_KNOWLEDGE_MIGRATION_META_KEY,
            status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
            completed=False,
            status=status_label,
            migrated=migrated,
            empty_source=False,
            read_errors=read_errors,
            decode_errors=decode_errors,
            write_errors=write_errors,
        )
        logger.warning(
            "Legacy Qdrant knowledge migration incomplete (status=%s, migrated=%d, read_errors=%d, decode_errors=%d, write_errors=%d): %s",
            status_label,
            migrated,
            len(read_errors),
            len(decode_errors),
            len(write_errors),
            (read_errors or decode_errors or write_errors)[0],
        )
        return migrated

    _record_migration_status(
        meta_store,
        done_key=_KNOWLEDGE_MIGRATION_META_KEY,
        status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
        completed=True,
        status="completed",
        migrated=migrated,
        empty_source=(total_points_seen == 0),
        read_errors=[],
        decode_errors=[],
        write_errors=[],
    )
    if migrated:
        logger.info(
            "Migrated %d legacy Qdrant knowledge entries into SQLite hybrid store",
            migrated,
        )
    return migrated


def migrate_legacy_knowledge_qdrant(
    qdrant_root: str | Path,
    vector_store: StaticVectorStorePort,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
) -> int:
    """Automatically migrate standard legacy Qdrant PointStruct knowledge slices once."""
    return _run_knowledge_qdrant_migration(
        qdrant_root,
        vector_store,
        meta_store=meta_store,
        expected_dims=expected_dims,
        trusted_source=False,
    )


def migrate_legacy_knowledge_qdrant_explicit(
    qdrant_root: str | Path,
    vector_store: StaticVectorStorePort,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> int:
    """User-initiated migration for legacy knowledge Qdrant archives requiring explicit trust."""
    if not trusted_source:
        raise PermissionError(
            "Explicit legacy Qdrant migration requires trusted_source=True after verifying the archive source."
        )
    migrated = _run_knowledge_qdrant_migration(
        qdrant_root,
        vector_store,
        meta_store=meta_store,
        expected_dims=expected_dims,
        trusted_source=True,
    )
    if meta_store is not None:
        status = get_knowledge_migration_status(meta_store)
        if not status["completed"] and status["reason"]:
            raise LegacyQdrantMigrationError(status["reason"])
    return migrated
