from pathlib import Path
from types import SimpleNamespace

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
