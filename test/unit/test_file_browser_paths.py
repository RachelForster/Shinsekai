import os
from types import SimpleNamespace

from frontend_bridge_core.tools import (
    _browse_local_files,
    _display_path,
    _file_browser_root_key,
    _file_browser_root_label,
    _strip_windows_verbatim_prefix,
)


def test_strip_windows_verbatim_drive_prefix():
    assert _strip_windows_verbatim_prefix("\\\\?\\D:\\") == "D:\\"
    assert _strip_windows_verbatim_prefix("//?/D:/Games") == "D:/Games"


def test_strip_windows_verbatim_unc_prefix():
    assert _strip_windows_verbatim_prefix(r"\\?\UNC\server\share\asset.png") == r"\\server\share\asset.png"
    assert _strip_windows_verbatim_prefix("//?/UNC/server/share/asset.png") == "//server/share/asset.png"


def test_windows_drive_root_keys_collapse_verbatim_and_normal_paths():
    assert _file_browser_root_key("\\\\?\\D:\\") == _file_browser_root_key("D:/")
    assert _file_browser_root_key("//?/D:/") == _file_browser_root_key("D:/")


def test_windows_drive_root_labels_drop_verbatim_prefixes():
    assert _file_browser_root_label("\\\\?\\D:\\", "D:/") == "D:"
    assert _file_browser_root_label("//?/D:/", "D:/") == "D:"


def test_file_browser_uses_app_root_for_shinsekai_location(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    data_root = project_root / "data"
    downloads_root = tmp_path / "home" / "Downloads"
    app_root.mkdir()
    downloads_root.mkdir(parents=True)
    (app_root / "Shinsekai.exe").write_text("", encoding="utf-8")

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("HOME", str(downloads_root.parent))
    monkeypatch.setenv("USERPROFILE", str(downloads_root.parent))
    snapshot = _browse_local_files(SimpleNamespace(app_root_dir=str(app_root)), {})

    roots = {root["label"]: root["path"] for root in snapshot["roots"]}
    labels = [root["label"] for root in snapshot["roots"]]
    assert snapshot["cwd"] == _display_path(app_root)
    assert roots["Shinsekai"] == _display_path(app_root)
    assert roots["Data"] == _display_path(data_root)
    assert roots["Downloads"] == _display_path(downloads_root)
    assert labels.index("Data") < labels.index("Downloads") < labels.index("Home")
    assert data_root.is_dir()


def test_file_browser_uses_xdg_download_dir(tmp_path, monkeypatch):
    if os.name == "nt":
        return

    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    home = tmp_path / "home"
    downloads_root = home / "下载"
    config_dir = home / ".config"
    app_root.mkdir()
    downloads_root.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    (config_dir / "user-dirs.dirs").write_text(
        'XDG_DOWNLOAD_DIR="$HOME/下载"\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    snapshot = _browse_local_files(SimpleNamespace(app_root_dir=str(app_root)), {})

    roots = {root["label"]: root["path"] for root in snapshot["roots"]}
    assert roots["Downloads"] == _display_path(downloads_root)


def test_file_browser_relative_paths_still_resolve_from_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    target = project_root / "data"
    app_root.mkdir()
    target.mkdir(parents=True)

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    snapshot = _browse_local_files(SimpleNamespace(app_root_dir=str(app_root)), {"path": "data"})

    assert snapshot["cwd"] == _display_path(target)
