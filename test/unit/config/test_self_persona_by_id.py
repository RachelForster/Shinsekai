"""Unit tests verifying immutable ID-based built-in self-persona behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from application.chat.history.session_store import load_template_session, save_template_session
from application.chat.player_control import resolve_player, resolve_player_display_name
from application.chat.templates import (
    _reconcile_template_session_characters,
    _rename_template_session_character,
)
from config.character_ops import ConfigManagerCharacterTarget, save_character_patch
from config.config_manager import ConfigManager
from config.schema import (
    Character,
    SELF_PERSONA_ID,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
    build_default_self_persona,
)


def _make_config_manager(characters: list[Character]) -> ConfigManager:
    cfg_mgr = ConfigManager.__new__(ConfigManager)
    cfg_mgr._stores = None
    cfg_mgr._config = SimpleNamespace(
        characters=characters,
        system_config=SimpleNamespace(ui_language="zh_CN", voice_language="ja"),
    )
    cfg_mgr.save_characters_config = lambda: None  # type: ignore[method-assign]
    return cfg_mgr


def test_character_model_self_persona_invariants() -> None:
    renamed = Character(
        id=SELF_PERSONA_ID,
        name="浅羽",
        color="#112233",
        sprite_prefix="",
        is_builtin=False,
        pinned=False,
        undeletable=False,
    )
    assert renamed.id == SELF_PERSONA_ID
    assert renamed.name == "浅羽"
    assert renamed.sprite_prefix == SELF_PERSONA_SPRITE_PREFIX
    assert renamed.is_builtin is True
    assert renamed.pinned is True
    assert renamed.undeletable is True

    legacy = Character(name=SELF_PERSONA_NAME, color="#445566", sprite_prefix="")
    assert legacy.id == SELF_PERSONA_ID
    assert legacy.sprite_prefix == SELF_PERSONA_SPRITE_PREFIX
    assert legacy.is_builtin is True
    assert legacy.pinned is True
    assert legacy.undeletable is True

    normal = Character(name="Mika", color="#ffffff", sprite_prefix="mika")
    assert normal.id != SELF_PERSONA_ID
    assert normal.is_builtin is False
    assert normal.pinned is False
    assert normal.undeletable is False


def test_self_persona_rename_roundtrip_legacy_lookup_and_player_control() -> None:
    cfg_mgr = _make_config_manager(
        [
            build_default_self_persona(),
            Character(name="Mika", color="#ffffff", sprite_prefix="mika"),
        ]
    )
    target = ConfigManagerCharacterTarget(cfg_mgr)

    saved, renamed_from, created = save_character_patch(
        target,
        {"name": "浅羽", "display_name": "", "sprite_prefix": SELF_PERSONA_SPRITE_PREFIX},
        original_name=SELF_PERSONA_NAME,
    )
    assert created is False
    assert renamed_from == SELF_PERSONA_NAME
    assert saved.id == SELF_PERSONA_ID
    assert saved.name == "浅羽"
    assert cfg_mgr.get_self_persona().name == "浅羽"
    assert cfg_mgr.get_character_by_name(SELF_PERSONA_NAME) is cfg_mgr.get_self_persona()

    assert resolve_player(cfg_mgr, ["浅羽", "Mika"], SELF_PERSONA_NAME) == "浅羽"
    assert resolve_player(cfg_mgr, ["浅羽", "Mika"], SELF_PERSONA_ID) == "浅羽"
    assert resolve_player_display_name(cfg_mgr, SELF_PERSONA_NAME) == "浅羽"

    reverted, reverted_from, _ = save_character_patch(
        target,
        {"name": SELF_PERSONA_NAME, "sprite_prefix": SELF_PERSONA_SPRITE_PREFIX},
        target_id=SELF_PERSONA_ID,
    )
    assert reverted_from == "浅羽"
    assert reverted.id == SELF_PERSONA_ID
    assert reverted.name == SELF_PERSONA_NAME


def test_template_session_rename_and_reconcile_cascade_player_only_self_persona(tmp_path: Path) -> None:
    tpl_dir = tmp_path / "data" / "character_templates"
    tpl_dir.mkdir(parents=True)
    cfg_mgr = _make_config_manager(
        [
            build_default_self_persona(),
            Character(name="Mika", color="#ffffff", sprite_prefix="mika"),
        ]
    )
    state = SimpleNamespace(template_dir_path=str(tpl_dir), config_manager=cfg_mgr)

    save_template_session(
        str(tpl_dir),
        {
            "selected_characters": ["Mika"],
            "primary_characters": [],
            "player_character": SELF_PERSONA_NAME,
            "init_sprite_path": "",
        },
    )
    cfg_mgr.config.characters[0] = cfg_mgr.config.characters[0].model_copy(update={"name": "浅羽"})

    _rename_template_session_character(state, SELF_PERSONA_NAME, "浅羽")
    updated = load_template_session(str(tpl_dir))
    assert updated is not None
    assert updated["selected_characters"] == ["Mika"]
    assert updated["player_character"] == "浅羽"

    reconciled = _reconcile_template_session_characters(
        state,
        {
            "selected_characters": ["Mika"],
            "primary_characters": [],
            "player_character": SELF_PERSONA_NAME,
            "init_sprite_path": "",
        },
    )
    assert reconciled is not None
    assert reconciled["player_character"] == "浅羽"
