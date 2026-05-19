from __future__ import annotations

import io
import stat
import zipfile

import pytest

from core.plugins.archive_safety import UnsafeArchiveError, safe_extract_zip_single_top
from core.plugins.github_bundle_update import download_zip_extract_top_folder


pytestmark = pytest.mark.unit


def _write_zip(path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return buf.getvalue()


def test_safe_zip_extracts_single_top_folder(tmp_path) -> None:
    archive = tmp_path / "safe.zip"
    out_dir = tmp_path / "out"
    _write_zip(archive, {"repo-main/nested/file.txt": "ok"})

    extracted = safe_extract_zip_single_top(archive, out_dir)

    assert extracted == out_dir / "repo-main"
    assert (extracted / "nested" / "file.txt").read_text(encoding="utf-8") == "ok"


def test_safe_zip_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "evil.zip"
    escaped = tmp_path / "escape.txt"
    _write_zip(archive, {"repo-main/../../escape.txt": "owned"})

    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip_single_top(archive, tmp_path / "out")

    assert not escaped.exists()


def test_safe_zip_rejects_absolute_and_windows_drive_paths(tmp_path) -> None:
    archive = tmp_path / "evil.zip"
    _write_zip(archive, {"/abs.txt": "owned", "C:/escape.txt": "owned"})

    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip_single_top(archive, tmp_path / "out")


def test_safe_zip_rejects_symlink_entries(tmp_path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("repo-main/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "../escape.txt")

    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip_single_top(archive, tmp_path / "out")


def test_safe_zip_rejects_multiple_top_folders(tmp_path) -> None:
    archive = tmp_path / "multi.zip"
    _write_zip(archive, {"one/a.txt": "1", "two/b.txt": "2"})

    with pytest.raises(UnsafeArchiveError, match="one top-level"):
        safe_extract_zip_single_top(archive, tmp_path / "out")


def test_github_archive_download_uses_safe_extraction(tmp_path, monkeypatch) -> None:
    body = _zip_bytes({"repo-main/../../escape.txt": "owned"})
    monkeypatch.setattr(
        "core.plugins.github_bundle_update.stream_download_zip",
        lambda *args, **kwargs: body,
    )

    with pytest.raises(UnsafeArchiveError):
        download_zip_extract_top_folder(
            "owner/repo",
            ref_heads_or_tags="heads",
            ref_name="main",
        )
