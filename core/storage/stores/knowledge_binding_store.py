"""SQLite-backed character-to-knowledge binding store using stable ``character_id`` FKs."""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Any

from config.models import SELF_PERSONA_ID, is_self_persona_name
from core.knowledge.coordination import knowledge_operation_lock
from core.storage.sqlite_engine import SqliteEngine
from core.storage.stores.character_store import SqliteCharacterCatalog
from sdk.adapters.storage import BackendStatus


def _required(value: str, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _normalize_character_names(values: list[str], field: str) -> set[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field} must contain only strings")
        if not value.strip():
            raise ValueError(f"{field} must not contain empty names")
    return {value.strip() for value in values}


class SqliteKnowledgeBindingStore:
    """Persist character knowledge bindings against immutable ``characters.id`` keys."""

    def __init__(
        self,
        engine: SqliteEngine,
        *,
        characters: SqliteCharacterCatalog | None = None,
        name: str = "bindings.knowledge",
    ) -> None:
        self._engine = engine
        self._characters = characters
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def migrate(self) -> None:
        with self._engine.write_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_knowledge_bindings (
                    character_id  TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    knowledge_id  TEXT NOT NULL,
                    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (character_id, knowledge_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_knowledge_id "
                "ON character_knowledge_bindings(knowledge_id)"
            )

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
                    connection.execute("SELECT COUNT(*) FROM character_knowledge_bindings").fetchone()[0]
                )
        except sqlite3.OperationalError as exc:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=engine_status.location,
                healthy=False,
                schema_version=engine_status.schema_version,
                detail=str(exc),
            )
        return BackendStatus(
            name=self._name,
            kind="sqlite",
            location=engine_status.location,
            healthy=True,
            schema_version=engine_status.schema_version,
            detail=f"table=character_knowledge_bindings rows={count}",
        )

    def close(self) -> None:
        return None

    def _resolve_character_id_locked(
        self,
        connection: sqlite3.Connection,
        character_name: str,
        *,
        create_self_if_missing: bool = False,
    ) -> str | None:
        row = connection.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE LIMIT 1",
            (character_name,),
        ).fetchone()
        if row is not None:
            return str(row["id"])
        if create_self_if_missing and is_self_persona_name(character_name):
            if self._characters is not None:
                return self._characters.ensure_self_persona().id
            return SELF_PERSONA_ID
        return None

    def bind_character_knowledge(self, character_name: str, knowledge_id: str) -> None:
        name = _required(character_name, "character name")
        kid = _required(knowledge_id, "knowledge id")
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            char_id = self._resolve_character_id_locked(
                connection, name, create_self_if_missing=True
            )
            if char_id is None:
                raise ValueError(f"character not found: {name}")
            connection.execute(
                "INSERT OR IGNORE INTO character_knowledge_bindings(character_id, knowledge_id) VALUES (?, ?)",
                (char_id, kid),
            )

    def list_knowledge_binding_names(self, knowledge_id: str) -> dict[str, Any]:
        kid = _required(knowledge_id, "knowledge id")
        with self._engine.read_connection() as connection:
            names = [
                str(row["name"])
                for row in connection.execute(
                    """
                    SELECT c.name
                    FROM character_knowledge_bindings b
                    JOIN characters c ON c.id = b.character_id
                    WHERE b.knowledge_id = ?
                    ORDER BY c.name
                    """,
                    (kid,),
                )
            ]
        return {"knowledge_id": kid, "characterNames": names}

    def batch_knowledge_bindings(
        self,
        knowledge_id: str,
        add: list[str],
        remove: list[str],
    ) -> dict[str, Any]:
        kid = _required(knowledge_id, "knowledge id")
        added = _normalize_character_names(add, "add")
        removed = _normalize_character_names(remove, "remove")
        if added & removed:
            raise ValueError("a character cannot be added and removed in the same request")
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            for char_name in sorted(removed):
                char_id = self._resolve_character_id_locked(connection, char_name)
                if char_id is not None:
                    connection.execute(
                        "DELETE FROM character_knowledge_bindings WHERE knowledge_id = ? AND character_id = ?",
                        (kid, char_id),
                    )
            for char_name in sorted(added):
                char_id = self._resolve_character_id_locked(
                    connection, char_name, create_self_if_missing=True
                )
                if char_id is None:
                    raise ValueError(f"character not found: {char_name}")
                connection.execute(
                    "INSERT OR IGNORE INTO character_knowledge_bindings(character_id, knowledge_id) VALUES (?, ?)",
                    (char_id, kid),
                )
            names = [
                str(row["name"])
                for row in connection.execute(
                    """
                    SELECT c.name
                    FROM character_knowledge_bindings b
                    JOIN characters c ON c.id = b.character_id
                    WHERE b.knowledge_id = ?
                    ORDER BY c.name
                    """,
                    (kid,),
                )
            ]
        return {"ok": True, "knowledge_id": kid, "characterNames": names}

    def unbind_character_knowledge(self, character_name: str, knowledge_id: str) -> bool:
        name = _required(character_name, "character name")
        kid = _required(knowledge_id, "knowledge id")
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            char_id = self._resolve_character_id_locked(connection, name)
            if char_id is None:
                return False
            return (
                connection.execute(
                    "DELETE FROM character_knowledge_bindings WHERE character_id = ? AND knowledge_id = ?",
                    (char_id, kid),
                ).rowcount
                > 0
            )

    def list_character_knowledge_bindings(
        self,
        character_name: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        name = _required(character_name, "character name")
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        with self._engine.read_connection() as connection:
            char_id = self._resolve_character_id_locked(connection, name)
            if char_id is None:
                return {
                    "characterName": name,
                    "count": 0,
                    "page": page,
                    "pageSize": page_size,
                    "bindings": [],
                }
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM character_knowledge_bindings WHERE character_id = ?",
                    (char_id,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT knowledge_id, created_at
                FROM character_knowledge_bindings
                WHERE character_id = ?
                ORDER BY knowledge_id
                LIMIT ? OFFSET ?
                """,
                (char_id, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "characterName": name,
            "count": count,
            "page": page,
            "pageSize": page_size,
            "bindings": [
                {"knowledge_id": str(row["knowledge_id"]), "createdAt": str(row["created_at"])}
                for row in rows
            ],
        }

    def delete_knowledge_bindings(self, knowledge_id: str) -> int:
        kid = _required(knowledge_id, "knowledge id")
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            return connection.execute(
                "DELETE FROM character_knowledge_bindings WHERE knowledge_id = ?",
                (kid,),
            ).rowcount

    def rename_character_bindings(self, old_name: str, new_name: str) -> None:
        """Preserve or merge bindings across a character rename."""
        old = _required(old_name, "old character name")
        new = _required(new_name, "new character name")
        if old.casefold() == new.casefold():
            return
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            old_id = self._resolve_character_id_locked(connection, old)
            new_id = self._resolve_character_id_locked(connection, new)
            # When the character row was already updated in place with stable character_id,
            # bindings follow automatically with zero SQL work.
            if old_id is None or new_id is None or old_id == new_id:
                return
            connection.execute(
                """
                INSERT INTO character_knowledge_bindings(character_id, knowledge_id, created_at)
                SELECT ?, knowledge_id, created_at
                FROM character_knowledge_bindings
                WHERE character_id = ?
                ON CONFLICT(character_id, knowledge_id) DO UPDATE SET
                    created_at = MIN(character_knowledge_bindings.created_at, excluded.created_at)
                """,
                (new_id, old_id),
            )
            connection.execute(
                "DELETE FROM character_knowledge_bindings WHERE character_id = ?",
                (old_id,),
            )

    def delete_character_bindings(self, character_name: str) -> None:
        name = _required(character_name, "character name")
        with knowledge_operation_lock, self._engine.write_connection() as connection:
            char_id = self._resolve_character_id_locked(connection, name)
            if char_id is None:
                return
            connection.execute(
                "DELETE FROM character_knowledge_bindings WHERE character_id = ?",
                (char_id,),
            )

    def list_knowledge_ids_for_characters(self, character_names: Iterable[str]) -> list[str]:
        names = [str(item or "").strip() for item in character_names if str(item or "").strip()]
        if not names:
            return []
        placeholders = ",".join("? COLLATE NOCASE" for _ in names)
        with self._engine.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT b.knowledge_id
                FROM character_knowledge_bindings b
                JOIN characters c ON c.id = b.character_id
                WHERE c.name IN ({placeholders})
                """,
                names,
            ).fetchall()
        return sorted(
            str(row["knowledge_id"]) for row in rows if str(row["knowledge_id"]).strip()
        )

    def get_knowledge_binding_counts(self) -> dict[str, int]:
        with self._engine.read_connection() as connection:
            rows = connection.execute(
                "SELECT knowledge_id, COUNT(*) AS cnt FROM character_knowledge_bindings GROUP BY knowledge_id"
            ).fetchall()
        return {str(row["knowledge_id"]): int(row["cnt"]) for row in rows}


__all__ = ["SqliteKnowledgeBindingStore"]
