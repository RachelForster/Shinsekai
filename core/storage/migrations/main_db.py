"""Schema migrations and 5-step atomic legacy data importer for ``data/shinsekai.db``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any
import uuid
import yaml

from config.models import (
    Background,
    Character,
    Effect,
    SELF_PERSONA_ID,
    SELF_PERSONA_NAME,
    SystemConfig,
    UiRuntimeState,
    build_default_self_persona,
    is_self_persona,
    is_self_persona_name,
)
from config.sprite_voice import normalize_sprite_voice_types
from core.storage.codecs import PydanticJsonCodec, PydanticYamlCodec
from core.storage.file_store import FileDocumentStore
from core.storage.layout import StorageLayout
from core.storage.migrations.self_persona_migration import (
    migrate_v2_self_persona_display_name,
    rename_template_session_dict,
)
from core.storage.sqlite_engine import SqliteEngine, SqliteMigration
from core.storage.stores.conversation_store import ConversationRecord
from sdk.adapters.storage import BackendStatus
from sdk.file_io import durable_mkdir

logger = logging.getLogger(__name__)

MIGRATION_KEYS = (
    "v1_import_yaml_catalogs",
    "v1_import_conversations",
    "v1_import_knowledge_bindings",
    "v1_import_reminders",
    "v1_relocate_state_and_cache",
)

_CHAR_NAMESPACE = uuid.UUID("7f9c2a40-6b1e-4d8a-9c3f-1e5a8b2d4f60")
_BG_NAMESPACE = uuid.UUID("5c8d1b20-3a4e-4f91-8b2d-7e6c9a1d3f50")
_EF_NAMESPACE = uuid.UUID("3e7a9c10-2b5f-4e82-9a1c-6d4b8e2f0a40")

_IN_PROCESS_MIGRATION_LOCK = threading.Lock()


def _migrate_v1(connection: sqlite3.Connection) -> None:
    """Create all version-1 unified business tables and initial metadata rows."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS _catalog_meta (
            table_name TEXT PRIMARY KEY,
            revision   TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_migrations (
            name        TEXT PRIMARY KEY,
            applied_at  REAL NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS characters (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
            sprite_prefix TEXT NOT NULL UNIQUE,
            is_builtin    INTEGER NOT NULL DEFAULT 0,
            pinned        INTEGER NOT NULL DEFAULT 0,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            payload_json  TEXT NOT NULL,
            updated_at    REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_characters_is_builtin ON characters(is_builtin)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_characters_pinned ON characters(pinned)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS backgrounds (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
            sprite_prefix TEXT NOT NULL,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            payload_json  TEXT NOT NULL,
            updated_at    REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_backgrounds_sprite_prefix ON backgrounds(sprite_prefix)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS effects (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            payload_json  TEXT NOT NULL,
            updated_at    REAL NOT NULL
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
        "CREATE INDEX IF NOT EXISTS idx_kb_knowledge_id ON character_knowledge_bindings(knowledge_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id             TEXT PRIMARY KEY,
            character_id   TEXT NOT NULL,
            title          TEXT NOT NULL,
            message        TEXT NOT NULL,
            due_at         REAL NOT NULL,
            recurrence     TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'active',
            claim_token    TEXT,
            claim_until    REAL NOT NULL DEFAULT 0,
            delivery_count INTEGER NOT NULL DEFAULT 0,
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_heartbeat (
            id      INTEGER PRIMARY KEY,
            seen_at REAL
        )
        """
    )
    for meta_key in ("characters", "characters:static", "backgrounds", "effects", "conversations"):
        connection.execute(
            "INSERT OR IGNORE INTO _catalog_meta(table_name, revision) VALUES (?, ?)",
            (meta_key, uuid.uuid4().hex),
        )


MAIN_DB_MIGRATIONS: tuple[SqliteMigration, ...] = (
    SqliteMigration(
        version=1,
        description="Initial unified shinsekai.db schema",
        up=_migrate_v1,
    ),
    SqliteMigration(
        version=2,
        description="Promote built-in self-persona display_name into canonical name",
        up=migrate_v2_self_persona_display_name,
    ),
)


@contextmanager
def _cross_process_migration_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an OS-level exclusive lock preventing concurrent startup migrations."""
    durable_mkdir(lock_path.parent)
    with _IN_PROCESS_MIGRATION_LOCK:
        handle = lock_path.open("a+b")
        locked = False
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if lock_path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                locked = True
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                locked = True
            yield
        finally:
            if locked:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


def _safe_yaml_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _read_legacy_knowledge_rows(db_path: Path) -> list[tuple[str, str, str]]:
    if not db_path.is_file():
        return []
    connection = sqlite3.connect(db_path, timeout=10)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_knowledge_bindings'"
        ).fetchone()
        if table_exists is None:
            return []
        rows = connection.execute(
            "SELECT character_name, knowledge_id, created_at FROM character_knowledge_bindings"
        ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]
    finally:
        connection.close()


def _read_legacy_reminder_data(db_path: Path) -> tuple[list[dict[str, Any]], float | None, bool]:
    if not db_path.is_file():
        return [], None, False
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        reminders: list[dict[str, Any]] = []
        has_reminders = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reminders'"
        ).fetchone()
        if has_reminders is not None:
            cols = {row["name"] for row in connection.execute("PRAGMA table_info(reminders)")}
            has_delivery = "delivery_count" in cols
            for row in connection.execute("SELECT * FROM reminders"):
                reminders.append(
                    {
                        "id": str(row["id"]),
                        "character_name": str(row["character_name"]),
                        "title": str(row["title"]),
                        "message": str(row["message"]),
                        "due_at": float(row["due_at"]),
                        "recurrence": str(row["recurrence"]),
                        "status": str(row["status"]),
                        "claim_token": row["claim_token"],
                        "claim_until": float(row["claim_until"] or 0),
                        "delivery_count": int(row["delivery_count"] or 0) if has_delivery else 0,
                        "created_at": float(row["created_at"]),
                        "updated_at": float(row["updated_at"]),
                    }
                )
        seen_at: float | None = None
        has_hb = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='heartbeat'"
        ).fetchone()
        if has_hb is not None:
            hb_row = connection.execute("SELECT seen_at FROM heartbeat WHERE id=1").fetchone()
            if hb_row is not None and hb_row[0] is not None:
                seen_at = float(hb_row[0])
        has_bedtime = False
        has_mig = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migrations'"
        ).fetchone()
        if has_mig is not None:
            has_bedtime = (
                connection.execute(
                    "SELECT 1 FROM migrations WHERE name='native-bedtime'"
                ).fetchone()
                is not None
            )
        return reminders, seen_at, has_bedtime
    finally:
        connection.close()


