"""Zero-dependency migration from legacy local Qdrant SQLite storage."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _dt
import io
import json
import logging
from pathlib import Path
import pickle
import sqlite3
import time
from typing import Any
import uuid

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
_MEMORY_MIGRATION_STATUS_META_KEY = "migration.qdrant_memory.v1.status"
_KNOWLEDGE_MIGRATION_META_KEY = "migration.qdrant_knowledge.v1"
_KNOWLEDGE_MIGRATION_STATUS_META_KEY = "migration.qdrant_knowledge.v1.status"

_EXPECTED_PYDANTIC_STATE_KEYS = frozenset(
    {
        "__dict__",
        "__pydantic_fields_set__",
        "__pydantic_extra__",
        "__pydantic_private__",
        "__fields_set__",
        "__private_attribute_values__",
    }
)
_EXPECTED_POINT_KEYS = frozenset(
    {
        "id",
        "vector",
        "payload",
        "shard_key",
        "order_value",
    }
)
_EXPECTED_SPARSE_VECTOR_KEYS = frozenset({"indices", "values"})
_MAX_PAYLOAD_DEPTH = 16


class LegacyQdrantMigrationError(RuntimeError):
    """Base error for legacy local Qdrant migration failures."""


class LegacyQdrantReadError(LegacyQdrantMigrationError):
    """Raised when a legacy Qdrant SQLite database cannot be opened or queried."""


class LegacyQdrantDecodeError(LegacyQdrantMigrationError):
    """Raised when a legacy Qdrant point row is malformed or cannot be decoded."""


class UnsafeLegacyQdrantDataError(pickle.UnpicklingError, LegacyQdrantDecodeError):
    """Raised when a legacy Qdrant pickle references an unsupported or unsafe global."""


def _is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _safe_set(items: Any = ()) -> set[Any]:
    if not isinstance(items, (list, tuple, set, frozenset)):
        raise UnsafeLegacyQdrantDataError("set() constructor requires a sequence of primitives")
    for item in items:
        if not isinstance(item, (str, int)) or isinstance(item, bool):
            raise UnsafeLegacyQdrantDataError(
                f"Unsupported element type in pickled set: {type(item).__name__}"
            )
    return set(items)


def _safe_frozenset(items: Any = ()) -> frozenset[Any]:
    return frozenset(_safe_set(items))


class _SafeUUIDStub:
    """Minimal safe placeholder for pickled ``uuid.UUID`` values."""

    __slots__ = ("_uuid",)

    def __new__(cls) -> _SafeUUIDStub:
        inst = super().__new__(cls)
        inst._uuid = None
        return inst

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args or kwargs:
            raise UnsafeLegacyQdrantDataError("Direct UUID constructor calls are not permitted")

    def __setstate__(self, state: Any) -> None:
        if not isinstance(state, dict):
            raise LegacyQdrantDecodeError("Invalid pickled UUID state")
        raw_int = state.get("int")
        if not _is_plain_int(raw_int) or not (0 <= raw_int < (1 << 128)):
            raise LegacyQdrantDecodeError("Invalid 128-bit integer in pickled UUID state")
        self._uuid = uuid.UUID(int=raw_int)

    @property
    def uuid_value(self) -> uuid.UUID:
        if self._uuid is None:
            raise LegacyQdrantDecodeError("Uninitialized pickled UUID")
        return self._uuid

    def __str__(self) -> str:
        return str(self.uuid_value)


class _QdrantSparseVectorStub:
    """Minimal validated placeholder for ``qdrant_client`` ``SparseVector``."""

    __slots__ = ("indices", "values")

    def __new__(cls) -> _QdrantSparseVectorStub:
        inst = super().__new__(cls)
        inst.indices = ()
        inst.values = ()
        return inst

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args or kwargs:
            raise UnsafeLegacyQdrantDataError(
                "Direct SparseVector constructor arguments are not permitted"
            )

    def __setstate__(self, state: Any) -> None:
        if not isinstance(state, dict):
            raise LegacyQdrantDecodeError("Invalid SparseVector pickle state")
        if "__dict__" in state:
            unknown_outer = set(state.keys()) - _EXPECTED_PYDANTIC_STATE_KEYS
            if unknown_outer:
                raise LegacyQdrantDecodeError(
                    f"Unexpected outer keys in SparseVector state: {sorted(unknown_outer)}"
                )
            fields = state["__dict__"]
        else:
            fields = state
        if not isinstance(fields, dict):
            raise LegacyQdrantDecodeError("Invalid SparseVector fields dictionary")
        unknown_fields = set(fields.keys()) - _EXPECTED_SPARSE_VECTOR_KEYS
        if unknown_fields:
            raise LegacyQdrantDecodeError(
                f"Unexpected fields in SparseVector: {sorted(unknown_fields)}"
            )
        raw_indices = fields.get("indices") or ()
        raw_values = fields.get("values") or ()
        if not isinstance(raw_indices, (list, tuple)) or not all(
            _is_plain_int(i) for i in raw_indices
        ):
            raise LegacyQdrantDecodeError("SparseVector.indices must be a list of integers")
        if not isinstance(raw_values, (list, tuple)) or not all(
            _is_real_number(v) for v in raw_values
        ):
            raise LegacyQdrantDecodeError("SparseVector.values must be a list of numbers")
        self.indices = tuple(int(i) for i in raw_indices)
        self.values = tuple(float(v) for v in raw_values)


def _validate_safe_payload_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise LegacyQdrantDecodeError("Legacy Qdrant payload exceeds maximum nesting depth")
    if value is None or isinstance(value, (bool, str)):
        return value
    if _is_real_number(value):
        return value
    if isinstance(value, _SafeUUIDStub):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_validate_safe_payload_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise LegacyQdrantDecodeError(
                    f"Legacy Qdrant payload keys must be strings, got {type(k).__name__}"
                )
            cleaned[k] = _validate_safe_payload_value(v, depth=depth + 1)
        return cleaned
    raise LegacyQdrantDecodeError(
        f"Unsupported value type in legacy Qdrant payload: {type(value).__name__}"
    )


def _validate_point_fields(fields: Mapping[str, Any], *, allow_numpy: bool = False) -> dict[str, Any]:
    unknown_keys = set(fields.keys()) - _EXPECTED_POINT_KEYS
    if unknown_keys:
        raise LegacyQdrantDecodeError(
            f"Unexpected fields in legacy PointStruct: {sorted(unknown_keys)}"
        )
    raw_id = fields.get("id")
    if isinstance(raw_id, bool) or not isinstance(
        raw_id, (str, int, uuid.UUID, _SafeUUIDStub)
    ):
        raise LegacyQdrantDecodeError(
            f"Invalid PointStruct.id type: {type(raw_id).__name__}"
        )

    raw_payload = fields.get("payload")
    if raw_payload is None:
        validated_payload: dict[str, Any] = {}
    elif isinstance(raw_payload, dict):
        validated_payload = _validate_safe_payload_value(raw_payload)
    else:
        raise LegacyQdrantDecodeError(
            f"Invalid PointStruct.payload type: {type(raw_payload).__name__}"
        )

    raw_vector = fields.get("vector")
    validated_vector = _validate_raw_vector_structure(raw_vector, allow_numpy=allow_numpy)
    return {
        "id": str(raw_id).strip(),
        "payload": validated_payload,
        "vector": validated_vector,
    }


def _validate_raw_vector_structure(raw_vector: Any, *, allow_numpy: bool = False) -> Any:
    if raw_vector is None or isinstance(raw_vector, _QdrantSparseVectorStub):
        return None
    if allow_numpy:
        import numpy as np

        if isinstance(raw_vector, np.ndarray):
            if raw_vector.ndim != 1 or not np.issubdtype(raw_vector.dtype, np.number):
                raise LegacyQdrantDecodeError("Invalid numpy vector shape or dtype")
            return [float(x) for x in raw_vector.tolist()]
    if isinstance(raw_vector, (list, tuple)):
        if not all(_is_real_number(x) for x in raw_vector):
            raise LegacyQdrantDecodeError("Dense vector must contain only numeric values")
        return [float(x) for x in raw_vector]
    if isinstance(raw_vector, dict):
        cleaned: dict[str, list[float]] = {}
        for k, v in raw_vector.items():
            if not isinstance(k, str):
                raise LegacyQdrantDecodeError("Named vector dictionary keys must be strings")
            if isinstance(v, _QdrantSparseVectorStub) or v is None:
                continue
            sub = _validate_raw_vector_structure(v, allow_numpy=allow_numpy)
            if isinstance(sub, list):
                cleaned[k] = sub
        return cleaned
    raise LegacyQdrantDecodeError(
        f"Unsupported PointStruct.vector type: {type(raw_vector).__name__}"
    )


class _QdrantPointStructStub:
    """Strict structural stub for legacy ``qdrant_client`` ``PointStruct``."""

    __slots__ = ("fields",)

    def __new__(cls) -> _QdrantPointStructStub:
        inst = super().__new__(cls)
        inst.fields = None
        return inst

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args or kwargs:
            raise UnsafeLegacyQdrantDataError(
                "Direct PointStruct constructor arguments are not permitted"
            )

    def __setstate__(self, state: Any) -> None:
        if not isinstance(state, dict):
            raise LegacyQdrantDecodeError("Invalid PointStruct pickle state")
        if "__dict__" in state:
            unknown_outer = set(state.keys()) - _EXPECTED_PYDANTIC_STATE_KEYS
            if unknown_outer:
                raise LegacyQdrantDecodeError(
                    f"Unexpected outer keys in PointStruct state: {sorted(unknown_outer)}"
                )
            raw_fields = state["__dict__"]
        else:
            raw_fields = state
        if not isinstance(raw_fields, dict):
            raise LegacyQdrantDecodeError("Invalid PointStruct __dict__ state")
        self.fields = raw_fields


_ALLOWED_LEGACY_PICKLE_GLOBALS: dict[tuple[str, str], Any] = {
    ("qdrant_client.http.models.models", "PointStruct"): _QdrantPointStructStub,
    ("qdrant_client.models", "PointStruct"): _QdrantPointStructStub,
    ("qdrant_client.conversions.common_types", "PointStruct"): _QdrantPointStructStub,
    ("qdrant_client.http.models.models", "SparseVector"): _QdrantSparseVectorStub,
    ("qdrant_client.models", "SparseVector"): _QdrantSparseVectorStub,
    ("builtins", "set"): _safe_set,
    ("__builtin__", "set"): _safe_set,
    ("builtins", "frozenset"): _safe_frozenset,
    ("__builtin__", "frozenset"): _safe_frozenset,
    ("uuid", "UUID"): _SafeUUIDStub,
    ("uuid", "SafeUUID"): uuid.SafeUUID,
    ("datetime", "datetime"): _dt.datetime,
    ("datetime", "date"): _dt.date,
    ("datetime", "timezone"): _dt.timezone,
    ("datetime", "timedelta"): _dt.timedelta,
}

_TRUSTED_EXTRA_PICKLE_GLOBALS: tuple[tuple[str, str], ...] = (
    ("collections", "OrderedDict"),
    ("decimal", "Decimal"),
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy", "ndarray"),
    ("numpy", "dtype"),
)


class _QdrantSafeUnpickler(pickle.Unpickler):
    """Strict exact-symbol unpickler for automatic legacy Qdrant PointStruct migration."""

    def find_class(self, module: str, name: str) -> Any:
        allowed = _ALLOWED_LEGACY_PICKLE_GLOBALS.get((module, name))
        if allowed is not None:
            return allowed
        raise UnsafeLegacyQdrantDataError(
            f"Blocked unsupported pickle global: {module}.{name}"
        )

    def persistent_load(self, pid: Any) -> Any:
        raise UnsafeLegacyQdrantDataError(
            f"Blocked unsupported pickle persistent_load: {pid!r}"
        )


class _TrustedLegacyQdrantUnpickler(_QdrantSafeUnpickler):
    """Extended unpickler used ONLY in explicit user-initiated trusted migrations."""

    def find_class(self, module: str, name: str) -> Any:
        allowed = _ALLOWED_LEGACY_PICKLE_GLOBALS.get((module, name))
        if allowed is not None:
            return allowed
        if (module, name) in _TRUSTED_EXTRA_PICKLE_GLOBALS:
            return pickle.Unpickler.find_class(self, module, name)
        raise UnsafeLegacyQdrantDataError(
            f"Blocked unsupported pickle global even in trusted mode: {module}.{name}"
        )


def decode_legacy_qdrant_point(
    blob: bytes | bytearray | memoryview,
    *,
    row_key: Any = None,
    expected_dims: int = 384,
    trusted_source: bool = False,
) -> dict[str, Any]:
    """Decode and validate a single pickled Qdrant PointStruct blob."""
    if not isinstance(blob, (bytes, bytearray, memoryview)) or len(blob) == 0:
        raise LegacyQdrantDecodeError(f"Point row {row_key!r} does not contain a non-empty BLOB")

    unpickler_cls = _TrustedLegacyQdrantUnpickler if trusted_source else _QdrantSafeUnpickler
    try:
        decoded = unpickler_cls(io.BytesIO(bytes(blob))).load()
    except UnsafeLegacyQdrantDataError:
        raise
    except Exception as exc:
        raise LegacyQdrantDecodeError(
            f"Failed to unpickle Qdrant point {row_key!r}: {type(exc).__name__}: {exc}"
        ) from exc

    if isinstance(decoded, _QdrantPointStructStub):
        if not isinstance(decoded.fields, dict):
            raise LegacyQdrantDecodeError(
                f"PointStruct {row_key!r} has uninitialized fields"
            )
        raw_fields: Mapping[str, Any] = decoded.fields
    elif isinstance(decoded, dict):
        raw_fields = decoded
    else:
        raise LegacyQdrantDecodeError(
            f"Top-level pickled object for {row_key!r} must be PointStruct, got {type(decoded).__name__}"
        )

    validated = _validate_point_fields(raw_fields, allow_numpy=trusted_source)
    point_id = validated["id"] or str(row_key or "").strip()
    if not point_id:
        raise LegacyQdrantDecodeError("Decoded Qdrant point has an empty id")
    vector = _extract_vector_from_point(validated["vector"], expected_dims=expected_dims)
    return {
        "id": point_id,
        "payload": validated["payload"],
        "vector": vector,
    }


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
    if _is_real_number(value):
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
