"""Lifecycle hub for registering, migrating, inspecting, and closing storage backends."""

from __future__ import annotations

import threading
from typing import TypeVar

from core.storage.layout import StorageLayout
from sdk.adapters.storage import BackendStatus, ManagedBackend, Migratable

B = TypeVar("B", bound=ManagedBackend)


class StorageHub:
    """Central lifecycle owner for registered file stores and database engines."""

    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout
        self._lock = threading.RLock()
        self._backends: dict[str, ManagedBackend] = {}
        self._closed = False

    def register(self, backend: B) -> B:
        """Register a managed backend under its unique logical name."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot register backend after StorageHub is closed")
            backend_name = str(getattr(backend, "name", "") or "").strip()
            if not backend_name:
                raise ValueError("Backend name must not be empty")
            if backend_name in self._backends:
                raise ValueError(f"Duplicate storage backend: {backend_name}")
            self._backends[backend_name] = backend
            return backend

    def get_backend(self, name: str) -> ManagedBackend | None:
        with self._lock:
            return self._backends.get(name)

    @property
    def backends(self) -> tuple[ManagedBackend, ...]:
        with self._lock:
            return tuple(self._backends.values())

    def migrate_all(self) -> None:
        """Run startup migrations in registration order."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot migrate StorageHub after it is closed")
            targets = list(self._backends.values())
        for backend in targets:
            if isinstance(backend, Migratable):
                backend.migrate()

    def statuses(self) -> tuple[BackendStatus, ...]:
        """Collect health snapshots from every registered backend."""
        with self._lock:
            targets = list(self._backends.values())
        results: list[BackendStatus] = []
        for backend in targets:
            try:
                results.append(backend.status())
            except Exception as exc:
                results.append(
                    BackendStatus(
                        name=str(getattr(backend, "name", "unknown")),
                        kind="memory",
                        location="",
                        healthy=False,
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
        return tuple(results)

    def close_all(self) -> None:
        """Idempotently close all backends in reverse registration order."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            targets = list(reversed(list(self._backends.values())))
        first_error: Exception | None = None
        for backend in targets:
            try:
                backend.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


__all__ = ["StorageHub"]
