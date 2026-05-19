from __future__ import annotations

import io
import stat
import tarfile
import zipfile

import pytest

from llm.tools.file_tools import file_extract


pytestmark = pytest.mark.unit


def test_file_extract_zip_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "evil.zip"
    escaped = tmp_path / "escape.txt"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "owned")

    result = file_extract(str(archive), str(tmp_path / "out"))

    assert "error" in result
    assert not escaped.exists()


def test_file_extract_tar_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "evil.tar"
    escaped = tmp_path / "escape.txt"
    data = b"owned"
    with tarfile.open(archive, "w") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    result = file_extract(str(archive), str(tmp_path / "out"))

    assert "error" in result
    assert not escaped.exists()


def test_file_extract_tar_rejects_links(tmp_path) -> None:
    archive = tmp_path / "evil.tar"
    with tarfile.open(archive, "w") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../escape.txt"
        tf.addfile(info)

    result = file_extract(str(archive), str(tmp_path / "out"))

    assert "error" in result


def test_file_extract_zip_rejects_links(tmp_path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "../escape.txt")

    result = file_extract(str(archive), str(tmp_path / "out"))

    assert "error" in result


def test_file_extract_zip_extracts_safe_members(tmp_path) -> None:
    archive = tmp_path / "safe.zip"
    out_dir = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/file.txt", "ok")

    result = file_extract(str(archive), str(out_dir))

    assert "error" not in result
    assert (out_dir / "nested" / "file.txt").read_text(encoding="utf-8") == "ok"
