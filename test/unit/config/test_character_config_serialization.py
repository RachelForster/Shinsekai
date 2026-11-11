from types import SimpleNamespace

import pytest
import yaml

from config.config_manager import ConfigManager
from config.schema import ApiConfig, AppConfig, Character, ModelSprites, Sprite, SystemConfig


def test_catalog_revision_changes_after_save_and_changed_reload_only(tmp_path, monkeypatch):
    manager = object.__new__(ConfigManager)
    manager._config = AppConfig(
        characters=[Character(name="Mika", color="", sprite_prefix="mika")],
        background_list=[],
        api_config=ApiConfig(),
        system_config=SystemConfig(),
    )
    manager._CHARACTERS_CONFIG_PATH = tmp_path / "characters.yaml"
    manager._BACKGOUND_CONFIG_PATH = tmp_path / "background.yaml"
    manager._BACKGOUND_CONFIG_PATH.write_text("[]", encoding="utf-8")
    initial = manager.characters_revision
    manager.save_characters_config()
    saved = manager.characters_revision
    assert saved and saved != initial
    manager.refresh_media_catalogs()
    assert manager.characters_revision == saved

    # Simulate changed data loaded from disk without an HTTP save route.
    data = yaml.safe_load(manager._CHARACTERS_CONFIG_PATH.read_text(encoding="utf-8"))
    data[0]["character_setting"] = "changed outside the frontend"
    manager._CHARACTERS_CONFIG_PATH.write_text(yaml.safe_dump(data), encoding="utf-8")
    manager.refresh_media_catalogs()
    assert manager.characters_revision != saved
    assert manager.config.characters[0].character_setting == "changed outside the frontend"

    revision = manager.characters_revision

    def fail_save(*args):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_save_single_config", fail_save)
    with pytest.raises(OSError, match="disk full"):
        manager.save_characters_config()
    assert manager.characters_revision == revision


def test_full_reload_tracks_catalog_changes_and_preserves_unchanged_version(tmp_path):
    manager = object.__new__(ConfigManager)
    manager._config = None
    for attribute, filename, content in (
        ("_API_CONFIG_PATH", "api.yaml", "{}"),
        ("_SYSTEM_CONFIG_PATH", "system.yaml", "{}"),
        ("_CHARACTERS_CONFIG_PATH", "characters.yaml", "[]"),
        ("_BACKGOUND_CONFIG_PATH", "background.yaml", "[]"),
        ("_EFFECT_CONFIG_PATH", "effects.yaml", "[]"),
    ):
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        setattr(manager, attribute, path)
    manager.reload()
    initial = manager.characters_revision
    assert initial
    manager.reload()
    assert manager.characters_revision == initial
    manager._CHARACTERS_CONFIG_PATH.write_text(
        yaml.safe_dump([{"name": "Added by host", "color": "", "sprite_prefix": "added"}]),
        encoding="utf-8",
    )
    manager.reload()
    assert manager.characters_revision != initial
    assert manager.config.characters[0].name == "Added by host"


def test_unloaded_character_config_cannot_report_a_successful_save():
    manager = object.__new__(ConfigManager)
    manager._config = None
    with pytest.raises(RuntimeError, match="无法保存角色配置"):
        manager.save_characters_config()


@pytest.mark.parametrize("avatar_type", ["static", "l2d", "vrm"])
def test_character_config_paths_round_trip_through_safe_yaml(tmp_path, avatar_type):
    state_path = tmp_path / "状态.json"
    image_path = tmp_path / "立绘.png"
    voice_path = tmp_path / "语音.wav"
    for path in (state_path, image_path, voice_path):
        path.touch()
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        avatar_type=avatar_type,
        sprites=[Sprite(path=image_path, portrait_crop={"zoom": 1.2})],
        emotion_tags="静态立绘",
        avatars={
            "l2d": ModelSprites(
                model_path="Haru.model3.json",
                sprites=[Sprite(
                    path=state_path,
                    voice_path=voice_path,
                    voice_text="你好",
                    voice_type="reference",
                )],
                emotion_tags="状态1：微笑",
            ),
            "vrm": ModelSprites(model_path="avatar.vrm"),
        },
    )
    manager = object.__new__(ConfigManager)
    manager._config = SimpleNamespace(characters=[character])
    manager._CHARACTERS_CONFIG_PATH = tmp_path / "characters.yaml"

    # Exercise the actual writer, not a fake that already uses JSON-mode dumps.
    manager.save_characters_config()

    saved_text = manager._CHARACTERS_CONFIG_PATH.read_text(encoding="utf-8")
    assert "!!python" not in saved_text
    saved = yaml.safe_load(saved_text)
    assert saved[0]["sprites"][0]["path"] == str(image_path)
    state = saved[0]["avatars"]["l2d"]["sprites"][0]
    assert state["path"] == str(state_path)
    assert state["voice_path"] == str(voice_path)
    reloaded = Character.model_validate(manager._load_yaml(manager._CHARACTERS_CONFIG_PATH)[0])
    assert reloaded.model_dump(mode="json", by_alias=True) == character.model_dump(
        mode="json", by_alias=True,
    )
