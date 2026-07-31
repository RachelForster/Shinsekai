from types import SimpleNamespace
from pathlib import Path

import pytest

from config.character_manager import CharacterManager, _voice_filename_for_sprite
from config.schema import Character
from core.paths import safe_path_component


class FakeConfigManager:
    def __init__(self, characters):
        self.config = SimpleNamespace(characters=characters)
        self.save_count = 0

    def get_character_by_name(self, name):
        return next((character for character in self.config.characters if character.name == name), None)

    def save_characters_config(self):
        self.save_count += 1


def build_manager(characters, project_root=None):
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = FakeConfigManager(characters)
    manager._project_root = Path(project_root or Path.cwd()).resolve()
    return manager


def sprite_field(sprite, key):
    return getattr(sprite, key, None) if hasattr(sprite, key) else sprite.get(key)


def test_voice_filename_reserves_bytes_for_digest_and_extension():
    filename = _voice_filename_for_sprite(
        {"path": f"{'a' * 250}.png"},
        0,
        ".wav",
    )

    assert filename.startswith("voice_")
    assert filename.endswith(".wav")
    assert len(filename.encode("utf-8")) == 255
    assert safe_path_component(filename) == filename


def test_voice_filename_uses_portable_sprite_path_identity():
    posix_name = _voice_filename_for_sprite(
        {"path": "data/sprite/mika/idle.png"},
        0,
        ".wav",
    )
    windows_name = _voice_filename_for_sprite(
        {"path": r"data\sprite\mika\idle.png"},
        0,
        ".wav",
    )

    assert windows_name == posix_name
    assert windows_name.startswith("voice_idle_")


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


def test_add_character_rejects_whitespace_retargeted_storage_prefix():
    manager = build_manager([])

    message, _names = manager.add_character(
        "Mika",
        "#66ccff",
        " mika ",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
    )

    assert "目录名无效" in message
    assert manager._config_manager.config.characters == []


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


def test_edit_character_cannot_detach_existing_paths_by_changing_storage_prefix(tmp_path):
    asset = tmp_path / "data/sprite/mika/idle.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"image")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
    )
    manager = build_manager([character], tmp_path)

    message, _names = manager.add_character(
        "Mika",
        "#66ccff",
        "renamed",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
        edit_as_name="Mika",
    )

    assert "不可直接修改" in message
    assert character.sprite_prefix == "mika"
    assert sprite_field(character.sprites[0], "path") == "data/sprite/mika/idle.png"
    assert asset.read_bytes() == b"image"
    assert manager._config_manager.save_count == 0


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
    manager = build_manager([character], tmp_path)

    manager.delete_single_sprite("Mika", 0)
    _message, uploaded_path = manager.upload_voice("Mika", 1, str(new_c), "", "preset")

    assert sprite_field(character.sprites[0], "voice_path") == str(old_b)
    assert old_b.read_bytes() == b"old-b"
    assert uploaded_path
    assert sprite_field(character.sprites[1], "voice_path") == uploaded_path
    assert uploaded_path != str(old_b)
    assert "voice_01" not in uploaded_path
    assert (tmp_path / uploaded_path).is_file()
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
    manager = build_manager([character], tmp_path)

    _message, uploaded_path = manager.upload_voice("Mika", 0, str(new_voice), "", "preset")

    assert external_voice.read_bytes() == b"external"
    assert uploaded_path
    assert (tmp_path / uploaded_path).is_file()
    assert sprite_field(character.sprites[0], "voice_path") == uploaded_path
    assert manager._config_manager.save_count == 1


def test_delete_sprite_never_unlinks_external_config_path(tmp_path):
    external_sprite = tmp_path / "external.png"
    external_voice = tmp_path / "external.wav"
    external_sprite.write_bytes(b"image")
    external_voice.write_bytes(b"voice")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[
            {
                "path": external_sprite.as_posix(),
                "voice_path": external_voice.as_posix(),
            }
        ],
    )
    manager = build_manager([character], tmp_path / "project")

    manager.delete_single_sprite("Mika", 0)

    assert external_sprite.read_bytes() == b"image"
    assert external_voice.read_bytes() == b"voice"
    assert character.sprites == []


def test_delete_character_rejects_traversal_prefix_and_keeps_external_directory(tmp_path):
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="../../outside",
    )
    manager = build_manager([character], project_root)

    manager.delete_character("Mika")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert manager._config_manager.config.characters == []


def test_upload_sprites_never_overwrites_same_named_managed_file(tmp_path):
    project = tmp_path / "project"
    existing = project / "data/sprite/mika/idle.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    source = tmp_path / "incoming/idle.png"
    source.parent.mkdir()
    source.write_bytes(b"new")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
    )
    manager = build_manager([character], project)

    _message, paths, _tags = manager.upload_sprites(
        "Mika",
        [SimpleNamespace(name=source.as_posix())],
        "",
    )

    assert existing.read_bytes() == b"old"
    assert paths == [
        "data/sprite/mika/idle.png",
        "data/sprite/mika/idle_1.png",
    ]
    assert (project / paths[1]).read_bytes() == b"new"


def test_upload_sprites_resolves_relative_source_from_project_not_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    source = project / "data/incoming/idle.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"project image")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    character = Character(name="Mika", color="#66ccff", sprite_prefix="mika")
    manager = build_manager([character], project)

    _message, paths, _tags = manager.upload_sprites(
        "Mika",
        [SimpleNamespace(name="data/incoming/idle.png")],
        "",
    )

    assert paths == ["data/sprite/mika/idle.png"]
    assert (project / paths[0]).read_bytes() == b"project image"
    assert not (unrelated / "data/sprite/mika/idle.png").exists()


