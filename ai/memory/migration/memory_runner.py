"""Migration runner for legacy Qdrant character/self memories."""

from __future__ import annotations

import logging
from pathlib import Path
import time

from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    MemoryRecord,
    MemoryRepository,
)

from ai.memory.migration.errors import LegacyQdrantMigrationError
from ai.memory.migration.qdrant_reader import (
    _MEMORY_MIGRATION_META_KEY,
    _MEMORY_MIGRATION_STATUS_META_KEY,
    _discover_collection_sqlite_files,
    _record_migration_status,
    get_memory_migration_status,
    read_legacy_qdrant_collection,
)
from ai.memory.migration.unpickler import _parse_timestamp

logger = logging.getLogger(__name__)


def _run_memory_qdrant_migration(
    qdrant_root: str | Path,
    repo: MemoryRepository,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> int:
    if meta_store is not None and meta_store.get_meta(_MEMORY_MIGRATION_META_KEY):
        return 0

    root = Path(qdrant_root)
    try:
        if not root.exists():
            return 0
        if not root.is_dir():
            _record_migration_status(
                meta_store,
                done_key=_MEMORY_MIGRATION_META_KEY,
                status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
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
            done_key=_MEMORY_MIGRATION_META_KEY,
            status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
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
                done_key=_MEMORY_MIGRATION_META_KEY,
                status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
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
            done_key=_MEMORY_MIGRATION_META_KEY,
            status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
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
        ("character_memories_multilingual_minilm", "character_memories"),
    )
    decode_errors: list[str] = []
    write_errors: list[str] = []
    migrated = 0
    total_points_seen = 0
    seen_ids: set[str] = set()
    now = time.time()

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
            user_id = str(payload.get("user_id") or "").strip()
            agent_id = str(payload.get("agent_id") or "").strip()
            if (
                not user_id
                or user_id.startswith("__shinsekai_media__:")
                or agent_id == "semantic-media"
            ):
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
            try:
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
            except Exception as exc:
                write_errors.append(f"{pid}: {type(exc).__name__}: {exc}")

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
            done_key=_MEMORY_MIGRATION_META_KEY,
            status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
            completed=False,
            status=status_label,
            migrated=migrated,
            empty_source=False,
            read_errors=read_errors,
            decode_errors=decode_errors,
            write_errors=write_errors,
        )
        logger.warning(
            "Legacy Qdrant memory migration incomplete (status=%s, migrated=%d, read_errors=%d, decode_errors=%d, write_errors=%d): %s",
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
        done_key=_MEMORY_MIGRATION_META_KEY,
        status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
        completed=True,
        status="completed",
        migrated=migrated,
        empty_source=(total_points_seen == 0),
        read_errors=[],
        decode_errors=[],
        write_errors=[],
    )
    if migrated:
        logger.info("Migrated %d legacy Qdrant memories into SQLite hybrid store", migrated)
    return migrated


def migrate_legacy_memory_qdrant(
    qdrant_root: str | Path,
    repo: MemoryRepository,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
) -> int:
    """Automatically migrate standard legacy Qdrant PointStruct memories once."""
    return _run_memory_qdrant_migration(
        qdrant_root,
        repo,
        meta_store=meta_store,
        expected_dims=expected_dims,
        trusted_source=False,
    )


def migrate_legacy_memory_qdrant_explicit(
    qdrant_root: str | Path,
    repo: MemoryRepository,
    *,
    meta_store: SqliteHybridStore | None = None,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> int:
    """User-initiated migration for legacy Qdrant archives requiring explicit trust."""
    if not trusted_source:
        raise PermissionError(
            "Explicit legacy Qdrant migration requires trusted_source=True after verifying the archive source."
        )
    migrated = _run_memory_qdrant_migration(
        qdrant_root,
        repo,
        meta_store=meta_store,
        expected_dims=expected_dims,
        trusted_source=True,
    )
    if meta_store is not None:
        status = get_memory_migration_status(meta_store)
        if not status["completed"] and status["reason"]:
            raise LegacyQdrantMigrationError(status["reason"])
    return migrated
