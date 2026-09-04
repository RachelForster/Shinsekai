import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_bridge_core.tools import (
    _browse_local_files,
    _display_path,
    _file_browser_root_key,
    _file_browser_root_label,
    _local_file_access_roots,
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


def test_file_browser_rejects_paths_outside_local_access_roots(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    for path in (project_root, app_root, home, outside):
        path.mkdir()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    if os.name == "nt":
        # Every existing local drive is a root (matching the sidebar), so only
        # network/UNC locations remain outside the allowed roots.
        outside_path = "\\\\server\\share\\folder"
    else:
        outside_path = str(outside)

    with pytest.raises(PermissionError, match="outside the allowed roots"):
        _browse_local_files(
            SimpleNamespace(app_root_dir=str(app_root)),
            {"path": outside_path},
        )


def test_local_file_access_roots_include_existing_drives(tmp_path, monkeypatch):
    if os.name != "nt":
        return

    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    project_root.mkdir()
    app_root.mkdir()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    roots = _local_file_access_roots(SimpleNamespace(app_root_dir=str(app_root)))

    for code in range(ord("A"), ord("Z") + 1):
        drive = Path(f"{chr(code)}:/")
        if drive.exists():
            assert drive.resolve(strict=False) in roots
