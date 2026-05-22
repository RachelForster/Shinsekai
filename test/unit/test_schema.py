"""Unit tests for Pydantic config models — validation, defaults, aliases."""

import pytest
from pydantic import ValidationError

from config.schema import (
    Sprite,
    Character,
    Background,
    ApiConfig,
    SystemConfig,
    AppConfig,
)


class TestSprite:
    def test_minimal_sprite(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        s = Sprite(path=str(img))
        assert s.path is not None
        assert s.voice_path is None
        assert s.voice_text is None

    def test_full_sprite(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        voice = tmp_path / "test.wav"
        voice.write_text("fake audio")
        s = Sprite(path=str(img), voice_path=str(voice), voice_text="hello")
        assert s.voice_path is not None
        assert s.voice_text == "hello"

    def test_path_required(self):
        with pytest.raises(ValidationError):
            Sprite()


class TestCharacter:
    def test_minimal_character(self):
        c = Character(name="Alice", color="#fff", sprite_prefix="alice")
        assert c.name == "Alice"
        assert c.character_setting == ""
        assert c.sprite_scale == 1.0
        assert c.sprites == []
        assert c.emotion_tags == ""

    def test_full_character(self):
        c = Character(
            name="Alice",
            color="#ff0000",
            sprite_prefix="alice",
            character_setting="A brave warrior.",
            sprite_scale=1.5,
            emotion_tags="happy:0, sad:1",
            speech_speed=1.2,
        )
        assert c.character_setting == "A brave warrior."
        assert c.sprite_scale == 1.5
        assert c.speech_speed == 1.2

    def test_none_defaults_treated_as_default(self):
        """None values for DefaultIfNone fields should fall back to defaults."""
        c = Character(name="Bob", color="#000", sprite_prefix="bob", character_setting=None, sprite_scale=None)
        assert c.character_setting == ""
        assert c.sprite_scale == 1.0


class TestApiConfig:
    def test_defaults(self):
        ac = ApiConfig()
        assert ac.llm_provider == "Deepseek"
        assert ac.is_streaming is True
        assert ac.temperature == 0.7
        assert ac.tts_provider == "gpt-sovits"
        assert ac.t2i_provider == "comfyui"
        assert ac.compact_threshold == 0.4
        assert ac.compact_target_ratio == 0.3
        assert ac.history_recent_messages == 20
        assert ac.max_tool_result_chars == 6000
        assert ac.max_active_tool_groups == 3

    def test_custom_provider(self):
        ac = ApiConfig(llm_provider="ChatGPT", llm_api_key={"ChatGPT": "sk-xxx"}, llm_model={"ChatGPT": "gpt-4"})
        assert ac.llm_provider == "ChatGPT"
        assert ac.llm_api_key["ChatGPT"] == "sk-xxx"


class TestAppConfig:
    def test_valid_app_config(self, sample_app_config):
        assert len(sample_app_config.characters) >= 1
        assert sample_app_config.api_config is not None
        assert sample_app_config.system_config is not None

    def test_empty_characters_allowed(self):
        ac = AppConfig(
            characters=[],
            background_list=[],
            api_config=ApiConfig(),
            system_config=SystemConfig(),
        )
        assert ac.characters == []
