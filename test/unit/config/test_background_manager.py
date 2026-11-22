from types import SimpleNamespace

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


def build_manager(backgrounds):
    manager = BackgroundManager.__new__(BackgroundManager)
    manager._config_manager = FakeConfigManager(backgrounds)
    return manager


def test_upload_mixed_image_and_mp4_backgrounds_preserves_bytes_and_tag_order(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("config.background_manager.BACKGROUND_UPLOAD_DIR", str(tmp_path / "uploaded"))
    sources = []
    for name in ("day.png", "rain.mp4", "night.gif"):
        source = tmp_path / name
        source.write_bytes(name.encode())
        sources.append(SimpleNamespace(name=str(source)))
    background = Background(name="School", sprite_prefix="school")
    manager = build_manager([background])

    _message, paths, tags = manager.upload_sprites("School", sources, "")

    assert [Path(path).name for path in paths] == ["day.png", "rain.mp4", "night.gif"]
    assert [Path(path).read_bytes() for path in paths] == [b"day.png", b"rain.mp4", b"night.gif"]
    assert tags == "场景 1：\n场景 2：\n场景 3：\n"
    assert background.model_dump(mode="json")["sprites"][1]["path"] == paths[1]
    assert manager._config_manager.save_count == 1


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


def test_background_creation_allocates_unique_prefixes_and_protects_shared_legacy_dirs(tmp_path):
    from config.schema import Sprite

    manager = build_manager([])
    first, _, _ = manager.save_background_patch({"name": "樱花教室", "sprite_prefix": "temp"})
    second, _, _ = manager.save_background_patch({"name": "深夜卧室", "sprite_prefix": "temp"})
    assert first.sprite_prefix == "temp"
    assert second.sprite_prefix == "bg_1"

    import pytest
    from config.background_ops import BackgroundProfileError

    with pytest.raises(BackgroundProfileError):
        manager.save_background_patch(
            {"id": second.id, "name": "深夜卧室", "sprite_prefix": "temp"},
            target_id=second.id,
        )

    upload_root = tmp_path / "backgrounds"
    bgm_root = tmp_path / "bgm"
    shared_img_dir = upload_root / "legacy_shared"
    shared_img_dir.mkdir(parents=True)
    img_a = shared_img_dir / "a.png"
    img_b = shared_img_dir / "b.png"
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"b")

    legacy_a = Background(name="旧背景A", sprite_prefix="legacy_shared", sprites=[Sprite(path=str(img_a))])
    legacy_b = Background(name="旧背景B", sprite_prefix="legacy_shared", sprites=[Sprite(path=str(img_b))])
    legacy_mgr = build_manager([legacy_a, legacy_b])

    from config.background_ops import ConfigManagerBackgroundTarget, delete_background_and_assets

    delete_background_and_assets(
        ConfigManagerBackgroundTarget(legacy_mgr._config_manager),
        "旧背景A",
        upload_dir=upload_root,
        bgm_dir=bgm_root,
    )
    assert not img_a.exists()
    assert img_b.exists()
