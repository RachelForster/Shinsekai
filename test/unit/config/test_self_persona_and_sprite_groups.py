"""Unit tests for Phase 4 built-in '自设' persona and sprite outfit group management."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import zipfile

import yaml

from ai.llm.template_generator import TemplateGenerator
from application.characters.management import CharacterOperation, CharacterRequest, CharacterUseCase
from application.characters.sprite.auto_group_sprites import (
    analyze_character_sprite_groups,
)
from application.chat.player_control import resolve_player, resolve_player_display_name
from config.character_config import CharacterConfig
from config.character_manager import CharacterManager
from config.config_manager import ConfigManager
from config.schema import (
    Character,
    DEFAULT_SPRITE_GROUP,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
    Sprite,
    build_default_self_persona,
)
from config.sprite_groups import (
    filter_sprite_indices_for_group,
    has_multiple_sprite_groups,
    list_character_sprite_groups,
    resolve_default_sprite_group,
)
from tools.file_util import export_character, import_character


class _FakeConfigManager:
    def __init__(self, characters: list[Character]):
        self.config = SimpleNamespace(
            characters=characters,
            system_config=SimpleNamespace(voice_language="ja", ui_language="zh_CN"),
        )
        self.save_count = 0

    def get_character_by_name(self, name: str):
        found = next((c for c in self.config.characters if c.name == name), None)
        if found is not None:
            return found
        if name.strip() == SELF_PERSONA_NAME:
            return build_default_self_persona()
        return None

    def ensure_self_persona_persisted(self):
        existing = next(
            (c for c in self.config.characters if c.name == SELF_PERSONA_NAME),
            None,
        )
        if existing is None:
            existing = build_default_self_persona()
            self.config.characters.insert(0, existing)
        return existing

    def get_background_by_name(self, _name: str):
        return None

    def save_characters_config(self):
        self.save_count += 1


def _build_manager(characters: list[Character]) -> CharacterManager:
    mgr = CharacterManager.__new__(CharacterManager)
    mgr._config_manager = _FakeConfigManager(characters)
    return mgr


def test_self_persona_catalog_pinned_first_without_mutating_raw_app_config():
    cfg_mgr = ConfigManager.__new__(ConfigManager)
    cfg_mgr._config = SimpleNamespace(
        characters=[
            Character(name="Mika", color="#fff", sprite_prefix="mika"),
            Character(name="Nanami", color="#eee", sprite_prefix="nanami"),
        ]
    )

    assert [c.name for c in cfg_mgr.config.characters] == ["Mika", "Nanami"]

    catalog = cfg_mgr.list_characters_catalog()
    assert [c.name for c in catalog] == [SELF_PERSONA_NAME, "Mika", "Nanami"]
    assert catalog[0].is_builtin is True
    assert catalog[0].pinned is True
    assert catalog[0].undeletable is True
    assert catalog[0].sprite_prefix == SELF_PERSONA_SPRITE_PREFIX

    cfg_mgr.config.characters.append(
        Character(
            name=SELF_PERSONA_NAME,
            color="#aabbcc",
            sprite_prefix="",
            character_setting="热爱天文学的旅行者",
        )
    )
    catalog2 = cfg_mgr.list_characters_catalog()
    assert [c.name for c in catalog2] == [SELF_PERSONA_NAME, "Mika", "Nanami"]
    assert catalog2[0].character_setting == "热爱天文学的旅行者"
    assert catalog2[0].sprite_prefix == SELF_PERSONA_SPRITE_PREFIX
    assert catalog2[0].is_builtin is True


def test_self_persona_cannot_be_deleted_renamed_or_collided():
    self_char = build_default_self_persona()
    mika = Character(name="Mika", color="#fff", sprite_prefix="mika")
    mgr = _build_manager([self_char, mika])

    msg_del, names_del = mgr.delete_character(SELF_PERSONA_NAME)
    assert "不可删除" in msg_del
    assert SELF_PERSONA_NAME in names_del

    msg_ren, _ = mgr.add_character(
        "OtherName",
        "#fff",
        "other",
        "",
        "",
        "",
        "",
        "",
        "设定",
        edit_as_name=SELF_PERSONA_NAME,
    )
    assert "不可重命名" in msg_ren

    msg_into_self, _ = mgr.add_character(
        SELF_PERSONA_NAME,
        "#fff",
        "mika",
        "",
        "",
        "",
        "",
        "",
        "设定",
        edit_as_name="Mika",
    )
    assert "不能将其他角色重命名" in msg_into_self

    msg_prefix_collision, _ = mgr.add_character(
        "Stranger",
        "#fff",
        SELF_PERSONA_SPRITE_PREFIX,
        "",
        "",
        "",
        "",
        "",
        "设定",
    )
    assert "占用" in msg_prefix_collision

    msg_ok, _ = mgr.add_character(
        SELF_PERSONA_NAME,
        "#89b4fa",
        SELF_PERSONA_SPRITE_PREFIX,
        "",
        "",
        "",
        "",
        "",
        "一名精通古文献修复的大学生",
        edit_as_name=SELF_PERSONA_NAME,
    )
    assert "已更新" in msg_ok
    saved = mgr._config_manager.get_character_by_name(SELF_PERSONA_NAME)
    assert saved.character_setting == "一名精通古文献修复的大学生"
    assert saved.is_builtin is True
    assert saved.undeletable is True


def test_self_persona_display_name_survives_save_and_reload(tmp_path):
    mgr = _build_manager([])
    config = mgr._config_manager
    config.config.api_config = SimpleNamespace()
    path = tmp_path / "characters.yaml"

    def save():
        path.write_text(
            yaml.safe_dump([item.model_dump(mode="json") for item in config.config.characters]),
            encoding="utf-8",
        )

    def reload():
        config.config.characters = [
            Character.model_validate(value) for value in yaml.safe_load(path.read_text(encoding="utf-8"))
        ]

    config.save_characters_config = save
    config.reload = reload
    use_case = CharacterUseCase(SimpleNamespace(
        config_manager=config, character_manager=mgr, project_root_dir=tmp_path,
    ))
    persona = build_default_self_persona().model_dump(mode="json")
    updated = use_case.execute(CharacterRequest(CharacterOperation.SAVE, {
        "originalName": SELF_PERSONA_NAME,
        "character": {**persona, "display_name": "  Robin  "},
    }))
    assert updated["display_name"] == "Robin"
    assert [c.name for c in config.config.characters] == [SELF_PERSONA_NAME]
    assert updated["sprite_prefix"] == SELF_PERSONA_SPRITE_PREFIX
    assert updated["undeletable"] is True
    assert resolve_player(config, [], SELF_PERSONA_NAME) == SELF_PERSONA_NAME
    assert resolve_player_display_name(config, SELF_PERSONA_NAME) == "Robin"
    assert resolve_player_display_name(config, "") == "Robin"
    assert resolve_player_display_name(config, "", "Guest") == "Guest"

    use_case.execute(CharacterRequest(CharacterOperation.SAVE, {
        "originalName": SELF_PERSONA_NAME,
        "character": {**persona, "display_name": ""},
    }))
    assert resolve_player_display_name(config, SELF_PERSONA_NAME) == SELF_PERSONA_NAME


def test_cha_import_blocks_overwriting_self_persona_and_preserves_sprite_groups(
    tmp_path, monkeypatch
):
    sprite_dir = tmp_path / "sprite"
    voice_dir = tmp_path / "speech"
    chars_yaml = tmp_path / "characters.yaml"
    sprite_dir.mkdir()
    voice_dir.mkdir()
    chars_yaml.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr("tools.file_util.SPRITE_DIR", sprite_dir)
    monkeypatch.setattr("tools.file_util.SPEECH_DIR", voice_dir)
    monkeypatch.setattr("tools.file_util.CHARACTERS_CONFIG_PATH", chars_yaml)
    monkeypatch.setattr("tools.file_util._open_export_folder", lambda _p: True)

    bad_cha = tmp_path / "forged_self.cha"
    with zipfile.ZipFile(bad_cha, "w") as zf:
        zf.writestr(
            "character.yaml",
            "- name: 自设\n  color: '#ffffff'\n  sprite_prefix: __self__\n  is_builtin: true\n  undeletable: true\n",
        )
    imported_forged = import_character(str(bad_cha))
    assert len(imported_forged) == 1
    assert imported_forged[0].name == "自设（1）"
    assert imported_forged[0].sprite_prefix == "__self__1"
    persisted_yaml = chars_yaml.read_text(encoding="utf-8")
    assert "is_builtin: true" not in persisted_yaml
    assert "undeletable: true" not in persisted_yaml

    char_root = sprite_dir / "nanami"
    char_root.mkdir(parents=True)
    img1 = char_root / "school_01.png"
    img2 = char_root / "pajama_01.png"
    img1.write_bytes(b"PNG1")
    img2.write_bytes(b"PNG2")

    nanami_cfg = CharacterConfig.parse_dic(
        {
            "name": "Nanami",
            "color": "#ff99aa",
            "sprite_prefix": "nanami",
            "sprites": [
                {"path": img1.as_posix(), "group": "校服"},
                {"path": img2.as_posix(), "group": "睡衣"},
            ],
            "sprite_groups": ["校服", "睡衣"],
            "default_sprite_group": "校服",
            "fallback_to_default_group": False,
            "emotion_tags": "立绘 1：微笑\n立绘 2：困倦\n",
        }
    )
    exported_cha = tmp_path / "Nanami.cha"
    export_character([nanami_cfg], str(exported_cha), open_folder=False)
    assert exported_cha.is_file()

    fresh_sprite_dir = tmp_path / "fresh_sprite"
    fresh_chars_yaml = tmp_path / "fresh_characters.yaml"
    fresh_sprite_dir.mkdir()
    fresh_chars_yaml.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr("tools.file_util.SPRITE_DIR", fresh_sprite_dir)
    monkeypatch.setattr("tools.file_util.CHARACTERS_CONFIG_PATH", fresh_chars_yaml)

    imported_list = import_character(str(exported_cha))
    assert len(imported_list) == 1
    imported = imported_list[0]
    assert imported.name == "Nanami"
    assert imported.sprite_groups == ["校服", "睡衣"]
    assert imported.default_sprite_group == "校服"
    assert imported.fallback_to_default_group is False
    assert [s.get("group") for s in imported.sprites] == ["校服", "睡衣"]


def test_self_persona_prompt_injection_and_player_control(monkeypatch):
    mika = Character(
        name="Mika",
        color="#fff",
        sprite_prefix="mika",
        character_setting="活泼的青梅竹马。",
    )

    cfg_without_self = _FakeConfigManager([mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_without_self)
    prompt_base, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika"],
        "",
        False,
        False,
        False,
        player_character="",
    )

    cfg_empty_self = _FakeConfigManager([build_default_self_persona(), mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_empty_self)
    prompt_empty_self, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert prompt_empty_self == prompt_base

    populated_self = build_default_self_persona().model_copy(
        update={"character_setting": "表面冷静、内心细腻的古书店店长。"}
    )
    cfg_with_self = _FakeConfigManager([populated_self, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_with_self)
    prompt_with_self, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika"],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "表面冷静、内心细腻的古书店店长。" in prompt_with_self
    assert "自设" in prompt_with_self

    resolved = resolve_player(
        cfg_with_self,
        ["Mika"],
        SELF_PERSONA_NAME,
    )
    assert resolved == SELF_PERSONA_NAME


def test_save_sprite_groups_atomic_create_rename_delete_assign_and_auto_group():
    char = Character.model_construct(
        name="Aoi",
        color="#66ccff",
        sprite_prefix="aoi",
        avatar_type="static",
        avatars={},
        sprites=[
            Sprite.model_construct(path=Path("sprite/aoi/school_normal.png"), group=None),
            Sprite.model_construct(path=Path("sprite/aoi/school_smile.png"), group=None),
            Sprite.model_construct(path=Path("sprite/aoi/pajama/sleepy.png"), group=None),
            Sprite.model_construct(path=Path("sprite/aoi/swimsuit_shy.png"), group=None),
            Sprite.model_construct(path=Path("sprite/aoi/casual_01.png"), group=None),
        ],
        sprite_groups=[],
        default_sprite_group=None,
        fallback_to_default_group=True,
        emotion_tags=(
            "立绘 1：平静，校服\n"
            "立绘 2：微笑\n"
            "立绘 3：困倦\n"
            "立绘 4：害羞，泳装\n"
            "立绘 5：便服微笑\n"
        ),
    )
    mgr = _build_manager([char])

    preview = analyze_character_sprite_groups(char)
    assert preview["assignments"] == {
        "0": "校服",
        "1": "校服",
        "2": "睡衣",
        "3": "泳装",
        "4": "私服",
    }
    assert preview["changedCount"] == 5

    mgr.save_sprite_groups(
        "Aoi",
        assignments=preview["assignments"],
        sprite_groups=preview["spriteGroups"],
        default_sprite_group="校服",
        fallback_to_default_group=True,
    )
    assert has_multiple_sprite_groups(char) is True
    assert resolve_default_sprite_group(char) == "校服"
    assert filter_sprite_indices_for_group(char, "校服") == (0, 1)
    assert filter_sprite_indices_for_group(char, "睡衣") == (2,)
    assert filter_sprite_indices_for_group(char, "泳装") == (3,)

    mgr.save_sprite_groups(
        "Aoi",
        rename_from="私服",
        rename_to="日常服",
        delete_group="泳装",
    )
    assert char.sprites[4].group == "日常服"
    assert char.sprites[3].group is None
    assert list_character_sprite_groups(char) == ["校服", "睡衣", "日常服", DEFAULT_SPRITE_GROUP]
