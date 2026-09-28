"""Tests for the shared asset-selection entry point."""

import pytest

from config.character_assets import get_character_assets
from config.schema import Character


def _character(**overrides):
    kwargs = dict(name="Alice", color="#fff", sprite_prefix="alice")
    kwargs.update(overrides)
    return Character(**kwargs)


class TestGetCharacterAssets:
    def test_static_returns_root_sprites(self, tmp_path):
        img = tmp_path / "smile.png"
        img.write_text("x")
        character = _character(
            sprites=[{"path": str(img)}],
            emotion_tags="立绘 1：微笑",
        )
        assets = get_character_assets(character, "static")
        assert assets.model_path == ""
        assert len(assets.sprites) == 1
        assert assets.emotion_tags == "立绘 1：微笑"

    def test_empty_avatar_type_defaults_to_static(self, tmp_path):
        img = tmp_path / "smile.png"
        img.write_text("x")
        character = _character(sprites=[{"path": str(img)}])
        assets = get_character_assets(character, "")
        assert assets.model_path == ""
        assert len(assets.sprites) == 1

    def test_model_type_returns_registered_sprites(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text("{}")
        character = _character(
            avatar_type="l2d",
            avatars={
                "l2d": {
                    "model_path": str(tmp_path / "m.model3.json"),
                    "sprites": [{"path": str(state)}],
                    "emotion_tags": "立绘 1：侧头",
                }
            },
        )
        assets = get_character_assets(character, "l2d")
        assert assets.model_path.endswith("m.model3.json")
        assert assets.emotion_tags == "立绘 1：侧头"

    def test_unknown_format_raises(self):
        character = _character()
        with pytest.raises(KeyError):
            get_character_assets(character, "gltf")

    def test_unknown_bank_survives_configuration_roundtrip(self):
        character = _character(avatar_type="Future", avatars={"Future": {"model_path": "model.future"}})
        restored = Character.model_validate(character.model_dump())
        assert restored.avatar_type == "future"
        assert get_character_assets(restored, " FUTURE ").model_path == "model.future"

    @pytest.mark.parametrize("banks", [{"static": {}}, {"": {}}, {" VRM ": {}, "vrm": {}}])
    def test_ambiguous_bank_names_are_rejected(self, banks):
        with pytest.raises(ValueError):
            _character(avatars=banks)
