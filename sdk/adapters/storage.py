"""Narrow SOLID ports for unified storage management and typed persistence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
K = TypeVar("K", contravariant=True)

BackendKind = Literal["yaml", "json", "sqlite", "memory"]


@dataclass(frozen=True, slots=True)
class BackendStatus:
    """Observability snapshot reported by any managed storage backend."""

    name: str
    kind: BackendKind
    location: str
    healthy: bool = True
    schema_version: int | None = None
    detail: str = ""


@runtime_checkable
class ManagedBackend(Protocol):
    """Minimal lifecycle contract shared by all storage engines and stores."""

    @property
    def name(self) -> str:
        """Unique logical backend identifier (e.g. 'settings.api', 'db.main')."""

    def status(self) -> BackendStatus:
        """Return current health, physical path, and schema version."""

    def close(self) -> None:
        """Release file locks, flush WAL checkpoints, or close DB connections."""


@runtime_checkable
class Migratable(Protocol):
    """Segregated capability for backends requiring schema or data migration."""

    def migrate(self) -> None:
        """Idempotently upgrade storage to the current schema version."""


@runtime_checkable
class Codec(Protocol[T]):
    """Pure in-memory serializer/validator separating format compatibility from models."""

    def decode(self, raw: bytes) -> T: ...

    def encode(self, value: T) -> bytes: ...

    def default(self) -> T: ...


@runtime_checkable
class ReadableDocument(Protocol[T_co]):
    """Read-only whole-document view for AI and runtime consumers."""

    @property
    def revision(self) -> str:
        """Opaque revision token; changes only when persisted content changes."""

    def get(self) -> T_co:
        """Return an immutable value or safe snapshot of the current document."""


@runtime_checkable
class DocumentStore(ReadableDocument[T], Protocol[T]):
    """Mutable whole-document port for settings and UI runtime state."""

    def save(self, value: T) -> str:
        """Validate and atomically persist value; return new revision."""

    def update(self, mutator: Callable[[T], T]) -> T:
        """Atomically load, mutate, validate, and persist under store lock."""


@runtime_checkable
class ReadableCatalog(Protocol[K, T_co]):
    """Read-only keyed entity collection port."""

    @property
    def revision(self) -> str:
        """Opaque catalog revision token updated on persisted structural changes."""

    def get(self, key: K) -> T_co | None:
        """Return one entity snapshot by key, or None if missing."""

    def list_all(self) -> tuple[T_co, ...]:
        """Return all stored entity snapshots in deterministic catalog order."""


@runtime_checkable
class CatalogStore(ReadableCatalog[K, T], Protocol[K, T]):
    """Keyed entity collection supporting single-item atomic writes."""

    def put(self, key: K, item: T) -> str:
        """Insert or replace one entity without rewriting unrelated items."""

    def patch(self, key: K, mutator: Callable[[T], T]) -> T:
        """Atomically update one entity in place; raise KeyError if missing."""

    def delete(self, key: K) -> bool:
        """Delete one entity by key; return True if it existed."""


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction scope across repositories sharing one SQLite engine."""

    def atomic(self) -> AbstractContextManager[None]:
        """Execute all participating repository writes in one atomic transaction."""


__all__ = [
    "BackendKind",
    "BackendStatus",
    "CatalogStore",
    "Codec",
    "DocumentStore",
    "ManagedBackend",
    "Migratable",
    "ReadableCatalog",
    "ReadableDocument",
    "UnitOfWork",
]
