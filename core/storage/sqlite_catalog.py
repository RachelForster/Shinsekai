"""Generic SQLite CatalogStore using indexed query columns plus payload_json."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import copy
from dataclasses import dataclass
import re
import sqlite3
import time
from typing import Generic, Literal, TypeVar
from uuid import uuid4

from core.storage.sqlite_engine import SqliteEngine
from sdk.adapters.storage import BackendStatus, Codec

T = TypeVar("T")

SqlColumnType = Literal["TEXT", "INTEGER", "REAL"]
_VALID_SQL_TYPES = frozenset({"TEXT", "INTEGER", "REAL"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_COLUMNS = frozenset({"id", "sort_order", "payload_json", "updated_at"})


def _validate_identifier(value: str, *, kind: str) -> str:
    cleaned = str(value or "").strip()
    if not _IDENTIFIER_RE.match(cleaned):
        raise ValueError(f"Invalid SQL {kind} identifier: {value!r}")
    return cleaned


def _clone_value(value: T) -> T:
    model_copy = getattr(value, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class IndexedColumn(Generic[T]):
    """Declared SQLite index column projected from a catalog entity."""

    name: str
    extractor: Callable[[T], str | int | float]
    sql_type: SqlColumnType = "TEXT"
    unique: bool = False
    nocase: bool = False

    def __post_init__(self) -> None:
        cleaned = _validate_identifier(self.name, kind="column")
        if cleaned in _RESERVED_COLUMNS:
            raise ValueError(f"Column name {cleaned!r} is reserved by SqliteCatalogStore")
        object.__setattr__(self, "name", cleaned)
        if self.sql_type not in _VALID_SQL_TYPES:
            raise ValueError(f"Unsupported SQL column type: {self.sql_type!r}")
        if self.nocase and self.sql_type != "TEXT":
            raise ValueError("COLLATE NOCASE is only supported on TEXT columns")


def _validate_order_by(order_by: str, allowed_columns: set[str]) -> str:
    clauses: list[str] = []
    for raw_clause in str(order_by or "").split(","):
        parts = raw_clause.strip().split()
        if not parts or len(parts) > 2:
            raise ValueError(f"Invalid ORDER BY clause: {order_by!r}")
        column = _validate_identifier(parts[0], kind="order_by column")
        if column not in allowed_columns:
            raise ValueError(f"Unknown ORDER BY column: {column!r}")
        direction = parts[1].upper() if len(parts) == 2 else "ASC"
        if direction not in {"ASC", "DESC"}:
            raise ValueError(f"Invalid ORDER BY direction: {direction!r}")
        clauses.append(f"{column} {direction}")
    if not clauses:
        raise ValueError("ORDER BY must contain at least one column")
    return ", ".join(clauses)


class SqliteCatalogStore(Generic[T]):
    """Keyed SQLite collection storing indexed columns alongside full JSON payloads."""

    def __init__(
        self,
        engine: SqliteEngine,
        *,
        name: str,
        table: str,
        codec: Codec[T],
        key_of: Callable[[T], str],
        indexed_columns: Sequence[IndexedColumn[T]] = (),
        order_by: str = "sort_order ASC, id ASC",
        revision_filter: Callable[[T, T], bool] | None = None,
    ) -> None:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("Catalog store name must not be empty")
        cleaned_table = _validate_identifier(table, kind="table")
        if cleaned_table == "_catalog_meta":
            raise ValueError("Table name '_catalog_meta' is reserved")

        seen_columns: set[str] = set()
        validated_columns: list[IndexedColumn[T]] = []
        for column in indexed_columns:
            if column.name in seen_columns:
                raise ValueError(f"Duplicate indexed column: {column.name!r}")
            seen_columns.add(column.name)
            validated_columns.append(column)

        allowed_order_columns = {"id", "sort_order", "updated_at", *seen_columns}
        self._engine = engine
        self._name = cleaned_name
        self._table = cleaned_table
        self._codec = codec
        self._key_of = key_of
        self._columns = tuple(validated_columns)
        self._column_names = frozenset(seen_columns)
        self._order_by = _validate_order_by(order_by, allowed_order_columns)
        self._revision_filter = revision_filter

    @property
    def name(self) -> str:
        return self._name

    @property
    def table(self) -> str:
        return self._table

    def migrate(self) -> None:
        """Create the catalog table, metadata revision row, and column indexes."""
        column_defs = ["id TEXT PRIMARY KEY"]
        for col in self._columns:
            collate = " COLLATE NOCASE" if col.nocase else ""
            unique = " UNIQUE" if col.unique else ""
            column_defs.append(f"{col.name} {col.sql_type} NOT NULL{collate}{unique}")
        column_defs.extend(
            (
                "sort_order INTEGER NOT NULL DEFAULT 0",
                "payload_json TEXT NOT NULL",
                "updated_at REAL NOT NULL",
            )
        )
        create_table_sql = (
            f"CREATE TABLE IF NOT EXISTS {self._table} ({', '.join(column_defs)})"
        )
        with self._engine.write_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS _catalog_meta (
                    table_name TEXT PRIMARY KEY,
                    revision TEXT NOT NULL
                )
                """
            )
            connection.execute(create_table_sql)
            for col in self._columns:
                if not col.unique:
                    connection.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._table}_{col.name} "
                        f"ON {self._table}({col.name})"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO _catalog_meta(table_name, revision) VALUES (?, ?)",
                (self._table, uuid4().hex),
            )

    @property
    def revision(self) -> str:
        with self._engine.read_connection() as connection:
            try:
                row = connection.execute(
                    "SELECT revision FROM _catalog_meta WHERE table_name = ?",
                    (self._table,),
                ).fetchone()
            except sqlite3.OperationalError:
                return ""
            return str(row["revision"]) if row is not None else ""

    def get(self, key: str) -> T | None:
        with self._engine.read_connection() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._table} WHERE id = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._codec.decode(str(row["payload_json"]).encode("utf-8"))

    def get_by_column(self, column_name: str, value: str | int | float) -> T | None:
        cleaned = _validate_identifier(column_name, kind="column")
        if cleaned not in self._column_names:
            raise ValueError(f"Unknown indexed column {column_name!r} for table {self._table!r}")
        with self._engine.read_connection() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._table} WHERE {cleaned} = ? LIMIT 1",
                (value,),
            ).fetchone()
        if row is None:
            return None
        return self._codec.decode(str(row["payload_json"]).encode("utf-8"))

    def list_all(self) -> tuple[T, ...]:
        with self._engine.read_connection() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._table} ORDER BY {self._order_by}"
            ).fetchall()
        return tuple(
            self._codec.decode(str(row["payload_json"]).encode("utf-8"))
            for row in rows
        )

    def put(self, key: str, item: T) -> str:
        with self._engine.write_connection() as connection:
            return self._put_locked(connection, key, item)

    def patch(self, key: str, mutator: Callable[[T], T]) -> T:
        with self._engine.write_connection() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._table} WHERE id = ?",
                (key,),
            ).fetchone()
            if row is None:
                raise KeyError(key)
            current = self._codec.decode(str(row["payload_json"]).encode("utf-8"))
            updated = mutator(current)
            self._put_locked(connection, key, updated)
            return _clone_value(updated)

    def delete(self, key: str) -> bool:
        with self._engine.write_connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM {self._table} WHERE id = ?",
                (key,),
            )
            if cursor.rowcount > 0:
                self._bump_revision_locked(connection)
                return True
            return False

    def status(self) -> BackendStatus:
        engine_status = self._engine.status()
        if not engine_status.healthy:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=engine_status.location,
                healthy=False,
                schema_version=engine_status.schema_version,
                detail=engine_status.detail,
            )
        try:
            with self._engine.read_connection() as connection:
                count = int(
                    connection.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]
                )
        except sqlite3.OperationalError as exc:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=engine_status.location,
                healthy=False,
                schema_version=engine_status.schema_version,
                detail=f"unmigrated ({self._table}): {exc}",
            )
        return BackendStatus(
            name=self._name,
            kind="sqlite",
            location=engine_status.location,
            healthy=True,
            schema_version=engine_status.schema_version,
            detail=f"table={self._table} rows={count}",
        )

    def close(self) -> None:
        # Shared SqliteEngine owns connection closing via reverse close_all() order.
        return None

    def _bump_revision_locked(self, connection: sqlite3.Connection) -> str:
        new_revision = uuid4().hex
        connection.execute(
            """
            INSERT INTO _catalog_meta(table_name, revision)
            VALUES (?, ?)
            ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
            """,
            (self._table, new_revision),
        )
        return new_revision

    def _current_revision_locked(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT revision FROM _catalog_meta WHERE table_name = ?",
            (self._table,),
        ).fetchone()
        if row is not None:
            return str(row["revision"])
        return self._bump_revision_locked(connection)

    def _put_locked(self, connection: sqlite3.Connection, key: str, item: T) -> str:
        item_key = self._key_of(item)
        if item_key != key:
            raise ValueError(f"Key {key!r} does not match item key {item_key!r}")
        payload_text = self._codec.encode(item).decode("utf-8")
        indexed_values = [col.extractor(item) for col in self._columns]
        now = time.time()

        existing = connection.execute(
            f"SELECT sort_order, payload_json FROM {self._table} WHERE id = ?",
            (key,),
        ).fetchone()
        if existing is None:
            next_order = int(
                connection.execute(
                    f"SELECT COALESCE(MAX(sort_order) + 1, 0) FROM {self._table}"
                ).fetchone()[0]
            )
            col_names = ["id", *(col.name for col in self._columns), "sort_order", "payload_json", "updated_at"]
            placeholders = ", ".join("?" for _ in col_names)
            connection.execute(
                f"INSERT INTO {self._table} ({', '.join(col_names)}) VALUES ({placeholders})",
                (key, *indexed_values, next_order, payload_text, now),
            )
            return self._bump_revision_locked(connection)

        should_bump = True
        if self._revision_filter is not None:
            previous_item = self._codec.decode(str(existing["payload_json"]).encode("utf-8"))
            should_bump = bool(self._revision_filter(previous_item, item))

        assignments = [*(f"{col.name} = ?" for col in self._columns), "payload_json = ?", "updated_at = ?"]
        connection.execute(
            f"UPDATE {self._table} SET {', '.join(assignments)} WHERE id = ?",
            (*indexed_values, payload_text, now, key),
        )
        if should_bump:
            return self._bump_revision_locked(connection)
        return self._current_revision_locked(connection)


__all__ = ["IndexedColumn", "SqlColumnType", "SqliteCatalogStore"]
