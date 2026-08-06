from types import SimpleNamespace
from pathlib import Path
import zipfile

import pytest
import yaml

from config.background_manager import BackgroundManager
from config.schema import Background


class FakeConfigManager:
    def __init__(self, backgrounds):
        self.config = SimpleNamespace(background_list=backgrounds)
        self.save_count = 0

    def get_background_by_name(self, name):
        return next((background for background in self.config.background_list if background.name == name), None)

    def save_background_config(self):
        self.save_count += 1


def build_manager(backgrounds, project_root=None):
    manager = BackgroundManager.__new__(BackgroundManager)
    manager._config_manager = FakeConfigManager(backgrounds)
    manager._project_root = Path(project_root or Path.cwd()).resolve()
    return manager


def test_add_background_updates_existing_tags():
    background = Background(name="School", sprite_prefix="school", bg_tags="Scene 1: old\n", bgm_tags="Music 1: old\n")
    manager = build_manager([background])

    manager.add_background(
        "School",
        "school",
        edit_as_name="School",
        bg_tags="Scene 1: classroom\n",
        bgm_tags="Music 1: calm\n",
    )

    assert background.bg_tags == "Scene 1: classroom\n"
    assert background.bgm_tags == "Music 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_background_creates_when_edit_target_is_missing():
    manager = build_manager([])

    manager.add_background(
        "City",
        "city",
        edit_as_name="Missing",
        bg_tags="Scene 1: street\n",
        bgm_tags="Music 1: traffic\n",
    )

    assert len(manager._config_manager.config.background_list) == 1
    assert manager._config_manager.config.background_list[0].name == "City"
    assert manager._config_manager.config.background_list[0].bg_tags == "Scene 1: street\n"
    assert manager._config_manager.config.background_list[0].bgm_tags == "Music 1: traffic\n"
    assert manager._config_manager.save_count == 1


def test_add_background_rejects_whitespace_retargeted_storage_prefix():
    manager = build_manager([])

    message, _names = manager.add_background("City", " city ")

    assert "目录名无效" in message
    assert manager._config_manager.config.background_list == []


def test_add_background_rejects_shared_storage_prefix():
    existing = Background(name="School", sprite_prefix="shared")
    manager = build_manager([existing])

    message, _names = manager.add_background("City", "shared")

    assert "已被背景组" in message
    assert manager._config_manager.config.background_list == [existing]


def test_edit_background_cannot_detach_existing_paths_by_changing_storage_prefix(tmp_path):
    asset = tmp_path / "data/backgrounds/school/room.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"image")
    background = Background(
        name="School",
        sprite_prefix="school",
        sprites=[{"path": "data/backgrounds/school/room.png"}],
    )
    manager = build_manager([background], tmp_path)

    message, _names = manager.add_background(
        "School",
        "renamed",
        edit_as_name="School",
    )

    assert "不可直接修改" in message
    assert background.sprite_prefix == "school"
    sprite = background.sprites[0]
    assert (sprite.path if hasattr(sprite, "path") else sprite.get("path")) == (
        "data/backgrounds/school/room.png"
    )
    assert asset.read_bytes() == b"image"
    assert manager._config_manager.save_count == 0


def test_delete_background_sprite_never_unlinks_external_config_path(tmp_path):
    external = tmp_path / "external.png"
    external.write_bytes(b"image")
    background = Background(
        name="School",
        sprite_prefix="school",
        sprites=[{"path": external.as_posix()}],
    )
    manager = build_manager([background], tmp_path / "project")

    manager.delete_single_sprite("School", 0)

    assert external.read_bytes() == b"image"
    assert background.sprites == []


def test_delete_background_rejects_traversal_prefix(tmp_path):
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    background = Background(name="School", sprite_prefix="../../outside")
    manager = build_manager([background], project_root)

    manager.delete_background("School")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert manager._config_manager.config.background_list == []


def test_import_background_save_failure_restores_memory_and_files(tmp_path):
    project = tmp_path / "project"
    package = tmp_path / "scene.bg"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "background.yaml",
            yaml.safe_dump(
                [{"name": "Scene", "sprite_prefix": "scene", "sprites": [{"path": "room.png"}]}],
                allow_unicode=True,
            ),
        )
        archive.writestr("sprites/scene/room.png", b"image")
    original = Background(name="Existing", sprite_prefix="existing")
    manager = build_manager([original], project)

    def fail_save():
        raise OSError("disk full")

    manager._config_manager.save_background_config = fail_save

    message, names = manager.import_background_file(package.as_posix())

    assert "disk full" in message
    assert names == ["Existing"]
    assert manager._config_manager.config.background_list == [original]
    assert not (project / "data/backgrounds/scene").exists()


