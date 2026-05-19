from __future__ import annotations

import io
import stat
import tarfile
import zipfile

import pytest

from llm.tools.file_tools import (
    file_extract,
    file_info,
    file_read,
    file_search,
    file_search_content,
)


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


def test_file_read_rejects_sensitive_ssh_path(tmp_path) -> None:
    key_path = tmp_path / ".ssh" / "id_rsa"
    key_path.parent.mkdir()
    key_path.write_text("PRIVATE KEY", encoding="utf-8")

    result = file_read(str(key_path))

    assert "error" in result
    assert "PRIVATE KEY" not in str(result)


def test_file_search_content_skips_project_data_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path))
    config_path = tmp_path / "data" / "config" / "api.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("llm_api_key: sk-secret", encoding="utf-8")

    result = file_search_content("sk-secret", str(tmp_path), "*.yaml")

    assert result["count"] == 0
    assert result["matches"] == []


def test_file_search_skips_sensitive_directories(tmp_path) -> None:
    key_path = tmp_path / ".ssh" / "id_ed25519"
    key_path.parent.mkdir()
    key_path.write_text("PRIVATE KEY", encoding="utf-8")
    public_path = tmp_path / "notes.txt"
    public_path.write_text("ok", encoding="utf-8")

    result = file_search("*", str(tmp_path))

    names = {item["name"] for item in result["matches"]}
    assert "notes.txt" in names
    assert "id_ed25519" not in names


def test_file_info_rejects_sensitive_project_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path))
    config_path = tmp_path / "data" / "config" / "mcp.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("servers: []", encoding="utf-8")

    result = file_info(str(config_path))

    assert "error" in result
