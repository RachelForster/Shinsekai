"""SQLite-backed character catalog store preserving stable IDs and single-row diffs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import sqlite3
import time
from typing import Protocol, runtime_checkable
from uuid import uuid4

from config.models import (
    Character,
    CharacterSummary,
    SELF_PERSONA_ID,
    Sprite,
    build_default_self_persona,
    is_self_persona_name,
)
from config.sprite_voice import normalize_sprite_voice_types
from core.storage.codecs import PydanticJsonCodec
from core.storage.sqlite_catalog import IndexedColumn, SqliteCatalogStore
from core.storage.sqlite_engine import SqliteEngine
from sdk.adapters.storage import BackendStatus, CatalogStore

STATIC_META_KEY = "characters:static"


def _normalize_character_for_storage(item: Character) -> Character:
    """Coerce any mutated raw sprite dicts and enforce self-persona invariants cleanly."""
    updates: dict[str, object] = {}
    if any(isinstance(sprite, dict) for sprite in item.sprites):
        updates["sprites"] = [
            Sprite.model_validate(sprite) if isinstance(sprite, dict) else sprite
            for sprite in item.sprites
        ]
    avatars = item.avatars or {}
    if any(
        any(isinstance(sprite, dict) for sprite in bank.sprites)
        for bank in avatars.values()
    ):
        updates["avatars"] = {
            kind: (
                bank.model_copy(
                    update={
                        "sprites": [
                            Sprite.model_validate(sprite)
                            if isinstance(sprite, dict)
                            else sprite
                            for sprite in bank.sprites
                        ]
                    }
                )
                if any(isinstance(sprite, dict) for sprite in bank.sprites)
                else bank
            )
            for kind, bank in avatars.items()
        }
    normalized = item.model_copy(update=updates) if updates else item
    if is_self_persona_name(normalized.name):
        return Character.model_validate(normalized.model_dump(mode="python"))
    return normalized


def _static_payload_changed(previous: Character, current: Character) -> bool:
    return previous.model_dump(mode="json", exclude={"relation_graph"}) != current.model_dump(
        mode="json", exclude={"relation_graph"}
    )


@runtime_checkable
class CharacterCatalogPort(CatalogStore[str, Character], Protocol):
    """Domain-specific query and batch sync port for Character catalogs."""

    @property
    def static_revision(self) -> str: ...

    def list_summaries(self) -> tuple[CharacterSummary, ...]: ...

    def list_catalog(self) -> list[Character]: ...

    def get_by_name(self, name: str) -> Character | None: ...

    def get_by_sprite_prefix(self, prefix: str) -> Character | None: ...

    def ensure_self_persona(self) -> Character: ...

    def replace_all(self, items: Sequence[Character]) -> str: ...


class SqliteCharacterCatalog:
    """Single-row diffing SQLite catalog store for ``Character`` entities."""

    def __init__(self, engine: SqliteEngine, *, name: str = "catalog.characters") -> None:
        self._engine = engine
        self._codec = PydanticJsonCodec(Character, pre_decode=normalize_sprite_voice_types)
        self._store = SqliteCatalogStore(
            engine,
            name=name,
            table="characters",
            codec=self._codec,
            key_of=lambda char: char.id,
            indexed_columns=(
                IndexedColumn("name", lambda char: char.name, "TEXT", unique=True, nocase=True),
                IndexedColumn("sprite_prefix", lambda char: char.sprite_prefix, "TEXT", unique=True),
                IndexedColumn("is_builtin", lambda char: int(bool(char.is_builtin)), "INTEGER"),
                IndexedColumn("pinned", lambda char: int(bool(char.pinned)), "INTEGER"),
            ),
            order_by="pinned DESC, is_builtin DESC, sort_order ASC, id ASC",
        )

    @property
    def name(self) -> str:
        return self._store.name

    @property
    def table(self) -> str:
        return self._store.table

    def migrate(self) -> None:
        self._store.migrate()
        with self._engine.write_connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO _catalog_meta(table_name, revision) VALUES (?, ?)",
                (STATIC_META_KEY, uuid4().hex),
            )

    @property
    def revision(self) -> str:
        return self._store.revision

    @property
    def static_revision(self) -> str:
        with self._engine.read_connection() as connection:
            try:
                row = connection.execute(
                    "SELECT revision FROM _catalog_meta WHERE table_name = ?",
                    (STATIC_META_KEY,),
                ).fetchone()
            except sqlite3.OperationalError:
                return ""
            return str(row["revision"]) if row is not None else ""

    def status(self) -> BackendStatus:
        return self._store.status()

    def close(self) -> None:
        self._store.close()

    def get(self, key: str) -> Character | None:
        return self._store.get(key)

    def get_by_name(self, name: str) -> Character | None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return None
        found = self._store.get_by_column("name", cleaned)
        if found is not None:
            return found
        if is_self_persona_name(cleaned):
            return build_default_self_persona()
        return None

    def get_by_sprite_prefix(self, prefix: str) -> Character | None:
        cleaned = str(prefix or "").strip()
        if not cleaned:
            return None
        return self._store.get_by_column("sprite_prefix", cleaned)

    def list_all(self) -> tuple[Character, ...]:
        return self._store.list_all()

    def list_catalog(self) -> list[Character]:
        """Return full catalog with built-in self-persona slot pinned first."""
        items = list(self.list_all())
        self_char: Character | None = None
        others: list[Character] = []
        for item in items:
            if is_self_persona_name(item.name) and self_char is None:
                self_char = item
            else:
                others.append(item)
        if self_char is None:
            self_char = build_default_self_persona()
        return [self_char, *others]

    def list_summaries(self) -> tuple[CharacterSummary, ...]:
        return tuple(CharacterSummary.from_character(item) for item in self.list_catalog())

    def ensure_self_persona(self) -> Character:
        with self._engine.write_connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM characters WHERE id = ? OR name = ? COLLATE NOCASE LIMIT 1",
                (SELF_PERSONA_ID, "自设"),
            ).fetchone()
            if row is not None:
                return self._codec.decode(str(row["payload_json"]).encode("utf-8"))
            created = build_default_self_persona()
            payload_text = self._codec.encode(created).decode("utf-8")
            connection.execute(
                """
                INSERT INTO characters(
                    id, name, sprite_prefix, is_builtin, pinned, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, 1, 1, -1, ?, ?)
                """,
                (
                    created.id,
                    created.name,
                    created.sprite_prefix,
                    payload_text,
                    time.time(),
                ),
            )
            self._bump_revisions_locked(connection, bump_static=True)
            return created.model_copy(deep=True)

    def put(self, key: str, item: Character) -> str:
        normalized = _normalize_character_for_storage(item)
        if normalized.id != key:
            raise ValueError(f"Key {key!r} does not match item key {normalized.id!r}")
        with self._engine.write_connection() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM characters WHERE id = ?",
                (key,),
            ).fetchone()
            bump_static = True
            if existing is not None:
                prev = self._codec.decode(str(existing["payload_json"]).encode("utf-8"))
                bump_static = _static_payload_changed(prev, normalized)
            revision = self._store.put(key, normalized)
            if bump_static:
                self._bump_static_revision_locked(connection)
            return revision

    def patch(self, key: str, mutator: Callable[[Character], Character]) -> Character:
        with self._engine.write_connection() as connection:
            current = self.get(key)
            if current is None:
                raise KeyError(key)
            updated = _normalize_character_for_storage(mutator(current))
            self.put(key, updated)
            return updated.model_copy(deep=True)

    def delete(self, key: str) -> bool:
        with self._engine.write_connection() as connection:
            deleted = self._store.delete(key)
            if deleted:
                self._bump_static_revision_locked(connection)
            return deleted

    def replace_all(self, items: Sequence[Character]) -> str:
        """Synchronize the catalog list while only updating rows whose content or order changed."""
        with self._engine.write_connection() as connection:
            existing_rows = connection.execute(
                "SELECT id, name, sprite_prefix, sort_order, payload_json FROM characters"
            ).fetchall()
            existing_by_id = {str(row["id"]): row for row in existing_rows}
            existing_id_by_name = {
                str(row["name"]).strip().casefold(): str(row["id"])
                for row in existing_rows
            }

            raw_items = [_normalize_character_for_storage(item) for item in items]
            explicit_ids = {
                item.id
                for item in raw_items
                if item.id in existing_by_id
            }
            resolved_items: list[Character] = []
            seen_ids: set[str] = set()
            for item in raw_items:
                candidate = item
                if is_self_persona_name(candidate.name):
                    if candidate.id != SELF_PERSONA_ID:
                        candidate = candidate.model_copy(update={"id": SELF_PERSONA_ID})
                elif candidate.id not in existing_by_id:
                    matched_id = existing_id_by_name.get(candidate.name.strip().casefold())
                    if matched_id and matched_id not in explicit_ids and matched_id not in seen_ids:
                        candidate = candidate.model_copy(update={"id": matched_id})
                if candidate.id in seen_ids:
                    candidate = candidate.model_copy(update={"id": uuid4().hex})
                seen_ids.add(candidate.id)
                resolved_items.append(candidate)

            incoming_ids = {item.id for item in resolved_items}
            removed_ids = [row_id for row_id in existing_by_id if row_id not in incoming_ids]

            changed_updates: list[tuple[int, Character, str]] = []
            new_inserts: list[tuple[int, Character, str]] = []
            bump_static = bool(removed_ids)

            for index, item in enumerate(resolved_items):
                sort_order = -1 if item.id == SELF_PERSONA_ID else index
                payload_text = self._codec.encode(item).decode("utf-8")
                existing = existing_by_id.get(item.id)
                if existing is None:
                    new_inserts.append((sort_order, item, payload_text))
                    bump_static = True
                    continue
                if (
                    str(existing["payload_json"]) == payload_text
                    and int(existing["sort_order"]) == sort_order
                ):
                    continue
                if str(existing["payload_json"]) != payload_text:
                    prev_model = self._codec.decode(str(existing["payload_json"]).encode("utf-8"))
                    if _static_payload_changed(prev_model, item):
                        bump_static = True
                else:
                    bump_static = True
                changed_updates.append((sort_order, item, payload_text))

            if not removed_ids and not changed_updates and not new_inserts:
                return self._current_revision_locked(connection)

            now = time.time()
            # 1) Remove deleted characters first (fires legitimate ON DELETE CASCADE).
            for removed_id in removed_ids:
                connection.execute("DELETE FROM characters WHERE id = ?", (removed_id,))

            # 2) Neutralize unique columns on rows being updated to prevent transient swap collisions.
            for _sort_order, item, _payload in changed_updates:
                connection.execute(
                    "UPDATE characters SET name = ?, sprite_prefix = ? WHERE id = ?",
                    (f"__updating_name_{item.id}", f"__updating_prefix_{item.id}", item.id),
                )

            # 3) Apply single-row updates for modified characters (keeps character_id intact -> zero cascade loss).
            for sort_order, item, payload_text in changed_updates:
                connection.execute(
                    """
                    UPDATE characters
                    SET name = ?, sprite_prefix = ?, is_builtin = ?, pinned = ?,
                        sort_order = ?, payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.name,
                        item.sprite_prefix,
                        int(bool(item.is_builtin)),
                        int(bool(item.pinned)),
                        sort_order,
                        payload_text,
                        now,
                        item.id,
                    ),
                )

            # 4) Insert newly added characters.
            for sort_order, item, payload_text in new_inserts:
                connection.execute(
                    """
                    INSERT INTO characters(
                        id, name, sprite_prefix, is_builtin, pinned, sort_order, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.name,
                        item.sprite_prefix,
                        int(bool(item.is_builtin)),
                        int(bool(item.pinned)),
                        sort_order,
                        payload_text,
                        now,
                    ),
                )

            return self._bump_revisions_locked(connection, bump_static=bump_static)

    def _current_revision_locked(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT revision FROM _catalog_meta WHERE table_name = 'characters'"
        ).fetchone()
        if row is not None:
            return str(row["revision"])
        return self._bump_revisions_locked(connection, bump_static=True)

    def _bump_static_revision_locked(self, connection: sqlite3.Connection) -> str:
        new_rev = uuid4().hex
        connection.execute(
            """
            INSERT INTO _catalog_meta(table_name, revision) VALUES (?, ?)
            ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
            """,
            (STATIC_META_KEY, new_rev),
        )
        return new_rev

    def _bump_revisions_locked(self, connection: sqlite3.Connection, *, bump_static: bool) -> str:
        new_rev = uuid4().hex
        connection.execute(
            """
            INSERT INTO _catalog_meta(table_name, revision) VALUES ('characters', ?)
            ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
            """,
            (new_rev,),
        )
        if bump_static:
            self._bump_static_revision_locked(connection)
        return new_rev


__all__ = ["CharacterCatalogPort", "SqliteCharacterCatalog"]
