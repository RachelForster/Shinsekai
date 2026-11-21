"""SQLite catalog stores for Background and Effect collections."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import sqlite3
import time
from typing import Protocol, runtime_checkable
from uuid import uuid4

from config.models import Background, Effect, Sprite
from core.storage.codecs import PydanticJsonCodec
from core.storage.sqlite_catalog import IndexedColumn, SqliteCatalogStore
from core.storage.sqlite_engine import SqliteEngine
from sdk.adapters.storage import BackendStatus, CatalogStore


def _normalize_background(item: Background) -> Background:
    if any(isinstance(sprite, dict) for sprite in item.sprites):
        return item.model_copy(
            update={
                "sprites": [
                    Sprite.model_validate(sprite) if isinstance(sprite, dict) else sprite
                    for sprite in item.sprites
                ]
            }
        )
    return item


@runtime_checkable
class BackgroundCatalogPort(CatalogStore[str, Background], Protocol):
    """Domain catalog port for Background entries."""

    def get_by_name(self, name: str) -> Background | None: ...

    def replace_all(self, items: Sequence[Background]) -> str: ...


@runtime_checkable
class EffectCatalogPort(CatalogStore[str, Effect], Protocol):
    """Domain catalog port for Effect entries."""

    def get_by_name(self, name: str) -> Effect | None: ...

    def replace_all(self, items: Sequence[Effect]) -> str: ...


class SqliteBackgroundCatalog:
    """Single-row diffing SQLite catalog store for ``Background`` entities."""

    def __init__(self, engine: SqliteEngine, *, name: str = "catalog.backgrounds") -> None:
        self._engine = engine
        self._codec = PydanticJsonCodec(Background)
        self._store = SqliteCatalogStore(
            engine,
            name=name,
            table="backgrounds",
            codec=self._codec,
            key_of=lambda item: item.id,
            indexed_columns=(
                IndexedColumn("name", lambda item: item.name, "TEXT", unique=True, nocase=True),
                IndexedColumn("sprite_prefix", lambda item: item.sprite_prefix, "TEXT", unique=False),
            ),
            order_by="sort_order ASC, id ASC",
        )

    @property
    def name(self) -> str:
        return self._store.name

    @property
    def table(self) -> str:
        return self._store.table

    @property
    def revision(self) -> str:
        return self._store.revision

    def migrate(self) -> None:
        self._store.migrate()

    def status(self) -> BackendStatus:
        return self._store.status()

    def close(self) -> None:
        self._store.close()

    def get(self, key: str) -> Background | None:
        return self._store.get(key)

    def get_by_name(self, name: str) -> Background | None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return None
        return self._store.get_by_column("name", cleaned)

    def list_all(self) -> tuple[Background, ...]:
        return self._store.list_all()

    def put(self, key: str, item: Background) -> str:
        return self._store.put(key, _normalize_background(item))

    def patch(self, key: str, mutator: Callable[[Background], Background]) -> Background:
        return self._store.patch(key, lambda current: _normalize_background(mutator(current)))

    def delete(self, key: str) -> bool:
        return self._store.delete(key)

    def replace_all(self, items: Sequence[Background]) -> str:
        with self._engine.write_connection() as connection:
            existing_rows = connection.execute(
                "SELECT id, name, sort_order, payload_json FROM backgrounds"
            ).fetchall()
            existing_by_id = {str(row["id"]): row for row in existing_rows}
            existing_id_by_name = {
                str(row["name"]).strip().casefold(): str(row["id"])
                for row in existing_rows
            }
            raw_items = [_normalize_background(item) for item in items]
            explicit_ids = {item.id for item in raw_items if item.id in existing_by_id}

            resolved: list[Background] = []
            seen_ids: set[str] = set()
            for item in raw_items:
                candidate = item
                if candidate.id not in existing_by_id:
                    matched_id = existing_id_by_name.get(candidate.name.strip().casefold())
                    if matched_id and matched_id not in explicit_ids and matched_id not in seen_ids:
                        candidate = candidate.model_copy(update={"id": matched_id})
                if candidate.id in seen_ids:
                    candidate = candidate.model_copy(update={"id": uuid4().hex})
                seen_ids.add(candidate.id)
                resolved.append(candidate)

            incoming_ids = {item.id for item in resolved}
            removed_ids = [row_id for row_id in existing_by_id if row_id not in incoming_ids]
            updates: list[tuple[int, Background, str]] = []
            inserts: list[tuple[int, Background, str]] = []

            for sort_order, item in enumerate(resolved):
                payload_text = self._codec.encode(item).decode("utf-8")
                existing = existing_by_id.get(item.id)
                if existing is None:
                    inserts.append((sort_order, item, payload_text))
                elif str(existing["payload_json"]) != payload_text or int(existing["sort_order"]) != sort_order:
                    updates.append((sort_order, item, payload_text))

            if not removed_ids and not updates and not inserts:
                return _current_table_revision(connection, "backgrounds")

            now = time.time()
            for removed_id in removed_ids:
                connection.execute("DELETE FROM backgrounds WHERE id = ?", (removed_id,))
            for _sort_order, item, _payload in updates:
                connection.execute(
                    "UPDATE backgrounds SET name = ? WHERE id = ?",
                    (f"__updating_bg_{item.id}", item.id),
                )
            for sort_order, item, payload_text in updates:
                connection.execute(
                    """
                    UPDATE backgrounds
                    SET name = ?, sprite_prefix = ?, sort_order = ?, payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (item.name, item.sprite_prefix, sort_order, payload_text, now, item.id),
                )
            for sort_order, item, payload_text in inserts:
                connection.execute(
                    """
                    INSERT INTO backgrounds(id, name, sprite_prefix, sort_order, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (item.id, item.name, item.sprite_prefix, sort_order, payload_text, now),
                )
            return _bump_table_revision(connection, "backgrounds")


class SqliteEffectCatalog:
    """Single-row diffing SQLite catalog store for ``Effect`` entities."""

    def __init__(self, engine: SqliteEngine, *, name: str = "catalog.effects") -> None:
        self._engine = engine
        self._codec = PydanticJsonCodec(Effect)
        self._store = SqliteCatalogStore(
            engine,
            name=name,
            table="effects",
            codec=self._codec,
            key_of=lambda item: item.id,
            indexed_columns=(
                IndexedColumn("name", lambda item: item.name, "TEXT", unique=True, nocase=True),
            ),
            order_by="sort_order ASC, id ASC",
        )

    @property
    def name(self) -> str:
        return self._store.name

    @property
    def table(self) -> str:
        return self._store.table

    @property
    def revision(self) -> str:
        return self._store.revision

    def migrate(self) -> None:
        self._store.migrate()

    def status(self) -> BackendStatus:
        return self._store.status()

    def close(self) -> None:
        self._store.close()

    def get(self, key: str) -> Effect | None:
        return self._store.get(key)

    def get_by_name(self, name: str) -> Effect | None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return None
        return self._store.get_by_column("name", cleaned)

    def list_all(self) -> tuple[Effect, ...]:
        return self._store.list_all()

    def put(self, key: str, item: Effect) -> str:
        return self._store.put(key, item)

    def patch(self, key: str, mutator: Callable[[Effect], Effect]) -> Effect:
        return self._store.patch(key, mutator)

    def delete(self, key: str) -> bool:
        return self._store.delete(key)

    def replace_all(self, items: Sequence[Effect]) -> str:
        with self._engine.write_connection() as connection:
            existing_rows = connection.execute(
                "SELECT id, name, sort_order, payload_json FROM effects"
            ).fetchall()
            existing_by_id = {str(row["id"]): row for row in existing_rows}
            existing_id_by_name = {
                str(row["name"]).strip().casefold(): str(row["id"])
                for row in existing_rows
            }
            explicit_ids = {item.id for item in items if item.id in existing_by_id}

            resolved: list[Effect] = []
            seen_ids: set[str] = set()
            for item in items:
                candidate = item
                if candidate.id not in existing_by_id:
                    matched_id = existing_id_by_name.get(candidate.name.strip().casefold())
                    if matched_id and matched_id not in explicit_ids and matched_id not in seen_ids:
                        candidate = candidate.model_copy(update={"id": matched_id})
                if candidate.id in seen_ids:
                    candidate = candidate.model_copy(update={"id": uuid4().hex})
                seen_ids.add(candidate.id)
                resolved.append(candidate)

            incoming_ids = {item.id for item in resolved}
            removed_ids = [row_id for row_id in existing_by_id if row_id not in incoming_ids]
            updates: list[tuple[int, Effect, str]] = []
            inserts: list[tuple[int, Effect, str]] = []

            for sort_order, item in enumerate(resolved):
                payload_text = self._codec.encode(item).decode("utf-8")
                existing = existing_by_id.get(item.id)
                if existing is None:
                    inserts.append((sort_order, item, payload_text))
                elif str(existing["payload_json"]) != payload_text or int(existing["sort_order"]) != sort_order:
                    updates.append((sort_order, item, payload_text))

            if not removed_ids and not updates and not inserts:
                return _current_table_revision(connection, "effects")

            now = time.time()
            for removed_id in removed_ids:
                connection.execute("DELETE FROM effects WHERE id = ?", (removed_id,))
            for _sort_order, item, _payload in updates:
                connection.execute(
                    "UPDATE effects SET name = ? WHERE id = ?",
                    (f"__updating_fx_{item.id}", item.id),
                )
            for sort_order, item, payload_text in updates:
                connection.execute(
                    """
                    UPDATE effects
                    SET name = ?, sort_order = ?, payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (item.name, sort_order, payload_text, now, item.id),
                )
            for sort_order, item, payload_text in inserts:
                connection.execute(
                    """
                    INSERT INTO effects(id, name, sort_order, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item.id, item.name, sort_order, payload_text, now),
                )
            return _bump_table_revision(connection, "effects")


def _current_table_revision(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT revision FROM _catalog_meta WHERE table_name = ?",
        (table_name,),
    ).fetchone()
    if row is not None:
        return str(row["revision"])
    return _bump_table_revision(connection, table_name)


def _bump_table_revision(connection: sqlite3.Connection, table_name: str) -> str:
    new_rev = uuid4().hex
    connection.execute(
        """
        INSERT INTO _catalog_meta(table_name, revision) VALUES (?, ?)
        ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
        """,
        (table_name, new_rev),
    )
    return new_rev


__all__ = [
    "BackgroundCatalogPort",
    "EffectCatalogPort",
    "SqliteBackgroundCatalog",
    "SqliteEffectCatalog",
]
