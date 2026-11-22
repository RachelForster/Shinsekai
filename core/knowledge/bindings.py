"""Persistent character-to-knowledge bindings."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from core.knowledge.coordination import knowledge_operation_lock

if TYPE_CHECKING:
    from core.storage.stores.knowledge_binding_store import SqliteKnowledgeBindingStore

_bound_lock = threading.RLock()
_bound_store: SqliteKnowledgeBindingStore | None = None
_bound_root: Path | None = None


def bind_knowledge_binding_store(
    store: SqliteKnowledgeBindingStore | None,
    *,
    project_root: Path | None = None,
) -> None:
    """Bind or clear the process-default ``shinsekai.db`` knowledge-binding store."""
    global _bound_store, _bound_root
    with _bound_lock:
        _bound_store = store
        _bound_root = project_root.resolve(strict=False) if project_root is not None else None


def _active_bound_store() -> SqliteKnowledgeBindingStore | None:
    if _database_path is not _default_database_path:
        return None
    with _bound_lock:
        store = _bound_store
        root = _bound_root
    if store is None:
        return None
    if root is not None:
        try:
            if Path.cwd().resolve(strict=False) != root:
                return None
        except OSError:
            return None
    return store


def _required(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _normalize_character_names(
    values: list[str],
    field: str,
) -> set[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")

    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field} must contain only strings")

        if not value.strip():
            raise ValueError(f"{field} must not contain empty names")

    return {value.strip() for value in values}


def _default_database_path() -> Path:
    path = Path.cwd() / "data" / "knowledge" / "knowledge.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_database_path = _default_database_path


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_database_path(), timeout=30)
    try:
        with connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_knowledge_bindings (
                    character_name TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (character_name, knowledge_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_bindings_knowledge "
                "ON character_knowledge_bindings(knowledge_id)"
            )
            yield connection
    finally:
        connection.close()


def bind_character_knowledge(character_name: str, knowledge_id: str) -> None:
    if (store := _active_bound_store()) is not None:
        store.bind_character_knowledge(character_name, knowledge_id)
        return
    name = _required(character_name, "character name")
    normalized_knowledge_id = _required(knowledge_id, "knowledge id")
    with knowledge_operation_lock, _connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO character_knowledge_bindings(character_name, knowledge_id) VALUES (?, ?)",
            (name, normalized_knowledge_id),
        )


def list_knowledge_binding_names(knowledge_id: str) -> dict[str, Any]:
    if (store := _active_bound_store()) is not None:
        return store.list_knowledge_binding_names(knowledge_id)
    normalized_knowledge_id = _required(knowledge_id, "knowledge id")
    with _connect() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT character_name FROM character_knowledge_bindings WHERE knowledge_id = ? ORDER BY character_name",
                (normalized_knowledge_id,),
            )
        ]
    return {"knowledge_id": normalized_knowledge_id, "characterNames": names}


def batch_knowledge_bindings(knowledge_id: str, add: list[str], remove: list[str]) -> dict[str, Any]:
    """Apply only the edited names atomically, preserving unrelated bindings."""
    if (store := _active_bound_store()) is not None:
        return store.batch_knowledge_bindings(knowledge_id, add, remove)
    normalized_knowledge_id = _required(knowledge_id, "knowledge id")
    added = _normalize_character_names(add, "add")
    removed = _normalize_character_names(remove, "remove")
    if added & removed:
        raise ValueError("a character cannot be added and removed in the same request")
    with knowledge_operation_lock, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "DELETE FROM character_knowledge_bindings WHERE knowledge_id = ? AND character_name = ?",
            [(normalized_knowledge_id, name) for name in sorted(removed)],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO character_knowledge_bindings(character_name, knowledge_id) VALUES (?, ?)",
            [(name, normalized_knowledge_id) for name in sorted(added)],
        )
        names = [
            row[0]
            for row in connection.execute(
                "SELECT character_name FROM character_knowledge_bindings WHERE knowledge_id = ? ORDER BY character_name",
                (normalized_knowledge_id,),
            )
        ]
    return {"ok": True, "knowledge_id": normalized_knowledge_id, "characterNames": names}


def unbind_character_knowledge(character_name: str, knowledge_id: str) -> bool:
    if (store := _active_bound_store()) is not None:
        return store.unbind_character_knowledge(character_name, knowledge_id)
    name = _required(character_name, "character name")
    normalized_knowledge_id = _required(knowledge_id, "knowledge id")
    with knowledge_operation_lock, _connect() as connection:
        return (
            connection.execute(
                "DELETE FROM character_knowledge_bindings WHERE character_name = ? AND knowledge_id = ?",
                (name, normalized_knowledge_id),
            ).rowcount
            > 0
        )


def list_character_knowledge_bindings(
    character_name: str,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    if (store := _active_bound_store()) is not None:
        return store.list_character_knowledge_bindings(
            character_name, page=page, page_size=page_size
        )
    name = _required(character_name, "character name")
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    with _connect() as connection:
        connection.execute("BEGIN")
        count = connection.execute(
            "SELECT COUNT(*) FROM character_knowledge_bindings WHERE character_name = ?", (name,)
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT knowledge_id, created_at FROM character_knowledge_bindings WHERE character_name = ? "
            "ORDER BY knowledge_id LIMIT ? OFFSET ?",
            (name, page_size, (page - 1) * page_size),
        ).fetchall()
    return {
        "characterName": name,
        "count": count,
        "page": page,
        "pageSize": page_size,
        "bindings": [
            {"knowledge_id": normalized_knowledge_id, "createdAt": created}
            for normalized_knowledge_id, created in rows
        ],
    }


def delete_knowledge_bindings(knowledge_id: str) -> int:
    if (store := _active_bound_store()) is not None:
        return store.delete_knowledge_bindings(knowledge_id)
    normalized_knowledge_id = _required(knowledge_id, "knowledge id")
    with knowledge_operation_lock, _connect() as connection:
        return connection.execute(
            "DELETE FROM character_knowledge_bindings WHERE knowledge_id = ?",
            (normalized_knowledge_id,),
        ).rowcount


def rename_character_bindings(old_name: str, new_name: str) -> None:
    """Move all bindings to the renamed character in one SQLite transaction."""
    if (store := _active_bound_store()) is not None:
        store.rename_character_bindings(old_name, new_name)
        return
    old = _required(old_name, "old character name")
    new = _required(new_name, "new character name")
    if old == new:
        return
    with knowledge_operation_lock, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO character_knowledge_bindings(character_name, knowledge_id, created_at) "
            "SELECT ?, knowledge_id, created_at FROM character_knowledge_bindings WHERE character_name = ? "
            "ON CONFLICT(character_name, knowledge_id) DO UPDATE SET "
            "created_at = MIN(character_knowledge_bindings.created_at, excluded.created_at)",
            (new, old),
        )
        connection.execute(
            "DELETE FROM character_knowledge_bindings WHERE character_name = ?",
            (old,),
        )


def delete_character_bindings(character_name: str) -> None:
    if (store := _active_bound_store()) is not None:
        store.delete_character_bindings(character_name)
        return
    name = _required(character_name, "character name")
    with knowledge_operation_lock, _connect() as connection:
        connection.execute(
            "DELETE FROM character_knowledge_bindings WHERE character_name = ?", (name,)
        )


def list_knowledge_ids_for_characters(character_names: Iterable[str]) -> list[str]:
    if (store := _active_bound_store()) is not None:
        return store.list_knowledge_ids_for_characters(character_names)
    names: set[str] = set()
    for character_name in character_names:
        name = str(character_name or "").strip()
        if name:
            names.add(name)
    if not names:
        return []
    placeholders = ",".join("?" for _ in names)
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT DISTINCT knowledge_id FROM character_knowledge_bindings WHERE character_name IN ({placeholders})",
            sorted(names),
        ).fetchall()
    knowledge_ids: list[str] = []
    for row in rows:
        if not row:
            continue
        knowledge_id = str(row[0])
        if knowledge_id.strip():
            knowledge_ids.append(knowledge_id)
    return sorted(knowledge_ids)


def get_knowledge_binding_counts() -> dict[str, int]:
    if (store := _active_bound_store()) is not None:
        return store.get_knowledge_binding_counts()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT knowledge_id, COUNT(*) FROM character_knowledge_bindings GROUP BY knowledge_id"
        ).fetchall()
    return {str(normalized_knowledge_id): int(count) for normalized_knowledge_id, count in rows}
