"""Shared SQLite engine with WAL concurrency, nested ContextVar transactions, and migrations."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import threading
from typing import Literal

from sdk.adapters.storage import BackendStatus
from sdk.file_io import durable_mkdir
from sdk.path_utils import resolve_regular_path

SynchronousMode = Literal["OFF", "NORMAL", "FULL", "EXTRA"]
_VALID_SYNCHRONOUS_MODES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})


@dataclass(frozen=True, slots=True)
class SqliteMigration:
    """Versioned idempotent SQLite schema or data migration step."""

    version: int
    description: str
    up: str | Callable[[sqlite3.Connection], None]


def _iter_sql_statements(sql: str) -> list[str]:
    """Split SQL text into executable statements without invoking executescript's implicit COMMIT."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            stripped = candidate.strip()
            if stripped:
                statements.append(stripped)
            buffer.clear()
    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


class SqliteEngine:
    """Single-responsibility SQLite engine implementing ManagedBackend, Migratable, and UnitOfWork."""

    def __init__(
        self,
        name: str,
        path: str | os.PathLike[str],
        *,
        migrations: Sequence[SqliteMigration] = (),
        busy_timeout_ms: int = 5000,
        synchronous: SynchronousMode = "NORMAL",
        max_idle_connections: int = 8,
    ) -> None:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("SQLite engine name must not be empty")
        sync_mode = str(synchronous).upper()
        if sync_mode not in _VALID_SYNCHRONOUS_MODES:
            raise ValueError(f"Unsupported SQLite synchronous mode: {synchronous!r}")

        validated_migrations: list[SqliteMigration] = []
        previous_version = 0
        for migration in migrations:
            if migration.version <= 0 or migration.version <= previous_version:
                raise ValueError(
                    f"Migration versions must be strictly ascending positive integers; got {migration.version}"
                )
            previous_version = migration.version
            validated_migrations.append(migration)

        raw_path = os.fspath(path)
        self._name = cleaned_name
        self._is_memory = raw_path == ":memory:"
        self._path: Path | None = None if self._is_memory else resolve_regular_path(raw_path)
        self._location = ":memory:" if self._is_memory else str(self._path)
        self._migrations = tuple(validated_migrations)
        self._busy_timeout_ms = max(0, int(busy_timeout_ms))
        self._synchronous = sync_mode
        self._max_idle_connections = max(1, int(max_idle_connections))

        self._write_lock = threading.RLock()
        self._conn_lock = threading.Lock()
        self._memory_conn: sqlite3.Connection | None = None
        self._idle_connections: list[sqlite3.Connection] = []
        self._active_connections: set[sqlite3.Connection] = set()
        self._closed = False

        self._tx_depth: ContextVar[int] = ContextVar(f"sqlite_tx_depth_{id(self)}", default=0)
        self._tx_conn: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"sqlite_tx_conn_{id(self)}", default=None
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> Path | None:
        return self._path

    def _open_connection(self) -> sqlite3.Connection:
        if not self._is_memory and self._path is not None:
            durable_mkdir(self._path.parent)
        target = ":memory:" if self._is_memory else str(self._path)
        connection = sqlite3.connect(
            target,
            timeout=self._busy_timeout_ms / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        if not self._is_memory:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(f"PRAGMA synchronous = {self._synchronous}")
        return connection

    @contextmanager
    def _borrow_connection(self) -> Iterator[sqlite3.Connection]:
        if self._is_memory:
            with self._conn_lock:
                if self._closed:
                    raise RuntimeError(f"SQLite engine {self._name!r} is closed")
                if self._memory_conn is None:
                    self._memory_conn = self._open_connection()
                connection = self._memory_conn
            yield connection
            return

        connection: sqlite3.Connection | None = None
        with self._conn_lock:
            if self._closed:
                raise RuntimeError(f"SQLite engine {self._name!r} is closed")
            if self._idle_connections:
                connection = self._idle_connections.pop()
                self._active_connections.add(connection)
        if connection is None:
            connection = self._open_connection()
            with self._conn_lock:
                if self._closed:
                    connection.close()
                    raise RuntimeError(f"SQLite engine {self._name!r} is closed")
                self._active_connections.add(connection)
        try:
            yield connection
        finally:
            should_close = False
            with self._conn_lock:
                self._active_connections.discard(connection)
                if not self._closed and len(self._idle_connections) < self._max_idle_connections:
                    self._idle_connections.append(connection)
                else:
                    should_close = True
            if should_close:
                connection.close()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Run a block inside BEGIN IMMEDIATE (outer) or SAVEPOINT (nested)."""
        depth = self._tx_depth.get()
        if depth == 0:
            with self._write_lock, self._borrow_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                token_depth = self._tx_depth.set(1)
                token_conn = self._tx_conn.set(connection)
                try:
                    yield
                    connection.execute("COMMIT")
                except BaseException:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
                finally:
                    self._tx_conn.reset(token_conn)
                    self._tx_depth.reset(token_depth)
            return

        connection = self._tx_conn.get()
        if connection is None:
            raise RuntimeError("Missing active transaction connection")
        savepoint = f"sp_{depth}"
        connection.execute(f"SAVEPOINT {savepoint}")
        token_depth = self._tx_depth.set(depth + 1)
        try:
            yield
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        except BaseException:
            try:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except sqlite3.Error:
                pass
            raise
        finally:
            self._tx_depth.reset(token_depth)

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Borrow a connection for read queries, reusing any active transaction."""
        active = self._tx_conn.get()
        if active is not None:
            yield active
            return
        if self._is_memory:
            with self._write_lock, self._borrow_connection() as connection:
                yield connection
            return
        with self._borrow_connection() as connection:
            yield connection

    @contextmanager
    def write_connection(self) -> Iterator[sqlite3.Connection]:
        """Enter an atomic write transaction and yield its connection."""
        with self.atomic():
            active = self._tx_conn.get()
            if active is None:
                raise RuntimeError("Missing active write connection")
            yield active

    def schema_version(self) -> int:
        with self.read_connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        """Apply pending migrations atomically and guard against schema downgrades."""
        max_version = self._migrations[-1].version if self._migrations else 0
        with self._write_lock:
            current_version = self.schema_version()
            if current_version > max_version:
                raise RuntimeError(
                    f"Database {self._name!r} schema version {current_version} "
                    f"is newer than supported version {max_version}"
                )
            for migration in self._migrations:
                if migration.version <= current_version:
                    continue
                with self.write_connection() as connection:
                    if isinstance(migration.up, str):
                        for statement in _iter_sql_statements(migration.up):
                            connection.execute(statement)
                    else:
                        migration.up(connection)
                    connection.execute(f"PRAGMA user_version = {int(migration.version)}")
                current_version = migration.version

    def status(self) -> BackendStatus:
        with self._conn_lock:
            if self._closed:
                return BackendStatus(
                    name=self._name,
                    kind="sqlite",
                    location=self._location,
                    healthy=False,
                    detail="closed",
                )
        try:
            version = self.schema_version()
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=self._location,
                healthy=True,
                schema_version=version,
            )
        except Exception as exc:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=self._location,
                healthy=False,
                detail=f"{type(exc).__name__}: {exc}",
            )

    def close(self) -> None:
        with self._write_lock, self._conn_lock:
            if self._closed:
                return
            self._closed = True
            connections = list(self._idle_connections) + list(self._active_connections)
            self._idle_connections.clear()
            self._active_connections.clear()
            if self._memory_conn is not None:
                connections.append(self._memory_conn)
                self._memory_conn = None
        first_error: Exception | None = None
        for connection in connections:
            try:
                connection.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


__all__ = ["SqliteEngine", "SqliteMigration", "SynchronousMode"]
