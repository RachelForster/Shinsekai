from types import SimpleNamespace

import pytest
import yaml

from config.config_manager import ConfigManager
from config.schema import Character, ModelSprites, Sprite


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
