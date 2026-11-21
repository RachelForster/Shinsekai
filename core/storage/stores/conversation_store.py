"""SQLite-backed conversation metadata store replacing ``data/config/conversations/*.json``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import sqlite3
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.storage.codecs import PydanticJsonCodec
from core.storage.sqlite_engine import SqliteEngine
from sdk.adapters.storage import BackendStatus


class ConversationRecord(BaseModel):
    """Structured named-conversation launch and metadata record."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Conversation hash ID derived from history directory")
    history_path: str = Field(..., description="Portable or resolved history path")
    title: str = Field(default="", description="User-assigned or derived title")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO creation timestamp",
    )
    launch: Optional[Dict[str, Any]] = Field(
        default=None, description="Launch payload snapshot"
    )
    requires_character_selection: bool = Field(
        default=False,
        description="True when a previously referenced cast member was deleted",
    )

    def to_legacy_dict(self) -> dict[str, Any]:
        """Project to the legacy JSON record shape consumed by conversation_library."""
        out: dict[str, Any] = {
            "historyPath": self.history_path,
            "title": self.title,
            "createdAt": self.created_at,
        }
        if self.launch is not None:
            out["launch"] = dict(self.launch)
        if self.requires_character_selection:
            out["requiresCharacterSelection"] = True
        return out

    @classmethod
    def from_legacy_dict(cls, conv_id: str, data: dict[str, Any]) -> "ConversationRecord":
        return cls(
            id=conv_id,
            history_path=str(data.get("historyPath") or ""),
            title=str(data.get("title") or ""),
            created_at=str(data.get("createdAt") or datetime.now(timezone.utc).isoformat()),
            launch=dict(data["launch"]) if isinstance(data.get("launch"), dict) else None,
            requires_character_selection=bool(data.get("requiresCharacterSelection", False)),
        )


class SqliteConversationStore:
    """SQLite CatalogStore for ``conversations`` table in ``data/shinsekai.db``."""

    def __init__(self, engine: SqliteEngine, *, name: str = "catalog.conversations") -> None:
        self._engine = engine
        self._name = name
        self._table = "conversations"
        self._codec = PydanticJsonCodec(ConversationRecord)

    @property
    def name(self) -> str:
        return self._name

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

    def migrate(self) -> None:
        with self._engine.write_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS _catalog_meta (
                    table_name TEXT PRIMARY KEY,
                    revision TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id            TEXT PRIMARY KEY,
                    history_path  TEXT NOT NULL UNIQUE,
                    title         TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL,
                    payload_json  TEXT NOT NULL,
                    updated_at    REAL NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO _catalog_meta(table_name, revision) VALUES (?, ?)",
                (self._table, uuid4().hex),
            )

    def get(self, key: str) -> ConversationRecord | None:
        with self._engine.read_connection() as connection:
            row = connection.execute(
                "SELECT id, history_path, title, created_at, payload_json FROM conversations WHERE id = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._decode_row(row)

    def list_all(self) -> tuple[ConversationRecord, ...]:
        with self._engine.read_connection() as connection:
            rows = connection.execute(
                "SELECT id, history_path, title, created_at, payload_json FROM conversations ORDER BY updated_at DESC, id ASC"
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def put(self, key: str, item: ConversationRecord) -> str:
        if item.id != key:
            raise ValueError(f"Key {key!r} does not match record id {item.id!r}")
        payload_text = json.dumps(item.to_legacy_dict(), ensure_ascii=False)
        now = time.time()
        with self._engine.write_connection() as connection:
            # Remove any stale entry claiming the same history_path under a different id.
            connection.execute(
                "DELETE FROM conversations WHERE history_path = ? AND id != ?",
                (item.history_path, key),
            )
            connection.execute(
                """
                INSERT INTO conversations(id, history_path, title, created_at, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    history_path = excluded.history_path,
                    title = excluded.title,
                    created_at = excluded.created_at,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (key, item.history_path, item.title, item.created_at, payload_text, now),
            )
            return self._bump_revision_locked(connection)

    def patch(
        self,
        key: str,
        mutator: Callable[[ConversationRecord], ConversationRecord],
    ) -> ConversationRecord:
        with self._engine.write_connection() as connection:
            current = self.get(key)
            if current is None:
                raise KeyError(key)
            updated = mutator(current.model_copy(deep=True))
            self.put(key, updated)
            return updated.model_copy(deep=True)

    def delete(self, key: str) -> bool:
        with self._engine.write_connection() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (key,))
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
                count = int(connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
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
            detail=f"table=conversations rows={count}",
        )

    def close(self) -> None:
        return None

    def _decode_row(self, row: sqlite3.Row) -> ConversationRecord:
        raw = json.loads(str(row["payload_json"]))
        if isinstance(raw, dict):
            raw.setdefault("historyPath", str(row["history_path"]))
            raw.setdefault("title", str(row["title"]))
            raw.setdefault("createdAt", str(row["created_at"]))
            return ConversationRecord.from_legacy_dict(str(row["id"]), raw)
        return ConversationRecord(
            id=str(row["id"]),
            history_path=str(row["history_path"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
        )

    def _bump_revision_locked(self, connection: sqlite3.Connection) -> str:
        new_rev = uuid4().hex
        connection.execute(
            """
            INSERT INTO _catalog_meta(table_name, revision) VALUES (?, ?)
            ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
            """,
            (self._table, new_rev),
        )
        return new_rev


__all__ = ["ConversationRecord", "SqliteConversationStore"]
