"""Integration and fault-injection tests for unified domain SQLite stores and 5-step auto-migration."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from application.chat.conversation_library import (
    list_conversations,
    remember_conversation,
    rename_conversation,
)
from application.runtime.stores import build_app_stores
from config.config_manager import ConfigManager
from config.models import (
    Background,
    Character,
    Effect,
    RelationEdge,
    RelationGraph,
    RelationNode,
    SELF_PERSONA_ID,
)
from config.perception import DEFAULT_PERCEPTION_MODEL, GGUF_MODEL_ID
from core.knowledge import bindings as legacy_kb
from core.storage.migrations.main_db import LegacyDataMigrator


def _create_legacy_workspace(root: Path) -> dict[str, Any]:
    data = root / "data"
    config = data / "config"
    config.mkdir(parents=True)

    # 1) Legacy api.yaml (GGUF model id + legacy vision default)
    (config / "api.yaml").write_text(
        yaml.safe_dump(
            {
                "llm_provider": "Deepseek",
                "vision_provider": "auto",
                "vision_model": {"deepseek": "deepseek-flash"},
                "perception_model": GGUF_MODEL_ID,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # 2) Legacy system_config.yaml with chat_window_geometry_b64 + invalid story flag
    (config / "system_config.yaml").write_text(
        yaml.safe_dump(
            {
                "ui_language": "ja",
                "chat_window_geometry_b64": "Z2VvbQ==",
                "story_system_enabled": "not-a-bool",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # 3) Legacy characters.yaml, background.yaml, effect.yaml
    (config / "characters.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "自设",
                    "color": "#94A3B8",
                    "sprite_prefix": "__self__",
                    "display_name": "主人公",
                },
                {
                    "name": "Alice",
                    "color": "#ff55aa",
                    "sprite_prefix": "alice",
                    "portrait_sprite_index": 2,
                    "sprites": [{"path": "data/sprite/alice/smile.png"}],
                },
                {
                    "name": "澪",
                    "color": "#3366ff",
                    "sprite_prefix": "mio",
                    "character_setting": "Bass player",
                },
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "background.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Clubroom",
                    "sprite_prefix": "clubroom",
                    "sprites": [{"path": "data/backgrounds/clubroom/day.png"}],
                }
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (config / "effect.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Sparkle",
                    "color": "#ffd700",
                    "prompt_text": "Play chime",
                }
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # 4) Legacy UI runtime state & caches in data/config/
    (config / "template_tab_last_launch.json").write_text(
        json.dumps(
            {
                "version": 1,
                "selected_characters": ["Alice", "澪"],
                "background": "Clubroom",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (config / "plugin_registry_downloads.json").write_text(
        json.dumps({"repos": ["owner/demo"], "entry_repo": {}, "entry_install": {}}),
        encoding="utf-8",
    )
    (config / "llm_model_capabilities.json").write_text(
        json.dumps({"Deepseek/deepseek-chat": {"vision": False}}),
        encoding="utf-8",
    )

    # 5) Legacy named conversation JSON + active.json on disk
    session_dir = (data / "chat_history" / "s1").resolve()
    session_dir.mkdir(parents=True)
    (session_dir / "active.json").write_text(
        json.dumps([{"role": "user", "content": "Hello"}], ensure_ascii=False),
        encoding="utf-8",
    )
    conv_id = hashlib.sha256(os.path.normcase(str(session_dir)).encode()).hexdigest()
    conv_dir = config / "conversations"
    conv_dir.mkdir()
    (conv_dir / f"{conv_id}.json").write_text(
        json.dumps(
            {
                "historyPath": session_dir.as_posix(),
                "title": "Evening chat",
                "createdAt": "2026-10-01T12:00:00+00:00",
                "launch": {"characters": ["Alice", "澪"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 6) Legacy knowledge.db
    kb_path = data / "knowledge" / "knowledge.db"
    kb_path.parent.mkdir(parents=True)
    kb_conn = sqlite3.connect(kb_path)
    try:
        with kb_conn:
            kb_conn.execute(
                """
                CREATE TABLE character_knowledge_bindings (
                    character_name TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (character_name, knowledge_id)
                )
                """
            )
            kb_conn.execute(
                "INSERT INTO character_knowledge_bindings VALUES ('Alice', 'lore-alice', '2026-09-01')"
            )
            kb_conn.execute(
                "INSERT INTO character_knowledge_bindings VALUES ('澪', 'lore-mio', '2026-09-02')"
            )
            kb_conn.execute(
                "INSERT INTO character_knowledge_bindings VALUES ('DeletedChar', 'lore-orphan', '2026-09-03')"
            )
    finally:
        kb_conn.close()

    # 7) Legacy reminders.sqlite3 (missing delivery_count column to test compat too)
    rem_path = data / "reminders.sqlite3"
    due = (datetime.now() + timedelta(hours=2)).timestamp()
    rem_conn = sqlite3.connect(rem_path)
    try:
        with rem_conn:
            rem_conn.execute(
                """
                CREATE TABLE reminders (
                    id TEXT PRIMARY KEY, character_name TEXT NOT NULL,
                    title TEXT NOT NULL, message TEXT NOT NULL, due_at REAL NOT NULL,
                    recurrence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                    claim_token TEXT, claim_until REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                )
                """
            )
            rem_conn.execute("CREATE TABLE heartbeat (id INTEGER PRIMARY KEY, seen_at REAL)")
            rem_conn.execute("CREATE TABLE migrations (name TEXT PRIMARY KEY)")
            rem_conn.execute("INSERT INTO heartbeat VALUES (1, ?)", (1700000000.0,))
            rem_conn.execute("INSERT INTO migrations VALUES ('native-bedtime')")
            rem_conn.execute(
                "INSERT INTO reminders VALUES ('r1', '澪', '茶会', '喝茶啦', ?, 'daily', 'active', NULL, 0, 1700000010.0, 1700000010.0)",
                (due,),
            )
            rem_conn.execute(
                "INSERT INTO reminders VALUES ('r2', '*', '随机', '伸懒腰', ?, 'once', 'active', NULL, 0, 1700000011.0, 1700000011.0)",
                (due,),
            )
            rem_conn.execute(
                "INSERT INTO reminders VALUES ('r3', 'DeletedChar', '旧约', '保留', ?, 'once', 'active', NULL, 0, 1700000012.0, 1700000012.0)",
                (due,),
            )
    finally:
        rem_conn.close()

    return {"conv_id": conv_id, "session_dir": session_dir}


def test_five_step_startup_auto_migration_rename_fk_and_idempotency(tmp_path: Path) -> None:
    info = _create_legacy_workspace(tmp_path)

    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        # 1) Migrated SQLite catalogs and order/IDs
        chars = stores.characters.list_catalog()
        assert [c.name for c in chars] == ["自设", "Alice", "澪"]
        assert chars[0].id == SELF_PERSONA_ID
        alice, mio = chars[1], chars[2]
        assert alice.portrait_sprite_index == 2
        assert alice.sprites[0].path == "data/sprite/alice/smile.png"

        assert [b.name for b in stores.backgrounds.list_all()] == ["Clubroom"]
        assert [e.name for e in stores.effects.list_all()] == ["Sparkle"]

        conv = stores.conversations.get(info["conv_id"])
        assert conv is not None and conv.title == "Evening chat"

        # 2) Legacy ApiConfig + SystemConfig codecs and UI state separation
        api_cfg = stores.api_settings.get()
        assert api_cfg.perception_model == DEFAULT_PERCEPTION_MODEL
        assert api_cfg.perception_use_gguf is True
        assert "deepseek" not in api_cfg.vision_model

        sys_raw = yaml.safe_load((tmp_path / "data" / "config" / "system_config.yaml").read_text(encoding="utf-8"))
        assert "chat_window_geometry_b64" not in sys_raw
        ui_state = stores.ui_state.get()
        assert ui_state.chat_window_geometry_b64 == "Z2VvbQ=="
        assert ui_state.template_last_launch["selected_characters"] == ["Alice", "澪"]

        # 3) Cache relocation & non-destructive legacy backup archival
        assert (tmp_path / "data" / "cache" / "plugin_registry_downloads.json").is_file()
        assert (tmp_path / "data" / "cache" / "llm_model_capabilities.json").is_file()

        assert not (tmp_path / "data" / "config" / "characters.yaml").exists()
        assert not (tmp_path / "data" / "knowledge" / "knowledge.db").exists()
        assert not (tmp_path / "data" / "reminders.sqlite3").exists()

        backups = list((tmp_path / "data" / "config" / "legacy_backup").iterdir())
        assert len(backups) == 1
        backup_dir = backups[0]
        assert (backup_dir / "README.txt").is_file()
        assert (backup_dir / "config" / "characters.yaml").is_file()
        assert (backup_dir / "knowledge" / "knowledge.db").is_file()
        assert (backup_dir / "reminders.sqlite3").is_file()

        # 4) Knowledge bindings & reminders stitched to stable character_id (orphan KB skipped, orphan reminder kept)
        assert stores.knowledge_bindings.list_character_knowledge_bindings("Alice")["bindings"][0]["knowledge_id"] == "lore-alice"
        assert stores.knowledge_bindings.list_character_knowledge_bindings("澪")["bindings"][0]["knowledge_id"] == "lore-mio"
        assert stores.knowledge_bindings.list_character_knowledge_bindings("DeletedChar")["count"] == 0

        # Zero-cascade rename: update Mio -> 秋山澪 while preserving stable id!
        mio_renamed = mio.model_copy(update={"name": "秋山澪"})
        stores.characters.replace_all([chars[0], alice, mio_renamed])
        assert stores.knowledge_bindings.list_character_knowledge_bindings("秋山澪")["bindings"][0]["knowledge_id"] == "lore-mio"
        rems_by_id = {r["id"]: r for r in stores.reminders.manage("list")["reminders"]}
        assert rems_by_id["r1"]["character_name"] == "秋山澪"
        assert rems_by_id["r2"]["character_name"] == "*"
        assert rems_by_id["r3"]["character_name"] == "DeletedChar"

        # ON DELETE CASCADE: deleting Alice removes her knowledge bindings automatically.
        assert stores.characters.delete(alice.id) is True
        assert stores.knowledge_bindings.list_knowledge_binding_names("lore-alice")["characterNames"] == []

        # Delete all remaining characters & reminders to test idempotency across restart.
        stores.characters.replace_all([])
        for rid in ("r1", "r2", "r3"):
            stores.reminders.manage("delete", reminder_id=rid)
    finally:
        stores.close()

    # 5) Second startup must skip completed migrations (never resurrect deleted data from backup).
    reopened = build_app_stores(tmp_path, bind_globals=False)
    try:
        assert reopened.characters.list_all() == ()
        assert reopened.reminders.manage("list")["reminders"] == []
    finally:
        reopened.close()


def test_atomic_migration_rollback_on_mid_transaction_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_legacy_workspace(tmp_path)

    original_insert = LegacyDataMigrator._insert_all_in_transaction

    def crash_mid_transaction(self, connection, **kwargs):
        original_insert(self, connection, **kwargs)
        raise sqlite3.OperationalError("simulated disk full crash")

    monkeypatch.setattr(LegacyDataMigrator, "_insert_all_in_transaction", crash_mid_transaction)
    with pytest.raises(sqlite3.OperationalError, match="simulated disk full crash"):
        build_app_stores(tmp_path, bind_globals=False)

    # DB rolled back completely AND legacy source files remain untouched!
    check_conn = sqlite3.connect(tmp_path / "data" / "shinsekai.db")
    try:
        assert check_conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 0
        assert check_conn.execute("SELECT COUNT(*) FROM storage_migrations").fetchone()[0] == 0
    finally:
        check_conn.close()
    assert (tmp_path / "data" / "config" / "characters.yaml").is_file()
    assert (tmp_path / "data" / "knowledge" / "knowledge.db").is_file()
    assert (tmp_path / "data" / "reminders.sqlite3").is_file()

    # Retrying after fixing disk space succeeds cleanly.
    monkeypatch.undo()
    recovered = build_app_stores(tmp_path, bind_globals=False)
    try:
        assert len(recovered.characters.list_all()) == 3
        assert not (tmp_path / "data" / "config" / "characters.yaml").exists()
    finally:
        recovered.close()


def test_single_row_diff_update_and_static_revision_tracking(tmp_path: Path) -> None:
    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        initial_chars = [
            Character(name=f"Hero{i}", color="#123456", sprite_prefix=f"hero{i}")
            for i in range(10)
        ]
        stores.characters.replace_all(initial_chars)
        with stores.main_db.read_connection() as conn:
            before_rows = {
                str(r["id"]): float(r["updated_at"])
                for r in conn.execute("SELECT id, updated_at FROM characters")
            }

        rev_0 = stores.characters.revision
        static_rev_0 = stores.characters.static_revision

        # Mutate ONLY Hero3's relation_graph -> revision changes, static_revision stays unchanged!
        chars = list(stores.characters.list_all())
        chars[3] = chars[3].model_copy(
            update={
                "relation_graph": RelationGraph(
                    nodes=[RelationNode(key="Hero3"), RelationNode(key="Hero0")],
                    edges=[RelationEdge(source="Hero3", target="Hero0", temperature=5, content="Ally")],
                )
            }
        )
        stores.characters.replace_all(chars)
        rev_1 = stores.characters.revision
        static_rev_1 = stores.characters.static_revision
        assert rev_1 != rev_0
        assert static_rev_1 == static_rev_0

        with stores.main_db.read_connection() as conn:
            after_rows = {
                str(r["id"]): float(r["updated_at"])
                for r in conn.execute("SELECT id, updated_at FROM characters")
            }
        changed_ids = [cid for cid, ts in after_rows.items() if ts != before_rows[cid]]
        assert changed_ids == [chars[3].id]

        # Now mutate Hero3's character_setting -> BOTH revision and static_revision change!
        chars[3] = chars[3].model_copy(update={"character_setting": "Updated lore"})
        stores.characters.replace_all(chars)
        assert stores.characters.revision != rev_1
        assert stores.characters.static_revision != static_rev_1
    finally:
        stores.close()


def test_config_manager_and_conversation_store_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    stores = build_app_stores(tmp_path, bind_globals=True)
    prev_instance = ConfigManager._instance
    ConfigManager._instance = None
    try:
        cm = ConfigManager()
        assert cm.active_backend is not None
        cm.config.system_config.chat_window_geometry_b64 = "XYZ123=="
        cm.save_system_config()
        assert stores.ui_state.get().chat_window_geometry_b64 == "XYZ123=="

        # Conversation store via conversation_library
        hist_dir = tmp_path / "data" / "chat_history" / "chat-1"
        hist_dir.mkdir(parents=True)
        (hist_dir / "active.json").write_text("[]", encoding="utf-8")
        fake_state = SimpleNamespace(
            project_root_dir=str(tmp_path),
            history_dir=str(tmp_path / "data" / "chat_history"),
            template_dir_path=str(tmp_path / "data" / "character_templates"),
            config_manager=cm,
            stores=stores,
        )
        remember_conversation(fake_state, hist_dir, {"characters": ["Alice"], "templateName": "Demo"})
        items = list_conversations(fake_state)
        assert len(items) == 1
        assert items[0]["title"] == "Demo"
        rename_conversation(fake_state, items[0]["id"], "Renamed Chat")
        assert list_conversations(fake_state)[0]["title"] == "Renamed Chat"

        # Bindings delegate to unified store when CWD == project_root
        char = Character(name="Saber", color="#2244aa", sprite_prefix="saber")
        stores.characters.put(char.id, char)
        legacy_kb.bind_character_knowledge("Saber", "holy-grail")
        assert legacy_kb.list_knowledge_ids_for_characters(["Saber"]) == ["holy-grail"]
    finally:
        ConfigManager._instance = prev_instance
        stores.close()