def test_upload_background_never_overwrites_same_named_managed_file(tmp_path):
    project = tmp_path / "project"
    existing = project / "data/backgrounds/school/room.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    source = tmp_path / "incoming/room.png"
    source.parent.mkdir()
    source.write_bytes(b"new")
    background = Background(
        name="School",
        sprite_prefix="school",
        sprites=[{"path": "data/backgrounds/school/room.png"}],
    )
    manager = build_manager([background], project)

    _message, paths, _tags = manager.upload_sprites(
        "School",
        [SimpleNamespace(name=source.as_posix())],
        "",
    )

    assert existing.read_bytes() == b"old"
    assert paths == [
        "data/backgrounds/school/room.png",
        "data/backgrounds/school/room_1.png",
    ]
    assert (project / paths[1]).read_bytes() == b"new"


def test_background_uploads_resolve_relative_sources_from_project_not_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    image = project / "data/incoming/room.png"
    audio = project / "data/incoming/theme.ogg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"project image")
    audio.write_bytes(b"project audio")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    background = Background(name="School", sprite_prefix="school")
    manager = build_manager([background], project)

    _message, paths, _tags = manager.upload_sprites(
        "School",
        [SimpleNamespace(name="data/incoming/room.png")],
        "",
    )
    manager.upload_bgms(
        "School",
        [SimpleNamespace(name="data/incoming/theme.ogg")],
        "",
    )

    assert paths == ["data/backgrounds/school/room.png"]
    assert (project / paths[0]).read_bytes() == b"project image"
    assert background.bgm_list == ["data/bgm/school/theme.ogg"]
    assert (project / background.bgm_list[0]).read_bytes() == b"project audio"
    assert not (unrelated / "data/backgrounds/school").exists()
    assert not (unrelated / "data/bgm/school").exists()


@pytest.mark.parametrize("media_kind", ("sprite", "bgm"))
def test_background_uploads_reject_linked_source_directories(
    tmp_path,
    media_kind,
):
    project = tmp_path / "project"
    external = tmp_path / "incoming"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    filename = "room.png" if media_kind == "sprite" else "theme.ogg"
    (external / filename).write_bytes(b"external media")
    try:
        (project / "data/incoming").symlink_to(
            external,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    background = Background(name="School", sprite_prefix="school")
    manager = build_manager([background], project)

    with pytest.raises(PermissionError, match="symbolic link"):
        if media_kind == "sprite":
            manager.upload_sprites(
                "School",
                [SimpleNamespace(name=f"data/incoming/{filename}")],
                "",
            )
        else:
            manager.upload_bgms(
                "School",
                [SimpleNamespace(name=f"data/incoming/{filename}")],
                "",
            )

    assert background.sprites == []
    assert background.bgm_list == []
    assert not (project / "data/backgrounds/school").exists()
    assert not (project / "data/bgm/school").exists()


def test_upload_background_save_failure_rolls_back_memory_and_new_files(tmp_path):
    project = tmp_path / "project"
    source = tmp_path / "incoming/room.png"
    source.parent.mkdir()
    source.write_bytes(b"new")
    background = Background(name="School", sprite_prefix="school")
    manager = build_manager([background], project)
    manager._config_manager.save_background_config = lambda: (_ for _ in ()).throw(
        OSError("disk full")
    )

    with pytest.raises(OSError, match="disk full"):
        manager.upload_sprites(
            "School",
            [SimpleNamespace(name=source.as_posix())],
            "",
        )

    assert background.sprites == []
    assert background.bg_tags == ""
    assert not (project / "data/backgrounds/school").exists()


def test_delete_background_sprite_save_failure_keeps_reference_and_file(tmp_path):
    project = tmp_path / "project"
    sprite = project / "data/backgrounds/school/room.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"image")
    background = Background(
        name="School",
        sprite_prefix="school",
        sprites=[{"path": "data/backgrounds/school/room.png"}],
        bg_tags="场景 1：room\n",
    )
    manager = build_manager([background], project)
    manager._config_manager.save_background_config = lambda: (_ for _ in ()).throw(
        OSError("read only")
    )

    with pytest.raises(OSError, match="read only"):
        manager.delete_single_sprite("School", 0)

    assert sprite.read_bytes() == b"image"
    stored = background.sprites[0]
    assert (stored.path if hasattr(stored, "path") else stored.get("path")) == (
        "data/backgrounds/school/room.png"
    )
    assert background.bg_tags == "场景 1：room\n"


def test_delete_background_sprite_preserves_replacement_created_during_save(
    tmp_path,
):
    project = tmp_path / "project"
    sprite = project / "data/backgrounds/school/room.png"
    preserved = project / "data/backgrounds/school/original-room.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"original")
    background = Background(
        name="School",
        sprite_prefix="school",
        sprites=[{"path": "data/backgrounds/school/room.png"}],
    )
    manager = build_manager([background], project)

    def replace_during_save():
        sprite.rename(preserved)
        sprite.write_bytes(b"peer")

    manager._config_manager.save_background_config = replace_during_save

    manager.delete_single_sprite("School", 0)

    assert sprite.read_bytes() == b"peer"
    assert preserved.read_bytes() == b"original"
    assert background.sprites == []


def test_background_prefix_collision_is_portably_case_insensitive():
    existing = Background(name="School", sprite_prefix="Scene")
    manager = build_manager([existing])

    message, _names = manager.add_background("City", "scene")

    assert "已被背景组" in message
