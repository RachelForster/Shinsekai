"""Unit tests for SQLite v2 self-persona display_name promotion and legacy fallback."""

from __future__ import annotations

import json
from pathlib import Path
import time

from config.models import (
    Character,
    SELF_PERSONA_ID,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
)
from core.storage.layout import StorageLayout
from core.storage.migrations.main_db import MAIN_DB_MIGRATIONS
from core.storage.migrations.self_persona_migration import migrate_v2_self_persona_display_name
from core.storage.sqlite_engine import SqliteEngine
from core.storage.stores.character_store import SqliteCharacterCatalog


def _seed_v1_database(db_path: Path, *, self_display_name: str, other_name: str = "Mika") -> None:
    v1_engine = SqliteEngine("main", db_path, migrations=MAIN_DB_MIGRATIONS[:1])
    try:
        v1_engine.migrate()
        now = time.time()
        self_char = Character(
            id=SELF_PERSONA_ID,
            name=SELF_PERSONA_NAME,
            display_name=self_display_name,
            color="#89b4fa",
            sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
            character_setting="Starlit chronicler",
            is_builtin=True,
            pinned=True,
            undeletable=True,
            relation_graph={
                "nodes": [{"key": SELF_PERSONA_NAME}, {"key": other_name}],
                "edges": [{"source": SELF_PERSONA_NAME, "target": other_name, "temperature": 5, "content": "友"}],
            },
        )
        other_char = Character(
            id="char-mika",
            name=other_name,
            color="#ffffff",
            sprite_prefix="mika",
            relation_graph={
                "nodes": [{"key": other_name}, {"key": SELF_PERSONA_NAME}],
                "edges": [{"source": other_name, "target": SELF_PERSONA_NAME, "temperature": 8, "content": "搭档"}],
            },
        )
        conv_payload = {
            "id": "conv-1",
            "historyPath": "data/history/conv-1.json",
            "title": "Test Chat",
            "createdAt": "2026-01-01T00:00:00Z",
            "launch": {
                "playerCharacter": SELF_PERSONA_NAME,
                "characters": [SELF_PERSONA_NAME, other_name],
                "primaryCharacters": [SELF_PERSONA_NAME],
                "editorSession": {
                    "player_character": SELF_PERSONA_NAME,
                    "selected_characters": [SELF_PERSONA_NAME, other_name],
                },
            },
        }
        with v1_engine.write_connection() as conn:
            conn.execute(
                """
                INSERT INTO characters(
                    id, name, sprite_prefix, is_builtin, pinned, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, 1, 1, 0, ?, ?)
                """,
                (SELF_PERSONA_ID, SELF_PERSONA_NAME, SELF_PERSONA_SPRITE_PREFIX, self_char.model_dump_json(), now),
            )
            conn.execute(
                """
                INSERT INTO characters(
                    id, name, sprite_prefix, is_builtin, pinned, sort_order, payload_json, updated_at
                ) VALUES (?, ?, ?, 0, 0, 1, ?, ?)
                """,
                ("char-mika", other_name, "mika", other_char.model_dump_json(), now),
            )
            conn.execute(
                """
                INSERT INTO conversations(
                    id, history_path, title, created_at, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "conv-1",
                    "data/history/conv-1.json",
                    "Test Chat",
                    "2026-01-01T00:00:00Z",
                    json.dumps(conv_payload, ensure_ascii=False),
                    now,
                ),
            )
    finally:
        v1_engine.close()


def test_v2_migration_promotes_display_name_cascades_and_is_idempotent(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    _seed_v1_database(layout.main_db_path, self_display_name="浅羽")

    engine = SqliteEngine("main", layout.main_db_path, migrations=MAIN_DB_MIGRATIONS)
    try:
        engine.migrate()
        with engine.write_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == 2
            conv_row = conn.execute("SELECT payload_json FROM conversations WHERE id = 'conv-1'").fetchone()
            assert conv_row is not None
            conv_data = json.loads(conv_row[0])
            assert conv_data["launch"]["playerCharacter"] == "浅羽"
            assert conv_data["launch"]["characters"] == ["浅羽", "Mika"]
            assert conv_data["launch"]["primaryCharacters"] == ["浅羽"]
            assert conv_data["launch"]["editorSession"]["player_character"] == "浅羽"
            assert conv_data["launch"]["editorSession"]["selected_characters"] == ["浅羽", "Mika"]

            # Running helper again directly is a safe no-op
            migrate_v2_self_persona_display_name(conn)

        catalog = SqliteCharacterCatalog(engine)
        renamed_self = catalog.get(SELF_PERSONA_ID)
        assert renamed_self is not None
        assert renamed_self.name == "浅羽"
        assert renamed_self.display_name == ""
        assert renamed_self.relation_graph.nodes[0].key == "浅羽"

        mika = catalog.get_by_name("Mika")
        assert mika is not None
        assert [n.key for n in mika.relation_graph.nodes] == ["Mika", "浅羽"]
        assert mika.relation_graph.edges[0].target == "浅羽"

        # Legacy sentinel name resolves via __self__ fallback after rename
        assert catalog.get_by_name(SELF_PERSONA_NAME) == renamed_self
    finally:
        engine.close()


def test_v2_migration_skips_when_display_name_collides_with_other_character(tmp_path: Path) -> None:
    db_path = tmp_path / "collision.db"
    _seed_v1_database(db_path, self_display_name="Mika", other_name="Mika")

    engine = SqliteEngine("main", db_path, migrations=MAIN_DB_MIGRATIONS)
    try:
        engine.migrate()
        catalog = SqliteCharacterCatalog(engine)
        kept_self = catalog.get(SELF_PERSONA_ID)
        assert kept_self is not None
        assert kept_self.name == SELF_PERSONA_NAME
        assert kept_self.display_name == "Mika"
    finally:
        engine.close()
