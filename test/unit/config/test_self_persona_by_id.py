"""Unit tests verifying immutable ID-based built-in self-persona behavior."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from ai.llm.template_generator import TemplateGenerator
from application.chat.conversation_library import (
    conversation_launch_payload,
    remember_conversation,
    update_conversation_character,
)
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


def _setup_template_generator(monkeypatch, cfg_mgr: ConfigManager) -> TemplateGenerator:
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_mgr)
    monkeypatch.setattr("ai.llm.template_generator._format_llm_tools_block", lambda: "")
    cfg_mgr.get_background_by_name = lambda _name: None  # type: ignore[method-assign]
    generator = TemplateGenerator(output_contract_patches=[])
    generator.resolve_chat_template_characters = lambda names: [  # type: ignore[method-assign]
        (c.name, c) for c in cfg_mgr.config.characters if c.name in names
    ]
    return generator


def test_rename_template_session_regenerates_non_manual_and_protects_manual(
    tmp_path: Path, monkeypatch
) -> None:
    tpl_dir = tmp_path / "data" / "character_templates"
    tpl_dir.mkdir(parents=True)
    self_char = build_default_self_persona().model_copy(
        update={"character_setting": "喜欢观星和黑咖啡"}
    )
    mika = Character(
        name="Mika", color="#ffffff", sprite_prefix="mika", character_setting="天文社成员"
    )
    cfg_mgr = _make_config_manager([self_char, mika])
    generator = _setup_template_generator(monkeypatch, cfg_mgr)
    state = SimpleNamespace(
        template_dir_path=str(tpl_dir),
        config_manager=cfg_mgr,
        template_generator=generator,
    )

    # 1) Player-only non-manual session
    save_template_session(
        str(tpl_dir),
        {
            "selected_characters": ["Mika"],
            "primary_characters": [],
            "player_character": SELF_PERSONA_NAME,
            "system_template_text": "主控人物：自设",
            "system_manually_edited": False,
            "init_sprite_path": "",
        },
    )
    cfg_mgr.config.characters[0] = self_char.model_copy(update={"name": "浅羽"})
    _rename_template_session_character(state, SELF_PERSONA_NAME, "浅羽")
    updated = load_template_session(str(tpl_dir))
    assert updated is not None
    assert updated["player_character"] == "浅羽"
    assert "浅羽" in updated["system_template_text"]
    assert "主控人物：自设" not in updated["system_template_text"]

    # 2) Background-only self-persona (no direct mention in selected/player) also refreshes
    cfg_mgr.config.characters[0] = self_char.model_copy(update={"name": SELF_PERSONA_NAME})
    save_template_session(
        str(tpl_dir),
        {
            "selected_characters": ["Mika"],
            "primary_characters": [],
            "player_character": "",
            "system_template_text": "【用户自设设定】\n喜欢观星和黑咖啡",
            "system_manually_edited": False,
            "init_sprite_path": "",
        },
    )
    cfg_mgr.config.characters[0] = self_char.model_copy(update={"name": "浅羽"})
    _rename_template_session_character(state, SELF_PERSONA_NAME, "浅羽")
    bg_updated = load_template_session(str(tpl_dir))
    assert bg_updated is not None
    assert "人物名：浅羽（该人物是用户自设。）" in bg_updated["system_template_text"]

    # 3) Manually edited session system prompt is preserved verbatim
    save_template_session(
        str(tpl_dir),
        {
            "selected_characters": ["Mika"],
            "primary_characters": [],
            "player_character": SELF_PERSONA_NAME,
            "system_template_text": "CUSTOM_HANDWRITTEN_自设",
            "system_manually_edited": True,
            "init_sprite_path": "",
        },
    )
    _rename_template_session_character(state, SELF_PERSONA_NAME, "浅羽")
    manual = load_template_session(str(tpl_dir))
    assert manual is not None
    assert manual["player_character"] == "浅羽"
    assert manual["system_template_text"] == "CUSTOM_HANDWRITTEN_自设"


def test_update_conversation_and_launch_payload_regenerate_stale_non_manual_prompts(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    tpl_dir = data_dir / "character_templates"
    tpl_dir.mkdir(parents=True)
    hist_root = data_dir / "chat_history"
    hist_root.mkdir(parents=True)

    self_char = build_default_self_persona().model_copy(update={"character_setting": "晨间散步爱好者"})
    mika = Character(name="Mika", color="#ffffff", sprite_prefix="mika", character_setting="画师")
    cfg_mgr = _make_config_manager([self_char, mika])
    generator = _setup_template_generator(monkeypatch, cfg_mgr)
    state = SimpleNamespace(
        project_root_dir=tmp_path,
        history_dir=str(hist_root),
        template_dir_path=str(tpl_dir),
        config_manager=cfg_mgr,
        template_generator=generator,
        stores=None,
    )

    def _conv_id(folder: str) -> tuple[Path, str]:
        p = (hist_root / folder).resolve()
        p.mkdir(parents=True, exist_ok=True)
        (p / "active.json").write_text("[]", encoding="utf-8")
        return p, hashlib.sha256(os.path.normcase(str(p)).encode()).hexdigest()

    p_auto, id_auto = _conv_id("auto")
    p_manual, id_manual = _conv_id("manual")
    p_stale, id_stale = _conv_id("stale")

    remember_conversation(
        state,
        p_auto,
        {
            "characters": [SELF_PERSONA_NAME, "Mika"],
            "playerCharacter": SELF_PERSONA_NAME,
            "system": "旧：以下是自设的角色设定：",
            "editorSession": {
                "selectedCharacters": [SELF_PERSONA_NAME, "Mika"],
                "playerCharacter": SELF_PERSONA_NAME,
                "system": "旧：以下是自设的角色设定：",
                "systemManuallyEdited": False,
            },
        },
    )
    remember_conversation(
        state,
        p_manual,
        {
            "characters": [SELF_PERSONA_NAME, "Mika"],
            "playerCharacter": SELF_PERSONA_NAME,
            "system": "HANDWRITTEN_自设",
            "systemManuallyEdited": True,
        },
    )
    remember_conversation(
        state,
        p_stale,
        {
            "characters": ["浅羽", "Mika"],
            "playerCharacter": "浅羽",
            "system": "离线迁移前遗留自设",
            "systemStale": True,
        },
    )

    cfg_mgr.config.characters[0] = self_char.model_copy(update={"name": "浅羽"})
    update_conversation_character(state, SELF_PERSONA_NAME, "浅羽")

    conv_dir = data_dir / "config" / "conversations"
    auto_data = json.loads((conv_dir / f"{id_auto}.json").read_text(encoding="utf-8"))
    assert auto_data["launch"]["playerCharacter"] == "浅羽"
    assert "浅羽" in auto_data["launch"]["system"]
    assert "旧：以下是自设的角色设定：" not in auto_data["launch"]["system"]
    assert auto_data["launch"]["editorSession"]["system"] == auto_data["launch"]["system"]

    manual_data = json.loads((conv_dir / f"{id_manual}.json").read_text(encoding="utf-8"))
    assert manual_data["launch"]["playerCharacter"] == "浅羽"
    assert manual_data["launch"]["system"] == "HANDWRITTEN_自设"

    launched_stale = conversation_launch_payload(state, id_stale)
    assert "systemStale" not in launched_stale
    assert "浅羽" in launched_stale["system"]
    assert "离线迁移前遗留自设" not in launched_stale["system"]