class LegacyDataMigrator:
    """One-time atomic startup migrator from legacy YAML/SQLite/JSON files into unified storage."""

    def __init__(
        self,
        layout: StorageLayout,
        engine: SqliteEngine,
        *,
        system_store: FileDocumentStore[SystemConfig] | None = None,
        ui_state_store: FileDocumentStore[UiRuntimeState] | None = None,
        name: str = "migration.legacy",
    ) -> None:
        self._layout = layout
        self._engine = engine
        self._system_store = system_store or FileDocumentStore(
            "settings.system.migrator",
            layout.config_file("system_config.yaml"),
            PydanticYamlCodec(SystemConfig),
        )
        self._ui_state_store = ui_state_store or FileDocumentStore(
            "state.ui.migrator",
            layout.state_file("ui_state.json"),
            PydanticJsonCodec(UiRuntimeState),
        )
        self._name = name
        self._char_codec = PydanticJsonCodec(Character, pre_decode=normalize_sprite_voice_types)
        self._bg_codec = PydanticJsonCodec(Background)
        self._ef_codec = PydanticJsonCodec(Effect)

    @property
    def name(self) -> str:
        return self._name

    def status(self) -> BackendStatus:
        try:
            with self._engine.read_connection() as connection:
                rows = connection.execute(
                    "SELECT name FROM storage_migrations"
                ).fetchall()
            applied = {str(r["name"]) for r in rows}
            pending = [key for key in MIGRATION_KEYS if key not in applied]
            detail = "complete" if not pending else f"pending={','.join(pending)}"
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=str(self._layout.main_db_path),
                healthy=True,
                schema_version=self._engine.schema_version(),
                detail=detail,
            )
        except Exception as exc:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=str(self._layout.main_db_path),
                healthy=False,
                detail=f"{type(exc).__name__}: {exc}",
            )

    def close(self) -> None:
        return None

    def _applied_keys(self) -> set[str]:
        with self._engine.read_connection() as connection:
            rows = connection.execute("SELECT name FROM storage_migrations").fetchall()
        return {str(row["name"]) for row in rows}

    def migrate(self) -> None:
        """Execute the 5-step idempotent legacy migration under cross-process file lock."""
        if all(key in self._applied_keys() for key in MIGRATION_KEYS):
            return

        with _cross_process_migration_lock(self._layout.migration_lock_path):
            applied = self._applied_keys()
            if all(key in applied for key in MIGRATION_KEYS):
                return

            sqlite_keys_pending = [
                key
                for key in (
                    "v1_import_yaml_catalogs",
                    "v1_import_conversations",
                    "v1_import_knowledge_bindings",
                    "v1_import_reminders",
                )
                if key not in applied
            ]
            if sqlite_keys_pending:
                self._run_atomic_sqlite_import(applied)

            applied = self._applied_keys()
            if "v1_relocate_state_and_cache" not in applied:
                self._relocate_state_and_cache()

            self._archive_legacy_files()

    def _run_atomic_sqlite_import(self, applied: set[str]) -> None:
        char_yaml = self._layout.config_file("characters.yaml")
        bg_yaml = self._layout.config_file("background.yaml")
        ef_yaml = self._layout.config_file("effect.yaml")
        conv_dir = self._layout.config_dir / "conversations"
        kb_db = self._layout.data_dir / "knowledge" / "knowledge.db"
        reminders_db = self._layout.data_dir / "reminders.sqlite3"

        # Seed name -> character_id map with any characters already in DB.
        name_to_id: dict[str, str] = {}
        existing_char_ids: set[str] = set()
        with self._engine.read_connection() as connection:
            for row in connection.execute("SELECT id, name FROM characters"):
                cid = str(row["id"])
                name_to_id[str(row["name"]).strip().casefold()] = cid
                existing_char_ids.add(cid)

        characters_to_insert: list[tuple[int, Character]] = []
        backgrounds_to_insert: list[tuple[int, Background]] = []
        effects_to_insert: list[tuple[int, Effect]] = []
        used_prefixes: set[str] = set()

        if "v1_import_yaml_catalogs" not in applied:
            for idx, raw_item in enumerate(_safe_yaml_list(char_yaml)):
                normalized_dict = normalize_sprite_voice_types(raw_item)
                char = Character.model_validate(normalized_dict)
                if is_self_persona(char):
                    char = char.model_copy(update={"id": SELF_PERSONA_ID})
                    sort_order = -1
                else:
                    if not raw_item.get("id"):
                        det_id = uuid.uuid5(_CHAR_NAMESPACE, f"{idx}:{char.name.strip().casefold()}").hex
                        char = char.model_copy(update={"id": det_id})
                    sort_order = idx
                key = char.name.strip().casefold()
                if key in name_to_id:
                    continue
                if char.sprite_prefix in used_prefixes:
                    continue
                used_prefixes.add(char.sprite_prefix)
                name_to_id[key] = char.id
                existing_char_ids.add(char.id)
                characters_to_insert.append((sort_order, char))

            seen_bgs: set[str] = set()
            for idx, raw_item in enumerate(_safe_yaml_list(bg_yaml)):
                bg = Background.model_validate(raw_item)
                if not raw_item.get("id"):
                    bg = bg.model_copy(
                        update={"id": uuid.uuid5(_BG_NAMESPACE, f"{idx}:{bg.name.strip().casefold()}").hex}
                    )
                if bg.name.strip().casefold() in seen_bgs:
                    continue
                seen_bgs.add(bg.name.strip().casefold())
                backgrounds_to_insert.append((idx, bg))

            seen_efs: set[str] = set()
            for idx, raw_item in enumerate(_safe_yaml_list(ef_yaml)):
                ef = Effect.model_validate(raw_item)
                if not raw_item.get("id"):
                    ef = ef.model_copy(
                        update={"id": uuid.uuid5(_EF_NAMESPACE, f"{idx}:{ef.name.strip().casefold()}").hex}
                    )
                if ef.name.strip().casefold() in seen_efs:
                    continue
                seen_efs.add(ef.name.strip().casefold())
                effects_to_insert.append((idx, ef))

        conversations_to_insert: list[ConversationRecord] = []
        if "v1_import_conversations" not in applied and conv_dir.is_dir():
            for file_path in sorted(conv_dir.glob("*.json")):
                try:
                    raw = json.loads(file_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(raw, dict) or not raw.get("historyPath"):
                    continue
                conversations_to_insert.append(
                    ConversationRecord.from_legacy_dict(file_path.stem, raw)
                )

        kb_rows_to_insert: list[tuple[str, str, str]] = []
        kb_orphans = 0
        if "v1_import_knowledge_bindings" not in applied:
            for char_name, knowledge_id, created_at in _read_legacy_knowledge_rows(kb_db):
                norm_key = char_name.strip().casefold()
                char_id = name_to_id.get(norm_key)
                if char_id is None and is_self_persona_name(char_name):
                    self_char = build_default_self_persona()
                    if self_char.id not in existing_char_ids:
                        characters_to_insert.append((-1, self_char))
                        existing_char_ids.add(self_char.id)
                    name_to_id[norm_key] = self_char.id
                    char_id = self_char.id
                if char_id is None:
                    kb_orphans += 1
                    continue
                kb_rows_to_insert.append((char_id, knowledge_id, created_at))

        reminders_to_insert: list[dict[str, Any]] = []
        hb_seen_at: float | None = None
        has_bedtime_migration = False
        reminder_orphans = 0
        if "v1_import_reminders" not in applied:
            raw_reminders, hb_seen_at, has_bedtime_migration = _read_legacy_reminder_data(reminders_db)
            for item in raw_reminders:
                cname = item["character_name"].strip()
                if cname == "*":
                    cid = "*"
                else:
                    cid = name_to_id.get(cname.casefold(), cname)
                    if cid == cname:
                        reminder_orphans += 1
                reminders_to_insert.append({**item, "character_id": cid})

        now = time.time()
        with self._engine.write_connection() as connection:
            self._insert_all_in_transaction(
                connection,
                now=now,
                applied=applied,
                characters_to_insert=characters_to_insert,
                backgrounds_to_insert=backgrounds_to_insert,
                effects_to_insert=effects_to_insert,
                conversations_to_insert=conversations_to_insert,
                kb_rows_to_insert=kb_rows_to_insert,
                kb_orphans=kb_orphans,
                reminders_to_insert=reminders_to_insert,
                hb_seen_at=hb_seen_at,
                has_bedtime_migration=has_bedtime_migration,
                reminder_orphans=reminder_orphans,
            )

    def _insert_all_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        now: float,
        applied: set[str],
        characters_to_insert: list[tuple[int, Character]],
        backgrounds_to_insert: list[tuple[int, Background]],
        effects_to_insert: list[tuple[int, Effect]],
        conversations_to_insert: list[ConversationRecord],
        kb_rows_to_insert: list[tuple[str, str, str]],
        kb_orphans: int,
        reminders_to_insert: list[dict[str, Any]],
        hb_seen_at: float | None,
        has_bedtime_migration: bool,
        reminder_orphans: int,
    ) -> None:
        for sort_order, char in characters_to_insert:
            connection.execute(
                """
                INSERT OR IGNORE INTO characters(
                    id, name, sprite_prefix, is_builtin, pinned, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    char.id,
                    char.name,
                    char.sprite_prefix,
                    int(bool(char.is_builtin)),
                    int(bool(char.pinned)),
                    sort_order,
                    self._char_codec.encode(char).decode("utf-8"),
                    now,
                ),
            )
        for sort_order, bg in backgrounds_to_insert:
            connection.execute(
                """
                INSERT OR IGNORE INTO backgrounds(
                    id, name, sprite_prefix, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bg.id,
                    bg.name,
                    bg.sprite_prefix,
                    sort_order,
                    self._bg_codec.encode(bg).decode("utf-8"),
                    now,
                ),
            )
        for sort_order, ef in effects_to_insert:
            connection.execute(
                """
                INSERT OR IGNORE INTO effects(
                    id, name, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ef.id,
                    ef.name,
                    sort_order,
                    self._ef_codec.encode(ef).decode("utf-8"),
                    now,
                ),
            )
        for rec in conversations_to_insert:
            connection.execute(
                """
                INSERT OR IGNORE INTO conversations(
                    id, history_path, title, created_at, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.id,
                    rec.history_path,
                    rec.title,
                    rec.created_at,
                    json.dumps(rec.to_legacy_dict(), ensure_ascii=False),
                    now,
                ),
            )
        for char_id, knowledge_id, created_at in kb_rows_to_insert:
            connection.execute(
                """
                INSERT INTO character_knowledge_bindings(character_id, knowledge_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(character_id, knowledge_id) DO UPDATE SET
                    created_at = MIN(character_knowledge_bindings.created_at, excluded.created_at)
                """,
                (char_id, knowledge_id, created_at),
            )
        for rem in reminders_to_insert:
            connection.execute(
                """
                INSERT OR IGNORE INTO reminders(
                    id, character_id, title, message, due_at, recurrence, status,
                    claim_token, claim_until, delivery_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rem["id"],
                    rem["character_id"],
                    rem["title"],
                    rem["message"],
                    rem["due_at"],
                    rem["recurrence"],
                    rem["status"],
                    rem["claim_token"],
                    rem["claim_until"],
                    rem["delivery_count"],
                    rem["created_at"],
                    rem["updated_at"],
                ),
            )
        if hb_seen_at is not None:
            connection.execute(
                "INSERT OR IGNORE INTO reminder_heartbeat(id, seen_at) VALUES (1, ?)",
                (hb_seen_at,),
            )
        if has_bedtime_migration:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES ('reminder_native_bedtime', ?, '{}')",
                (now,),
            )

        # Promote legacy __self__.display_name -> name once YAML/conversation rows are in place.
        migrate_v2_self_persona_display_name(connection)

        # Bump catalog revisions for populated tables.
        rev_updates = {
            "characters": bool(characters_to_insert),
            "characters:static": bool(characters_to_insert),
            "backgrounds": bool(backgrounds_to_insert),
            "effects": bool(effects_to_insert),
            "conversations": bool(conversations_to_insert),
        }
        for meta_key, changed in rev_updates.items():
            if changed:
                connection.execute(
                    "INSERT INTO _catalog_meta(table_name, revision) VALUES (?, ?) "
                    "ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision",
                    (meta_key, uuid.uuid4().hex),
                )

        if "v1_import_yaml_catalogs" not in applied:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES (?, ?, ?)",
                (
                    "v1_import_yaml_catalogs",
                    now,
                    json.dumps(
                        {
                            "characters": len(characters_to_insert),
                            "backgrounds": len(backgrounds_to_insert),
                            "effects": len(effects_to_insert),
                        }
                    ),
                ),
            )
        if "v1_import_conversations" not in applied:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES (?, ?, ?)",
                (
                    "v1_import_conversations",
                    now,
                    json.dumps({"conversations": len(conversations_to_insert)}),
                ),
            )
        if "v1_import_knowledge_bindings" not in applied:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES (?, ?, ?)",
                (
                    "v1_import_knowledge_bindings",
                    now,
                    json.dumps({"bindings": len(kb_rows_to_insert), "orphans_skipped": kb_orphans}),
                ),
            )
        if "v1_import_reminders" not in applied:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES (?, ?, ?)",
                (
                    "v1_import_reminders",
                    now,
                    json.dumps({"reminders": len(reminders_to_insert), "orphan_names": reminder_orphans}),
                ),
            )

    def _relocate_state_and_cache(self) -> None:
        sys_yaml = self._layout.config_file("system_config.yaml")
        extracted_geometry = ""
        system_rewrite: dict[str, Any] | None = None
        if sys_yaml.is_file():
            try:
                raw_sys = yaml.safe_load(sys_yaml.read_text(encoding="utf-8"))
                if isinstance(raw_sys, dict) and str(raw_sys.get("chat_window_geometry_b64") or "").strip():
                    extracted_geometry = str(raw_sys["chat_window_geometry_b64"])
                    cleaned_raw = dict(raw_sys)
                    cleaned_raw.pop("chat_window_geometry_b64", None)
                    model = SystemConfig.model_validate(cleaned_raw)
                    system_rewrite = model.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude={"chat_window_geometry_b64"},
                    )
            except Exception:
                logger.warning("Could not parse legacy chat_window_geometry_b64 cleanly", exc_info=True)

        legacy_template_json = self._layout.config_file("template_tab_last_launch.json")
        extracted_template: dict[str, Any] | None = None
        if legacy_template_json.is_file():
            try:
                parsed = json.loads(legacy_template_json.read_text(encoding="utf-8"))
                if isinstance(parsed, dict) and parsed.get("version") == 1:
                    extracted_template = parsed
            except (OSError, ValueError):
                pass
        if extracted_template is not None:
            current_self_name = ""
            with self._engine.read_connection() as connection:
                row = connection.execute(
                    "SELECT name FROM characters WHERE id = ? LIMIT 1",
                    (SELF_PERSONA_ID,),
                ).fetchone()
                if row is not None:
                    current_self_name = str(row["name"] or "").strip()
            if current_self_name and not is_self_persona_name(current_self_name):
                extracted_template, _ = rename_template_session_dict(
                    extracted_template,
                    SELF_PERSONA_NAME,
                    current_self_name,
                )

        if extracted_geometry or extracted_template is not None:
            def _merge_ui_state(current: UiRuntimeState) -> UiRuntimeState:
                return current.model_copy(
                    update={
                        "chat_window_geometry_b64": (
                            current.chat_window_geometry_b64 or extracted_geometry
                        ),
                        "template_last_launch": (
                            current.template_last_launch
                            if current.template_last_launch is not None
                            else extracted_template
                        ),
                    }
                )

            self._ui_state_store.update(_merge_ui_state)

        if system_rewrite is not None:
            try:
                self._atomic_write_yaml(sys_yaml, system_rewrite)
            except Exception:
                logger.warning("Could not strip legacy chat_window_geometry_b64 cleanly", exc_info=True)

        for cache_name in ("plugin_registry_downloads.json", "llm_model_capabilities.json"):
            src_cache = self._layout.config_file(cache_name)
            dst_cache = self._layout.cache_file(cache_name)
            if src_cache.is_file() and not dst_cache.is_file():
                durable_mkdir(dst_cache.parent)
                shutil.move(str(src_cache), str(dst_cache))

        now = time.time()
        with self._engine.write_connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES (?, ?, '{}')",
                ("v1_relocate_state_and_cache", now),
            )

    def _archive_legacy_files(self) -> None:
        sources: list[Path] = [
            self._layout.config_file("characters.yaml"),
            self._layout.config_file("background.yaml"),
            self._layout.config_file("effect.yaml"),
            self._layout.config_file("template_tab_last_launch.json"),
            self._layout.config_dir / "conversations",
        ]
        for sqlite_file in (
            self._layout.data_dir / "knowledge" / "knowledge.db",
            self._layout.data_dir / "reminders.sqlite3",
        ):
            sources.append(sqlite_file)
            sources.append(Path(f"{sqlite_file}-wal"))
            sources.append(Path(f"{sqlite_file}-shm"))
        # If cache already existed at data/cache/, archive remaining legacy copies in data/config/.
        for cache_name in ("plugin_registry_downloads.json", "llm_model_capabilities.json"):
            if self._layout.config_file(cache_name).is_file() and self._layout.cache_file(cache_name).is_file():
                sources.append(self._layout.config_file(cache_name))

        existing_sources = [path for path in sources if path.exists()]
        if not existing_sources:
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self._layout.legacy_backup_dir / stamp
        suffix = 1
        while backup_dir.exists():
            backup_dir = self._layout.legacy_backup_dir / f"{stamp}_{suffix}"
            suffix += 1
        durable_mkdir(backup_dir)

        archived: list[str] = []
        for src in existing_sources:
            rel = src.relative_to(self._layout.data_dir)
            dst = backup_dir / rel
            durable_mkdir(dst.parent)
            shutil.move(str(src), str(dst))
            archived.append(rel.as_posix())

        readme = backup_dir / "README.txt"
        readme.write_text(
            "Shinsekai Storage Architecture Auto-Migration Backup\n"
            "=================================================\n\n"
            "Your legacy YAML/JSON/SQLite data has been automatically migrated into:\n"
            f"  - {self._layout.main_db_path.name}\n"
            f"  - state/ui_state.json\n"
            f"  - cache/\n\n"
            "These original files were preserved here rather than deleted for safety.\n"
            "Archived entries:\n" + "".join(f"  - {item}\n" for item in archived),
            encoding="utf-8",
        )

    @staticmethod
    def _atomic_write_yaml(target: Path, payload: dict[str, Any]) -> None:
        from sdk.file_io import durable_rename
        import tempfile

        durable_mkdir(target.parent)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                yaml.safe_dump(payload, handle, allow_unicode=True, default_flow_style=False, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            durable_rename(tmp_path, target, replace=True)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


__all__ = ["LegacyDataMigrator", "MAIN_DB_MIGRATIONS", "MIGRATION_KEYS"]
