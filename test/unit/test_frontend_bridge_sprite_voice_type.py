from types import SimpleNamespace

import pytest

from config.schema import Character
from frontend_bridge_core.characters import _save_sprite_voice_type, _upload_sprite_voice


class FakeCharacterManager:
    def __init__(self, character):
        self.character = character

    def save_sprite_voice_type(self, character_name, sprite_index, voice_type):
        sprite = self.character.sprites[sprite_index]
        if isinstance(sprite, dict):
            sprite["voice_type"] = voice_type
        else:
            sprite.voice_type = voice_type
        return "voice type saved"

    def upload_voice(self, character_name, sprite_index, voice_file, voice_text, voice_type=""):
        sprite = self.character.sprites[sprite_index]
        if isinstance(sprite, dict):
            sprite["voice_path"] = voice_file
            sprite["voice_text"] = voice_text
            sprite["voice_type"] = voice_type or None
        else:
            sprite.voice_path = voice_file
            sprite.voice_text = voice_text
            sprite.voice_type = voice_type or None
        return "voice uploaded", voice_file


class FakeConfigManager:
    def __init__(self, character):
        self.character = character

    def get_character_by_name(self, name):
        if name == self.character.name:
            return self.character
        return None

    def reload(self):
        pass


def make_state(character):
    return SimpleNamespace(
        character_manager=FakeCharacterManager(character),
        config_manager=FakeConfigManager(character),
    )


def make_character(**sprite_fields):
    return Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/0.png", **sprite_fields}],
    )


def test_upload_sprite_voice_rejects_invalid_voice_type(tmp_path):
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"not really audio")
    state = make_state(make_character())

    with pytest.raises(ValueError, match="voice type"):
        _upload_sprite_voice(
            state,
            {
                "name": "Mika",
                "spriteIndex": 0,
                "voicePath": str(voice),
                "voiceText": "",
                "voiceType": "bad",
            },
        )


def test_save_sprite_voice_type_rejects_invalid_voice_type():
    state = make_state(make_character())

    with pytest.raises(ValueError, match="voice type"):
        _save_sprite_voice_type(state, {"name": "Mika", "spriteIndex": 0, "voiceType": "bad"})


def test_save_sprite_voice_type_rejects_missing_reference_audio():
    state = make_state(make_character(voice_path="missing.wav"))

    with pytest.raises(ValueError, match="does not exist"):
        _save_sprite_voice_type(state, {"name": "Mika", "spriteIndex": 0, "voiceType": "reference"})
