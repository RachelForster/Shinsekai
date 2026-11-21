"""Thread-safe atomic file-backed DocumentStore with stat-based caching."""

from __future__ import annotations

from collections.abc import Callable
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from typing import Generic, TypeVar

from sdk.adapters.storage import BackendKind, BackendStatus, Codec
from sdk.file_io import durable_mkdir, durable_rename
from sdk.path_utils import resolve_regular_path

T = TypeVar("T")

_MISSING_STAT = (-1, -1)


def _clone_value(value: T) -> T:
    model_copy = getattr(value, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    return copy.deepcopy(value)


class FileDocumentStore(Generic[T]):
    """Atomic file-backed DocumentStore supporting YAML and JSON codecs."""

    def __init__(
        self,
        name: str,
        path: str | os.PathLike[str],
        codec: Codec[T],
        *,
        kind: BackendKind | None = None,
    ) -> None:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("Store name must not be empty")
        self._name = cleaned_name
        self._path = resolve_regular_path(os.fspath(path))
        self._codec = codec
        if kind is not None:
            self._kind: BackendKind = kind
        else:
            self._kind = "json" if self._path.suffix.lower() == ".json" else "yaml"
        self._lock = threading.RLock()
        self._cached_stat: tuple[int, int] | None = None
        self._cached_value: T | None = None
        self._cached_revision: str = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> Path:
        return self._path

    @property
    def revision(self) -> str:
        with self._lock:
            _, current_revision = self._load_locked()
            return current_revision

    def get(self) -> T:
        with self._lock:
            value, _ = self._load_locked()
            return _clone_value(value)

    def save(self, value: T) -> str:
        with self._lock:
            return self._save_locked(value)

    def update(self, mutator: Callable[[T], T]) -> T:
        with self._lock:
            current, _ = self._load_locked()
            updated = mutator(_clone_value(current))
            self._save_locked(updated)
            return _clone_value(updated)

    def status(self) -> BackendStatus:
        with self._lock:
            exists = self._path.is_file()
            try:
                self._load_locked()
            except Exception as exc:
                return BackendStatus(
                    name=self._name,
                    kind=self._kind,
                    location=str(self._path),
                    healthy=False,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            return BackendStatus(
                name=self._name,
                kind=self._kind,
                location=str(self._path),
                healthy=True,
                detail="exists" if exists else "default",
            )

    def close(self) -> None:
        with self._lock:
            self._cached_stat = None
            self._cached_value = None
            self._cached_revision = ""

    @staticmethod
    def _revision_for_bytes(encoded: bytes) -> str:
        return hashlib.sha256(encoded).hexdigest()

    def _load_locked(self) -> tuple[T, str]:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            if self._cached_stat == _MISSING_STAT and self._cached_value is not None:
                return self._cached_value, self._cached_revision
            value = self._codec.default()
            rev = self._revision_for_bytes(self._codec.encode(value))
            self._cached_stat = _MISSING_STAT
            self._cached_value = value
            self._cached_revision = rev
            return value, rev

        signature = (stat.st_mtime_ns, stat.st_size)
        if self._cached_stat == signature and self._cached_value is not None:
            return self._cached_value, self._cached_revision

        raw = self._path.read_bytes()
        value = self._codec.decode(raw)
        rev = self._revision_for_bytes(self._codec.encode(value))
        self._cached_stat = signature
        self._cached_value = value
        self._cached_revision = rev
        return value, rev

    def _save_locked(self, value: T) -> str:
        encoded = self._codec.encode(value)
        revision = self._revision_for_bytes(encoded)
        durable_mkdir(self._path.parent)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            durable_rename(temporary_path, self._path, replace=True)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        stat = self._path.stat()
        self._cached_stat = (stat.st_mtime_ns, stat.st_size)
        self._cached_value = _clone_value(value)
        self._cached_revision = revision
        return revision


__all__ = ["FileDocumentStore"]
