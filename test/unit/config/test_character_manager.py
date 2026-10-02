from types import SimpleNamespace

import pytest

from config.character_manager import CharacterManager
from config.schema import Character, ModelSprites


class FakeConfigManager:
    def __init__(self, characters):
        self.config = SimpleNamespace(characters=characters)
        self.save_count = 0

    def get_character_by_name(self, name):
        return next((character for character in self.config.characters if character.name == name), None)

    def save_characters_config(self):
        self.save_count += 1


def build_manager(characters):
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = FakeConfigManager(characters)
    return manager


def sprite_field(sprite, key):
    return getattr(sprite, key, None) if hasattr(sprite, key) else sprite.get(key)


@pytest.mark.parametrize("prefix", ["", ".", "../outside"])
def test_delete_all_sprites_rejects_shared_or_escaping_root(tmp_path, monkeypatch, prefix):
    sprite_root = tmp_path / "sprite"
    sprite_root.mkdir()
    sentinel = sprite_root / "other-character.png"
    sentinel.touch()
    monkeypatch.setattr("config.character_manager.UPLOAD_DIR", str(sprite_root))
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(tmp_path / "speech"))
    character = Character(name="Mika", color="#fff", sprite_prefix=prefix)
    manager = build_manager([character])
    with pytest.raises((ValueError, PermissionError)):
        manager.delete_all_sprites("Mika")
    assert sentinel.is_file()
    assert manager._config_manager.save_count == 0


@pytest.mark.parametrize("operation", ["create", "update", "rename", "update_by_name"])
def test_add_character_persists_avatar_banks(operation):
    character = Character(
        name="Mika", color="#66ccff", sprite_prefix="old",
        avatar_type="vrm", avatars={"vrm": {"model_path": "old.vrm"}},
    )
    manager = build_manager([] if operation == "create" else [character])
    name = "Renamed" if operation == "rename" else "Mika"
    edit_as_name = "Mika" if operation in {"update", "rename"} else None
    assets = ModelSprites(
        model_path="new.model3.json",
        sprites=[{"path": "happy.motion3.json", "voice_type": "preset"}],
        emotion_tags="1: happy",
    )

    manager.add_character(
        name, "#ffffff", "new", "", "", "", "", "", "Updated setting",
        edit_as_name=edit_as_name, avatar_type=" L2D ", avatars={" L2D ": assets},
    )

    saved = manager._config_manager.get_character_by_name(name)
    assert saved.avatar_type == "l2d"
    assert saved.avatars == {"l2d": assets}
    assert saved.model_dump(mode="json")["avatars"]["l2d"]["sprites"][0]["voice_type"] == "preset"
    assert manager._config_manager.save_count == 1


@pytest.mark.parametrize("edit_as_name", [None, "Mika"])
def test_legacy_update_preserves_avatar_banks(edit_as_name):
    character = Character(
        name="Mika", color="#66ccff", sprite_prefix="old",
        avatar_type="vrm", avatars={"vrm": {"model_path": "existing.vrm"}},
    )
    original = character.model_dump(mode="json")
    manager = build_manager([character])
    manager.add_character(
        "Mika", "#ffffff", "new", "", "", "", "", "", "Updated setting",
        edit_as_name=edit_as_name,
    )
    assert character.avatar_type == original["avatar_type"]
    assert character.model_dump(mode="json")["avatars"] == original["avatars"]


def test_avatar_banks_can_be_explicitly_cleared():
    character = Character(
        name="Mika", color="#66ccff", sprite_prefix="old",
        avatar_type="vrm", avatars={"vrm": {"model_path": "existing.vrm"}},
    )
    manager = build_manager([character])
    manager.add_character(
        "Mika", "#ffffff", "new", "", "", "", "", "", "Updated setting",
        edit_as_name="Mika", avatar_type="static", avatars={},
    )
    assert character.avatar_type == "static"
    assert character.avatars == {}


def test_invalid_avatar_banks_do_not_mutate_existing_character():
    character = Character(name="Mika", color="#66ccff", sprite_prefix="old")
    original = character.model_dump(mode="json")
    manager = build_manager([character])
    with pytest.raises(ValueError, match="invalid or duplicate avatar format"):
        manager.add_character(
            "Mika", "#ffffff", "new", "", "", "", "", "", "Updated setting",
            edit_as_name="Mika", avatar_type="l2d", avatars={"static": {}},
        )
    assert character.model_dump(mode="json") == original
    assert manager._config_manager.save_count == 0


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


def test_legacy_character_update_preserves_existing_brief():
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        character_brief="Existing brief",
    )
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
        "Updated full setting.",
        edit_as_name="Mika",
    )

    assert character.character_brief == "Existing brief"


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
