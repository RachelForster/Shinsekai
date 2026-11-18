"""Restricted pickle unpickler and structural point validation for legacy Qdrant."""

from __future__ import annotations

from collections.abc import Mapping
import datetime as _dt
import io
import pickle
from typing import Any
import uuid

from core.vector_store.sqlite_hybrid_store import normalize_vector

from ai.memory.migration.errors import (
    LegacyQdrantDecodeError,
    UnsafeLegacyQdrantDataError,
)

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
