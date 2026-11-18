"""Legacy Qdrant SQLite collection reader and migration status persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from core.vector_store.sqlite_hybrid_store import SqliteHybridStore

from ai.memory.migration.errors import (
    LegacyQdrantDecodeError,
    LegacyQdrantReadError,
    UnsafeLegacyQdrantDataError,
)
from ai.memory.migration.unpickler import decode_legacy_qdrant_point

_MEMORY_MIGRATION_META_KEY = "migration.qdrant_memory.v1"
_MEMORY_MIGRATION_STATUS_META_KEY = "migration.qdrant_memory.v1.status"
_KNOWLEDGE_MIGRATION_META_KEY = "migration.qdrant_knowledge.v1"
_KNOWLEDGE_MIGRATION_STATUS_META_KEY = "migration.qdrant_knowledge.v1.status"


@dataclass(frozen=True, slots=True)
class QdrantCollectionReadResult:
    """Outcome of inspecting a single legacy Qdrant collection ``storage.sqlite``."""

    path: Path
    status: str  # "missing" | "empty" | "ok" | "read_error" | "decode_error"
    points: tuple[dict[str, Any], ...]
    decode_errors: tuple[tuple[str, str], ...] = ()
    error: str = ""


def read_legacy_qdrant_collection(
    storage_sqlite_path: str | Path,
    *,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> QdrantCollectionReadResult:
    """Inspect a legacy Qdrant ``storage.sqlite`` distinguishing empty, read error, and decode error."""
    path = Path(storage_sqlite_path)
    try:
        exists = path.exists()
    except OSError as exc:
        return QdrantCollectionReadResult(
            path=path,
            status="read_error",
            points=(),
            error=f"{type(exc).__name__}: {exc}",
        )
    if not exists:
        return QdrantCollectionReadResult(path=path, status="missing", points=())
    if not path.is_file():
        return QdrantCollectionReadResult(
            path=path,
            status="read_error",
            points=(),
            error=f"Legacy Qdrant storage path is not a regular file: {path}",
        )

    points: list[dict[str, Any]] = []
    decode_errors: list[tuple[str, str]] = []
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
            return QdrantCollectionReadResult(
                path=path,
                status="read_error",
                points=(),
                error="Missing 'points' table in legacy Qdrant storage.sqlite",
            )

        for row_key, blob in conn.execute("SELECT id, point FROM points"):
            try:
                point = decode_legacy_qdrant_point(
                    blob,
                    row_key=row_key,
                    expected_dims=expected_dims,
                    trusted_source=trusted_source,
                )
                points.append(point)
            except LegacyQdrantDecodeError as exc:
                decode_errors.append((str(row_key), str(exc)))
    except (sqlite3.Error, OSError) as exc:
        return QdrantCollectionReadResult(
            path=path,
            status="read_error",
            points=tuple(points),
            decode_errors=tuple(decode_errors),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if decode_errors:
        return QdrantCollectionReadResult(
            path=path,
            status="decode_error",
            points=tuple(points),
            decode_errors=tuple(decode_errors),
            error=f"{len(decode_errors)} point(s) failed to decode: {decode_errors[0][1]}",
        )
    return QdrantCollectionReadResult(
        path=path,
        status="ok" if points else "empty",
        points=tuple(points),
    )


def iter_legacy_qdrant_points(
    storage_sqlite_path: str | Path,
    *,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> list[dict[str, Any]]:
    """Read all points from ``storage.sqlite``, raising on SQLite read or point decode errors."""
    result = read_legacy_qdrant_collection(
        storage_sqlite_path,
        expected_dims=expected_dims,
        trusted_source=trusted_source,
    )
    if result.status == "missing":
        return []
    if result.status == "read_error":
        raise LegacyQdrantReadError(f"{result.path}: {result.error}")
    if result.decode_errors:
        row_id, detail = result.decode_errors[0]
        if "Blocked unsupported pickle global" in detail or "Blocked unsupported pickle" in detail:
            raise UnsafeLegacyQdrantDataError(f"{result.path} [row {row_id}]: {detail}")
        raise LegacyQdrantDecodeError(f"{result.path} [row {row_id}]: {detail}")
    return list(result.points)


def _discover_collection_sqlite_files(
    collections_dir: Path,
    preferred_names: tuple[str, ...],
) -> tuple[list[Path], list[str]]:
    """Return ordered ``storage.sqlite`` candidates and any structural directory errors."""
    sqlite_files: list[Path] = []
    read_errors: list[str] = []
    seen_dirs: set[str] = set()

    for name in preferred_names:
        cand_dir = collections_dir / name
        try:
            if not cand_dir.exists():
                continue
            if not cand_dir.is_dir():
                read_errors.append(f"{cand_dir}: collection entry is not a directory")
                continue
        except OSError as exc:
            read_errors.append(f"{cand_dir}: {type(exc).__name__}: {exc}")
            continue
        seen_dirs.add(name)
        sqlite_files.append(cand_dir / "storage.sqlite")

    try:
        entries = sorted(collections_dir.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        read_errors.append(f"{collections_dir}: {type(exc).__name__}: {exc}")
        return sqlite_files, read_errors

    for entry in entries:
        if entry.name in seen_dirs or entry.name.endswith("_entities") or entry.name.startswith("."):
            continue
        try:
            if not entry.is_dir():
                continue
        except OSError as exc:
            read_errors.append(f"{entry}: {type(exc).__name__}: {exc}")
            continue
        sqlite_files.append(entry / "storage.sqlite")

    return sqlite_files, read_errors


def _record_migration_status(
    meta_store: SqliteHybridStore | None,
    *,
    done_key: str,
    status_key: str,
    completed: bool,
    status: str,
    migrated: int,
    empty_source: bool,
    read_errors: list[str],
    decode_errors: list[str],
    write_errors: list[str],
) -> None:
    if meta_store is None:
        return
    all_errors = [*read_errors, *decode_errors, *write_errors]
    payload = {
        "status": status,
        "completed": completed,
        "retryable": not completed,
        "migrated": migrated,
        "empty_source": empty_source,
        "reason": all_errors[0] if all_errors else "",
        "read_errors": read_errors,
        "decode_errors": decode_errors,
        "write_errors": write_errors,
        "updated_at": time.time(),
    }
    meta_store.set_meta(status_key, json.dumps(payload, ensure_ascii=False))
    if completed:
        meta_store.set_meta(done_key, f"migrated:{migrated}")


def _read_migration_status(
    meta_store: SqliteHybridStore,
    *,
    done_key: str,
    status_key: str,
) -> dict[str, Any]:
    done_marker = meta_store.get_meta(done_key)
    raw_status = meta_store.get_meta(status_key)
    if raw_status:
        try:
            parsed = json.loads(raw_status)
            if isinstance(parsed, dict):
                parsed["completed"] = bool(done_marker)
                parsed["retryable"] = not bool(done_marker)
                return parsed
        except ValueError:
            pass
    if done_marker:
        return {
            "status": "completed",
            "completed": True,
            "retryable": False,
            "migrated": 0,
            "empty_source": done_marker == "empty",
            "reason": "",
            "read_errors": [],
            "decode_errors": [],
            "write_errors": [],
        }
    return {
        "status": "not_started",
        "completed": False,
        "retryable": True,
        "migrated": 0,
        "empty_source": False,
        "reason": "",
        "read_errors": [],
        "decode_errors": [],
        "write_errors": [],
    }


def get_memory_migration_status(meta_store: SqliteHybridStore) -> dict[str, Any]:
    """Return structured status and failure diagnostics for legacy memory Qdrant migration."""
    return _read_migration_status(
        meta_store,
        done_key=_MEMORY_MIGRATION_META_KEY,
        status_key=_MEMORY_MIGRATION_STATUS_META_KEY,
    )


def get_knowledge_migration_status(meta_store: SqliteHybridStore) -> dict[str, Any]:
    """Return structured status and failure diagnostics for legacy knowledge Qdrant migration."""
    return _read_migration_status(
        meta_store,
        done_key=_KNOWLEDGE_MIGRATION_META_KEY,
        status_key=_KNOWLEDGE_MIGRATION_STATUS_META_KEY,
    )
