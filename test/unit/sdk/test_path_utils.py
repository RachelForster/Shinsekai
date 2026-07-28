from __future__ import annotations

from pathlib import Path

import pytest

from sdk.path_utils import (
    safe_child_path,
    safe_existing_file_path,
    safe_filename,
    safe_project_path,
)


def test_safe_project_path_accepts_only_paths_inside_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    assert safe_project_path("data/item.json", root=root) == (
        root / "data" / "item.json"
    ).resolve(strict=False)
    assert safe_project_path(root / "data" / "item.json", root=root) == (
        root / "data" / "item.json"
    ).resolve(strict=False)

    with pytest.raises(PermissionError):
        safe_project_path("../project-copy/item.json", root=root)

    with pytest.raises(PermissionError):
        safe_project_path(tmp_path / "outside.json", root=root)


def test_safe_project_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError):
        safe_project_path(link / "secret.txt", root=root)


def test_safe_child_path_rejects_traversal_and_drive_paths(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    assert safe_child_path(root, "/assets/app.js") == (
        root / "assets" / "app.js"
    ).resolve(strict=False)

    with pytest.raises(PermissionError):
        safe_child_path(root, "../outside.txt")

    drive = Path(root.drive + "\\outside.txt") if root.drive else None
    if drive is not None:
        with pytest.raises(PermissionError):
            safe_child_path(root, drive)


def test_safe_filename_rejects_path_components():
    assert safe_filename("角色.char") == "角色.char"
    assert safe_filename("report", default_suffix=".txt") == "report.txt"

    for value in ("../secret", "folder/file", r"folder\file", ".", ".."):
        with pytest.raises(ValueError):
            safe_filename(value)


def test_safe_existing_file_path_requires_an_explicit_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    expected = allowed / "item.txt"
    expected.write_text("ok", encoding="utf-8")
    secret = outside / "secret.txt"
    secret.write_text("no", encoding="utf-8")

    assert safe_existing_file_path(expected, roots=[allowed]) == expected.resolve()
    assert safe_existing_file_path("item.txt", roots=[allowed]) == expected.resolve()

    with pytest.raises(PermissionError):
        safe_existing_file_path(secret, roots=[allowed])

    with pytest.raises(ValueError, match="trusted path root"):
        safe_existing_file_path(expected, roots=[])
