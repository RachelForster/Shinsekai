from __future__ import annotations

import io
import hashlib
import shutil
import stat
import zipfile

import pytest

from core.plugins.archive_safety import UnsafeArchiveError, safe_extract_zip_single_top
from core.plugins.github_bundle_update import (
    ArchiveDigestMismatchError,
    download_zip_extract_top_folder,
    github_archive_zip_url,
    resolve_ref_for_download,
)


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


def test_github_archive_download_accepts_matching_sha256(monkeypatch) -> None:
    body = _zip_bytes({"repo-main/file.txt": "ok"})
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(
        "core.plugins.github_bundle_update.stream_download_zip",
        lambda *args, **kwargs: body,
    )

    tmp_parent, extracted = download_zip_extract_top_folder(
        "owner/repo",
        ref_heads_or_tags="heads",
        ref_name="main",
        expected_archive_sha256=digest,
    )

    try:
        assert (extracted / "file.txt").read_text(encoding="utf-8") == "ok"
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def test_github_archive_commit_ref_uses_pinned_archive_url() -> None:
    sha = "A" * 40

    assert resolve_ref_for_download("owner/repo", "commit", sha) == ("commit", "a" * 40)
    assert github_archive_zip_url(
        "owner/repo",
        ref_heads_or_tags="commit",
        ref_name=sha,
    ) == f"https://github.com/owner/repo/archive/{sha.lower()}.zip"


def test_github_archive_commit_ref_rejects_non_sha() -> None:
    with pytest.raises(ValueError, match="commit SHA"):
        resolve_ref_for_download("owner/repo", "commit", "main")


def test_github_archive_invalid_sha256_fails_before_download(monkeypatch) -> None:
    def _unexpected_download(*args, **kwargs):
        raise AssertionError("download should not start for malformed archive_sha256")

    monkeypatch.setattr(
        "core.plugins.github_bundle_update.stream_download_zip",
        _unexpected_download,
    )

    with pytest.raises(ValueError, match="archive_sha256"):
        download_zip_extract_top_folder(
            "owner/repo",
            ref_heads_or_tags="heads",
            ref_name="main",
            expected_archive_sha256="not-a-digest",
        )


def test_github_archive_download_rejects_mismatched_sha256(monkeypatch) -> None:
    body = _zip_bytes({"repo-main/file.txt": "ok"})
    monkeypatch.setattr(
        "core.plugins.github_bundle_update.stream_download_zip",
        lambda *args, **kwargs: body,
    )

    with pytest.raises(ArchiveDigestMismatchError, match="sha256 mismatch"):
        download_zip_extract_top_folder(
            "owner/repo",
            ref_heads_or_tags="heads",
            ref_name="main",
            expected_archive_sha256="0" * 64,
        )