def test_upload_sprites_rejects_linked_source_directory(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "incoming"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    (external / "idle.png").write_bytes(b"external image")
    try:
        (project / "data/incoming").symlink_to(
            external,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    character = Character(name="Mika", color="#66ccff", sprite_prefix="mika")
    manager = build_manager([character], project)

    with pytest.raises(PermissionError, match="symbolic link"):
        manager.upload_sprites(
            "Mika",
            [SimpleNamespace(name="data/incoming/idle.png")],
            "",
        )

    assert character.sprites == []
    assert not (project / "data/sprite/mika").exists()


def test_upload_voice_resolves_relative_source_from_project_not_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    source = project / "data/incoming/line.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"voice")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
    )
    manager = build_manager([character], project)

    _message, stored = manager.upload_voice(
        "Mika",
        0,
        "data/incoming/line.wav",
        "",
        "preset",
    )

    assert stored is not None
    assert stored.startswith("data/speech/mika/")
    assert (project / stored).read_bytes() == b"voice"
    assert not (unrelated / "data/speech/mika").exists()


def test_upload_voice_rejects_linked_source_directory(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "incoming"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    (external / "line.wav").write_bytes(b"external voice")
    try:
        (project / "data/incoming").symlink_to(
            external,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
    )
    manager = build_manager([character], project)

    with pytest.raises(PermissionError, match="symbolic link"):
        manager.upload_voice(
            "Mika",
            0,
            "data/incoming/line.wav",
            "",
            "preset",
        )

    assert not (project / "data/speech/mika").exists()
    assert sprite_field(character.sprites[0], "voice_path") in {None, ""}


def test_upload_sprites_save_failure_rolls_back_memory_and_new_files(tmp_path):
    project = tmp_path / "project"
    source = tmp_path / "incoming/idle.png"
    source.parent.mkdir()
    source.write_bytes(b"new")
    character = Character(name="Mika", color="#66ccff", sprite_prefix="mika")
    manager = build_manager([character], project)
    manager._config_manager.save_characters_config = lambda: (_ for _ in ()).throw(
        OSError("disk full")
    )

    with pytest.raises(OSError, match="disk full"):
        manager.upload_sprites(
            "Mika",
            [SimpleNamespace(name=source.as_posix())],
            "",
        )

    assert character.sprites == []
    assert character.emotion_tags == ""
    assert not (project / "data/sprite/mika").exists()


def test_delete_sprite_save_failure_keeps_reference_and_file(tmp_path):
    project = tmp_path / "project"
    sprite = project / "data/sprite/mika/idle.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"image")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
        emotion_tags="立绘 1：idle\n",
    )
    manager = build_manager([character], project)
    manager._config_manager.save_characters_config = lambda: (_ for _ in ()).throw(
        OSError("read only")
    )

    with pytest.raises(OSError, match="read only"):
        manager.delete_single_sprite("Mika", 0)

    assert sprite.read_bytes() == b"image"
    assert sprite_field(character.sprites[0], "path") == "data/sprite/mika/idle.png"
    assert character.emotion_tags == "立绘 1：idle\n"


def test_delete_sprite_preserves_file_replaced_during_config_save(tmp_path):
    project = tmp_path / "project"
    sprite = project / "data/sprite/mika/idle.png"
    preserved = project / "data/sprite/mika/original-idle.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"original")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        sprites=[{"path": "data/sprite/mika/idle.png"}],
    )
    manager = build_manager([character], project)

    def replace_during_save():
        sprite.rename(preserved)
        sprite.write_bytes(b"peer")

    manager._config_manager.save_characters_config = replace_during_save

    manager.delete_single_sprite("Mika", 0)

    assert sprite.read_bytes() == b"peer"
    assert preserved.read_bytes() == b"original"
    assert character.sprites == []


def test_delete_character_preserves_directory_replaced_during_config_save(
    tmp_path,
):
    project = tmp_path / "project"
    sprite_dir = project / "data/sprite/mika"
    preserved = project / "data/sprite/preserved-mika"
    sprite_dir.mkdir(parents=True)
    (sprite_dir / "idle.png").write_bytes(b"original")
    character = Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
    )
    manager = build_manager([character], project)

    def replace_during_save():
        sprite_dir.rename(preserved)
        sprite_dir.mkdir()
        (sprite_dir / "peer.png").write_bytes(b"peer")

    manager._config_manager.save_characters_config = replace_during_save

    manager.delete_character("Mika")

    assert (sprite_dir / "peer.png").read_bytes() == b"peer"
    assert (preserved / "idle.png").read_bytes() == b"original"
    assert manager._config_manager.config.characters == []


def test_delete_sprite_keeps_file_still_referenced_by_legacy_character(tmp_path):
    project = tmp_path / "project"
    sprite = project / "data/sprite/shared/idle.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"image")
    first = Character(
        name="First",
        color="#fff",
        sprite_prefix="shared",
        sprites=[{"path": "data/sprite/shared/idle.png"}],
    )
    second = Character(
        name="Second",
        color="#000",
        sprite_prefix="shared",
        sprites=[{"path": "data/sprite/shared/idle.png"}],
    )
    manager = build_manager([first, second], project)

    manager.delete_single_sprite("First", 0)

    assert sprite.read_bytes() == b"image"
    assert first.sprites == []
    assert sprite_field(second.sprites[0], "path") == "data/sprite/shared/idle.png"


def test_character_prefix_collision_is_portably_case_insensitive():
    existing = Character(name="Mika", color="#fff", sprite_prefix="Mika")
    manager = build_manager([existing])

    message, _names = manager.add_character(
        "Other", "#000", "mika", "", "", "", "", "", ""
    )

    assert "已被角色" in message
