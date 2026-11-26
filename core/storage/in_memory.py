"""In-memory test doubles implementing DocumentStore, CatalogStore, and UnitOfWork."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
import copy
import hashlib
import threading
from typing import Any, Generic, Iterator, TypeVar
from uuid import uuid4

from sdk.adapters.storage import BackendStatus, Codec

T = TypeVar("T")
K = TypeVar("K")


def _clone_value(value: T) -> T:
    model_copy = getattr(value, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    return copy.deepcopy(value)


class NoopUnitOfWork:
    """In-memory UnitOfWork placeholder for isolated unit tests."""

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield


class InMemoryDocumentStore(Generic[T]):
    """Thread-safe in-memory DocumentStore mirroring FileDocumentStore snapshot semantics."""

    def __init__(
        self,
        name: str,
        default_factory: Callable[[], T],
        *,
        initial: T | None = None,
        codec: Codec[T] | None = None,
    ) -> None:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("Store name must not be empty")
        self._name = cleaned_name
        self._default_factory = default_factory
        self._codec = codec
        self._lock = threading.RLock()
        self._value: T = _clone_value(initial) if initial is not None else default_factory()
        self._revision: str = self._compute_revision(self._value)

    @property
    def name(self) -> str:
        return self._name

    @property
    def revision(self) -> str:
        with self._lock:
            return self._revision

    def get(self) -> T:
        with self._lock:
            return _clone_value(self._value)

    def save(self, value: T) -> str:
        with self._lock:
            new_rev = self._compute_revision(value, previous=self._value)
            self._value = _clone_value(value)
            self._revision = new_rev
            return self._revision

    def update(self, mutator: Callable[[T], T]) -> T:
        with self._lock:
            updated = mutator(_clone_value(self._value))
            self.save(updated)
            return _clone_value(updated)

    def status(self) -> BackendStatus:
        return BackendStatus(
            name=self._name,
            kind="memory",
            location="memory://document",
            healthy=True,
        )

    def close(self) -> None:
        return None

    def _compute_revision(self, value: T, *, previous: T | None = None) -> str:
        if self._codec is not None:
            return hashlib.sha256(self._codec.encode(value)).hexdigest()
        if previous is not None and value == previous and self._revision:
            return self._revision
        return uuid4().hex


class InMemoryCatalogStore(Generic[K, T]):
    """Thread-safe in-memory CatalogStore preserving insertion order and unique indexes."""

    def __init__(
        self,
        name: str,
        *,
        key_of: Callable[[T], K] | None = None,
        unique_indexes: Mapping[str, Callable[[T], Any]] | None = None,
        case_insensitive_indexes: frozenset[str] = frozenset(),
        revision_filter: Callable[[T, T], bool] | None = None,
    ) -> None:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("Catalog store name must not be empty")
        self._name = cleaned_name
        self._key_of = key_of
        self._unique_indexes = dict(unique_indexes or {})
        self._case_insensitive = frozenset(case_insensitive_indexes)
        self._revision_filter = revision_filter
        self._lock = threading.RLock()
        self._items: dict[K, T] = {}
        self._revision = uuid4().hex

    @property
    def name(self) -> str:
        return self._name

    @property
    def revision(self) -> str:
        with self._lock:
            return self._revision

    def get(self, key: K) -> T | None:
        with self._lock:
            item = self._items.get(key)
            return None if item is None else _clone_value(item)

    def get_by_column(self, column_name: str, value: Any) -> T | None:
        extractor = self._unique_indexes.get(column_name)
        if extractor is None:
            raise ValueError(f"Unknown indexed column: {column_name!r}")
        target = self._normalize_index_value(column_name, value)
        with self._lock:
            for item in self._items.values():
                if self._normalize_index_value(column_name, extractor(item)) == target:
                    return _clone_value(item)
            return None

    def list_all(self) -> tuple[T, ...]:
        with self._lock:
            return tuple(_clone_value(item) for item in self._items.values())

    def put(self, key: K, item: T) -> str:
        if self._key_of is not None:
            actual_key = self._key_of(item)
            if actual_key != key:
                raise ValueError(f"Key {key!r} does not match item key {actual_key!r}")
        with self._lock:
            self._check_unique_indexes(key, item)
            previous = self._items.get(key)
            should_bump = True
            if previous is not None and self._revision_filter is not None:
                should_bump = bool(self._revision_filter(previous, item))
            self._items[key] = _clone_value(item)
            if should_bump:
                self._revision = uuid4().hex
            return self._revision

    def patch(self, key: K, mutator: Callable[[T], T]) -> T:
        with self._lock:
            current = self._items.get(key)
            if current is None:
                raise KeyError(key)
            updated = mutator(_clone_value(current))
            self.put(key, updated)
            return _clone_value(updated)

    def delete(self, key: K) -> bool:
        with self._lock:
            existed = self._items.pop(key, None) is not None
            if existed:
                self._revision = uuid4().hex
            return existed

    def status(self) -> BackendStatus:
        with self._lock:
            count = len(self._items)
        return BackendStatus(
            name=self._name,
            kind="memory",
            location="memory://catalog",
            healthy=True,
            detail=f"rows={count}",
        )

    def close(self) -> None:
        return None

    def _normalize_index_value(self, column_name: str, value: Any) -> Any:
        if column_name in self._case_insensitive and isinstance(value, str):
            return value.casefold()
        return value

    def _check_unique_indexes(self, key: K, candidate: T) -> None:
        for column_name, extractor in self._unique_indexes.items():
            candidate_val = self._normalize_index_value(column_name, extractor(candidate))
            for existing_key, existing_item in self._items.items():
                if existing_key == key:
                    continue
                existing_val = self._normalize_index_value(column_name, extractor(existing_item))
                if existing_val == candidate_val:
                    raise ValueError(f"UNIQUE constraint failed: {column_name}")


__all__ = ["InMemoryCatalogStore", "InMemoryDocumentStore", "NoopUnitOfWork"]
