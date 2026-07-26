from pathlib import Path
from types import SimpleNamespace

from config.character_manager import CharacterManager
from config.schema import Character


class FakeConfigManager:
    def __init__(self, characters, save_result=True):
        self.config = SimpleNamespace(characters=characters)
        self.save_count = 0
        self._save_result = save_result

    def get_character_by_name(self, name):
        return next((character for character in self.config.characters if character.name == name), None)

    def save_characters_config(self):
        self.save_count += 1
        return self._save_result


def build_manager(characters, save_result=True):
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = FakeConfigManager(characters, save_result=save_result)
    return manager


def sprite_field(sprite, key):
    return getattr(sprite, key, None) if hasattr(sprite, key) else sprite.get(key)


def test_add_character_updates_existing_emotion_tags():
    character = Character(name="Mika", color="#66ccff", sprite_prefix="mika", emotion_tags="Sprite 1: old\n")
    manager = build_manager([character])

    manager.add_character(
        "Mika",
        "#66ccff",
        "mika",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
        edit_as_name="Mika",
        emotion_tags="Sprite 1: calm\n",
    )

    assert character.emotion_tags == "Sprite 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_character_applies_emotion_tags_to_new_character():
    manager = build_manager([])

    manager.add_character(
        "Mika",
        "#66ccff",
        "mika",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
        emotion_tags="Sprite 1: calm\n",
    )

    assert manager._config_manager.config.characters[0].emotion_tags == "Sprite 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_character_creates_when_edit_target_is_missing():
    manager = build_manager([])

    manager.add_character(
        "Sora",
        "#ff99aa",
        "sora",
        "",
        "",
        "",
        "",
        "",
        "New character.",
        edit_as_name="Missing",
        emotion_tags="Sprite 1: smile\n",
    )

    assert len(manager._config_manager.config.characters) == 1
    assert manager._config_manager.config.characters[0].name == "Sora"
    assert manager._config_manager.config.characters[0].emotion_tags == "Sprite 1: smile\n"
    assert manager._config_manager.save_count == 1


def test_upload_voice_after_sprite_delete_does_not_overwrite_shifted_sprite_voice(tmp_path, monkeypatch):
    voice_dir = tmp_path / "speech"
    char_voice_dir = voice_dir / "mika"
    char_voice_dir.mkdir(parents=True)
    old_a = char_voice_dir / "voice_00.wav"
    old_b = char_voice_dir / "voice_01.wav"
    old_c = char_voice_dir / "voice_02.wav"
    old_a.write_bytes(b"old-a")
    old_b.write_bytes(b"old-b")
    old_c.write_bytes(b"old-c")
    new_c = tmp_path / "new-c.wav"
    new_c.write_bytes(b"new-c")
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(voice_dir))
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[
            {"path": "data/sprite/mika/sprite-a.png", "voice_path": str(old_a)},
            {"path": "data/sprite/mika/sprite-b.png", "voice_path": str(old_b), "voice_type": "preset"},
            {"path": "data/sprite/mika/sprite-c.png", "voice_path": str(old_c), "voice_type": "preset"},
        ],
    )
    manager = build_manager([character])

    manager.delete_single_sprite("Mika", 0)
    _message, uploaded_path = manager.upload_voice("Mika", 1, str(new_c), "", "preset")

    assert sprite_field(character.sprites[0], "voice_path") == str(old_b)
    assert old_b.read_bytes() == b"old-b"
    assert uploaded_path
    assert sprite_field(character.sprites[1], "voice_path") == uploaded_path
    assert uploaded_path != str(old_b)
    assert "voice_01" not in uploaded_path
    assert old_c.exists() is False
    assert old_a.exists() is False
    assert manager._config_manager.save_count == 2


def test_upload_voice_does_not_delete_original_voice_outside_character_voice_dir(tmp_path, monkeypatch):
    voice_dir = tmp_path / "speech"
    voice_dir.mkdir()
    external_voice = tmp_path / "external.wav"
    external_voice.write_bytes(b"external")
    new_voice = tmp_path / "new.wav"
    new_voice.write_bytes(b"new")
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(voice_dir))
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[
            {
                "path": "data/sprite/mika/sprite-a.png",
                "voice_path": str(external_voice),
                "voice_type": "preset",
            },
        ],
    )
    manager = build_manager([character])

    _message, uploaded_path = manager.upload_voice("Mika", 0, str(new_voice), "", "preset")

    assert external_voice.read_bytes() == b"external"
    assert uploaded_path
    assert uploaded_path.startswith(str(voice_dir / "mika"))
    assert sprite_field(character.sprites[0], "voice_path") == uploaded_path
    assert manager._config_manager.save_count == 1


def _mika_with_sprite(voice_dir):
    return Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/sprite-a.png"}],
    )


def test_upload_voice_uses_distinct_paths_for_different_audio_bytes(tmp_path, monkeypatch):
    voice_dir = tmp_path / "speech"
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(voice_dir))
    manager = build_manager([_mika_with_sprite(voice_dir)])
    first = tmp_path / "first.wav"
    first.write_bytes(b"first-audio-bytes")
    second = tmp_path / "second.wav"
    second.write_bytes(b"second-audio-bytes")

    _m1, path_a = manager.upload_voice("Mika", 0, str(first), "hi", "reference")
    _m2, path_b = manager.upload_voice("Mika", 0, str(second), "hi", "reference")

    # Different audio content must land on different files (GPT-SoVITS caches
    # reference features by path, so a shared path would keep the first voice).
    assert path_a and path_b and path_a != path_b
    assert Path(path_a).exists() is False  # replaced file removed after save
    assert Path(path_b).exists() is True


def test_upload_voice_reuses_path_for_identical_audio_bytes(tmp_path, monkeypatch):
    voice_dir = tmp_path / "speech"
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(voice_dir))
    manager = build_manager([_mika_with_sprite(voice_dir)])
    first = tmp_path / "first.wav"
    first.write_bytes(b"same-audio-bytes")
    second = tmp_path / "second.wav"
    second.write_bytes(b"same-audio-bytes")

    _m1, path_a = manager.upload_voice("Mika", 0, str(first), "hi", "reference")
    _m2, path_b = manager.upload_voice("Mika", 0, str(second), "hi", "reference")

    assert path_a == path_b
    assert Path(path_b).exists() is True


def test_upload_voice_keeps_previous_voice_when_save_fails(tmp_path, monkeypatch):
    voice_dir = tmp_path / "speech"
    char_voice_dir = voice_dir / "mika"
    char_voice_dir.mkdir(parents=True)
    old_voice = char_voice_dir / "voice_old.wav"
    old_voice.write_bytes(b"old-voice")
    new_voice = tmp_path / "new.wav"
    new_voice.write_bytes(b"new-voice-bytes")
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(voice_dir))
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[
            {
                "path": "data/sprite/mika/sprite-a.png",
                "voice_path": str(old_voice),
                "voice_text": "original",
                "voice_type": "reference",
            },
        ],
    )
    manager = build_manager([character], save_result=False)

    message, uploaded_path = manager.upload_voice("Mika", 0, str(new_voice), "changed", "reference")

    # Failed persistence must not strand files or the config pointer.
    assert uploaded_path is None
    assert "失败" in message
    assert old_voice.exists() is True
    assert old_voice.read_bytes() == b"old-voice"
    assert sprite_field(character.sprites[0], "voice_path") == str(old_voice)
    assert sprite_field(character.sprites[0], "voice_text") == "original"
    # The just-copied new file must be cleaned up (no orphan).
    assert sorted(p.name for p in char_voice_dir.iterdir()) == ["voice_old.wav"]
