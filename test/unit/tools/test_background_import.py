import zipfile
from pathlib import Path

import pytest
import yaml

from config.schema import Background
from tools import file_util


def _mock_background_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    background_dir = data_dir / "backgrounds"
    bgm_dir = data_dir / "bgm"
    background_dir.mkdir(parents=True)
    bgm_dir.mkdir(parents=True)
    monkeypatch.setattr(file_util, "BACKGROUND_UPLOAD_DIR", background_dir)
    monkeypatch.setattr(file_util, "BGM_UPLOAD_DIR", bgm_dir)
    monkeypatch.setattr(file_util.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    return background_dir, bgm_dir


def _sprite_path(sprite) -> str:
    return str(sprite.path) if hasattr(sprite, "path") else sprite["path"]


def test_export_background_writes_package_filenames(tmp_path, monkeypatch):
    background_dir, bgm_dir = _mock_background_dirs(tmp_path, monkeypatch)
    prefix = "scene"
    sprite_dir = background_dir / prefix
    sound_dir = bgm_dir / prefix
    sprite_dir.mkdir()
    sound_dir.mkdir()
    (sprite_dir / "room.png").write_text("png", encoding="utf-8")
    (sound_dir / "theme.mp3").write_text("mp3", encoding="utf-8")

    background = Background(
        name="Room",
        sprite_prefix=prefix,
        sprites=[{"path": str((sprite_dir / "room.png").resolve())}],
        bgm_list=[str((sound_dir / "theme.mp3").resolve())],
    )
    output = tmp_path / "room.bg"

    file_util.export_background([background], str(output))

    with zipfile.ZipFile(output, "r") as zf:
        data = yaml.safe_load(zf.read("background.yaml"))
    assert data[0]["sprites"][0]["path"] == "room.png"
    assert data[0]["bgm_list"] == ["theme.mp3"]


def test_import_background_accepts_legacy_absolute_yaml_paths(tmp_path, monkeypatch):
    background_dir, bgm_dir = _mock_background_dirs(tmp_path, monkeypatch)
    prefix = "legacy"
    package = tmp_path / "legacy.bg"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "background.yaml",
            yaml.dump(
                [
                    {
                        "name": "Legacy",
                        "sprite_prefix": prefix,
                        "sprites": [{"path": "/home/user/legacy.png"}],
                        "bgm_list": ["C:\\Users\\user\\legacy.mp3"],
                    }
                ],
                allow_unicode=True,
            ),
        )
        zf.writestr(f"sprites/{prefix}/legacy.png", "png")
        zf.writestr(f"bgm/{prefix}/legacy.mp3", "mp3")

    result = file_util.import_background(str(package), [])

    assert _sprite_path(result[0].sprites[0]) == (background_dir / prefix / "legacy.png").as_posix()
    assert result[0].bgm_list == [(bgm_dir / prefix / "legacy.mp3").as_posix()]
    assert (background_dir / prefix / "legacy.png").is_file()
    assert (bgm_dir / prefix / "legacy.mp3").is_file()


def test_import_background_rejects_unsafe_paths(tmp_path, monkeypatch):
    _mock_background_dirs(tmp_path, monkeypatch)
    for filename, path in {
        "bad-parent.bg": "../evil.png",
        "bad-nul.bg": "evil\0.png",
    }.items():
        package = tmp_path / filename
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "background.yaml",
                yaml.dump(
                    [
                        {
                            "name": "Bad",
                            "sprite_prefix": "bad",
                            "sprites": [{"path": path}],
                        }
                    ],
                    allow_unicode=True,
                ),
            )

        with pytest.raises(ValueError):
            file_util.import_background(str(package), [])


def test_import_background_rejects_unsafe_zip_members(tmp_path, monkeypatch):
    _mock_background_dirs(tmp_path, monkeypatch)
    package = tmp_path / "bad-zip.bg"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../evil.txt", "bad")

    with pytest.raises(ValueError):
        file_util.import_background(str(package), [])
