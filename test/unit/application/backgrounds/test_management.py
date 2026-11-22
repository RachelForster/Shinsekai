from pathlib import Path
from types import SimpleNamespace

import pytest

from application.backgrounds import (
    BackgroundExportResult,
    BackgroundOperation,
    BackgroundUseCase,
    parse_background_request,
)
from config.schema import Background


class FakeConfigManager:
    def __init__(self, background):
        self.background = background
        self.events = []

    def get_background_by_name(self, name):
        return self.background if name == self.background.name else None

    def save_background_config(self):
        self.events.append("save-config")

    def reload(self):
        self.events.append("reload")


class FakeBackgroundManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def upload_bgms(self, _name, files):
        self.config_manager.events.append(("upload-bgm", [item.name for item in files]))
        return "uploaded", None, ""

    def delete_background(self, name):
        return f"背景组 {name} 已删除！", []


def make_use_case(tmp_path: Path):
    background = Background(name="Room", sprite_prefix="room", bgm_tags="old")
    config_manager = FakeConfigManager(background)
    state = SimpleNamespace(
        background_manager=FakeBackgroundManager(config_manager),
        config_manager=config_manager,
        project_root_dir=str(tmp_path),
    )
    return BackgroundUseCase(state, file_access_roots=(tmp_path,)), config_manager


def test_upload_bgm_updates_tags_before_file_operation_and_reloads(tmp_path):
    bgm = tmp_path / "room.mp3"
    bgm.write_bytes(b"audio")
    use_case, config_manager = make_use_case(tmp_path)

    result = use_case.execute(
        parse_background_request(
            BackgroundOperation.UPLOAD_BGM,
            {"name": "Room", "paths": [str(bgm)], "bgmTags": "new"},
        )
    )

    assert result["bgm_tags"] == "new"
    assert config_manager.events == [
        "save-config",
        ("upload-bgm", [str(bgm.resolve())]),
        "reload",
    ]


def test_delete_background_preserves_bridge_response_shape(tmp_path):
    use_case, _config_manager = make_use_case(tmp_path)

    result = use_case.execute(
        parse_background_request(BackgroundOperation.DELETE, {"name": "Room"})
    )

    assert result == {"message": "背景组 Room 已删除！", "names": []}


def test_export_returns_transport_neutral_path_result(tmp_path, monkeypatch):
    use_case, _config_manager = make_use_case(tmp_path)
    exported = []
    monkeypatch.setattr(
        "tools.file_util.export_background",
        lambda _backgrounds, output, *, open_folder: exported.append(output),
    )

    result = use_case.execute(
        parse_background_request(BackgroundOperation.EXPORT, {"name": "Room"})
    )

    assert result == BackgroundExportResult(path="output/Room.bg")
    assert exported == [(tmp_path / "output" / "Room.bg").as_posix()]


def test_save_image_and_bgm_tags_persist_without_localized_prefix_parsing(tmp_path):
    use_case, config_manager = make_use_case(tmp_path)

    img_res = use_case.execute(
        parse_background_request(
            BackgroundOperation.SAVE_IMAGE_TAGS,
            {"name": "Room", "bgTags": "场景 1：大厅\n"},
        )
    )
    bgm_res = use_case.execute(
        parse_background_request(
            BackgroundOperation.SAVE_BGM_TAGS,
            {"name": "Room", "bgmTags": "音乐 1：舒缓钢琴\n"},
        )
    )

    assert img_res["bg_tags"] == "场景 1：大厅\n"
    assert bgm_res["bgm_tags"] == "音乐 1：舒缓钢琴\n"
    assert config_manager.events == ["save-config", "reload", "save-config", "reload"]

    with pytest.raises(ValueError, match="background name is required"):
        use_case.execute(
            parse_background_request(
                BackgroundOperation.SAVE_IMAGE_TAGS,
                {"name": "   ", "bgTags": "tag"},
            )
        )
    with pytest.raises(KeyError, match="background not found"):
        use_case.execute(
            parse_background_request(
                BackgroundOperation.SAVE_BGM_TAGS,
                {"name": "Missing", "bgmTags": "tag"},
            )
        )


def test_concurrent_image_and_bgm_tag_saves_preserve_both_fields_in_sqlite_catalog(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from application.runtime.stores import build_app_stores
    from config.models import Background as StoredBackground

    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        bg = StoredBackground(
            name="Room",
            sprite_prefix="room",
            bg_tags="old-bg",
            bgm_tags="old-bgm",
        )
        stores.backgrounds.put(bg.id, bg)

        class StaleReadInterleavingCatalog:
            def __init__(self, inner):
                self._inner = inner
                self.interleaved = False

            def get_by_name(self, name):
                snap = self._inner.get_by_name(name)
                if snap is not None and not self.interleaved:
                    self.interleaved = True
                    # Simulate a concurrent writer updating bgm_tags after this caller read snap.
                    self._inner.patch(
                        snap.id,
                        lambda current: current.model_copy(update={"bgm_tags": "concurrent-bgm"}),
                    )
                return snap

            def __getattr__(self, item):
                return getattr(self._inner, item)

        refresh_calls = []
        interleaved_catalog = StaleReadInterleavingCatalog(stores.backgrounds)
        state = SimpleNamespace(
            stores=SimpleNamespace(backgrounds=interleaved_catalog),
            config_manager=SimpleNamespace(refresh_backgrounds=lambda: refresh_calls.append("refresh")),
            project_root_dir=str(tmp_path),
        )
        use_case = BackgroundUseCase(state, file_access_roots=(tmp_path,))

        # 1) Even when get_by_name returned a stale snapshot before another writer updated bgm_tags,
        # patch() preserves concurrent-bgm instead of overwriting the row.
        use_case.execute(
            parse_background_request(
                BackgroundOperation.SAVE_IMAGE_TAGS,
                {"name": "Room", "bgTags": "updated-bg"},
            )
        )
        after_interleave = stores.backgrounds.get(bg.id)
        assert after_interleave is not None
        assert after_interleave.bg_tags == "updated-bg"
        assert after_interleave.bgm_tags == "concurrent-bgm"

        # 2) Concurrent BackgroundUseCase dispatches preserve both fields end-to-end.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_img = pool.submit(
                use_case.execute,
                parse_background_request(
                    BackgroundOperation.SAVE_IMAGE_TAGS,
                    {"name": "Room", "bgTags": "parallel-bg"},
                ),
            )
            f_bgm = pool.submit(
                use_case.execute,
                parse_background_request(
                    BackgroundOperation.SAVE_BGM_TAGS,
                    {"name": "Room", "bgmTags": "parallel-bgm"},
                ),
            )
            f_img.result()
            f_bgm.result()

        saved = stores.backgrounds.get(bg.id)
        assert saved is not None
        assert saved.bg_tags == "parallel-bg"
        assert saved.bgm_tags == "parallel-bgm"
        assert len(refresh_calls) == 3
    finally:
        stores.close()
