from __future__ import annotations

import io
import stat
import tarfile
import zipfile

import pytest

from llm.tools.file_tools import (
    file_append,
    file_copy,
    file_delete,
    file_extract,
    file_info,
    file_mkdir,
    file_move,
    file_read,
    file_search,
    file_search_content,
    file_write,
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


def test_file_extract_zip_rejects_zip_bomb_like_member(tmp_path) -> None:
    archive = tmp_path / "bomb.zip"
    out_dir = tmp_path / "out"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("nested/bomb.txt", "0" * (1024 * 1024))

    result = file_extract(str(archive), str(out_dir))

    assert "error" in result
    assert not (out_dir / "nested" / "bomb.txt").exists()


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


def test_mutating_tools_reject_sensitive_paths_without_writing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_rsa"
    key_path.write_text("ORIGINAL", encoding="utf-8")
    public_file = tmp_path / "public.txt"
    public_file.write_text("PUBLIC", encoding="utf-8")
    sensitive_config = tmp_path / "data" / "config" / "api.yaml"

    assert "error" in file_write(str(key_path), "PWN")
    assert key_path.read_text(encoding="utf-8") == "ORIGINAL"

    assert "error" in file_append(str(key_path), "+PWN")
    assert key_path.read_text(encoding="utf-8") == "ORIGINAL"

    assert "error" in file_copy(str(public_file), str(ssh_dir / "copied_key"))
    assert not (ssh_dir / "copied_key").exists()

    assert "error" in file_move(str(key_path), str(tmp_path / "moved_key"))
    assert key_path.exists()
    assert not (tmp_path / "moved_key").exists()

    assert "error" in file_delete(str(key_path))
    assert key_path.exists()

    assert "error" in file_mkdir(str(sensitive_config.parent))
    assert not sensitive_config.parent.exists()


def test_file_extract_rejects_sensitive_destination_before_creating(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path))
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/file.txt", "ok")
    sensitive_dest = tmp_path / "data" / "config" / "extract"

    result = file_extract(str(archive), str(sensitive_dest))

    assert "error" in result
    assert not sensitive_dest.exists()


def test_file_delete_reports_deleted_file_size(tmp_path) -> None:
    target = tmp_path / "delete-me.txt"
    target.write_text("abc", encoding="utf-8")

    result = file_delete(str(target))

    assert result == {
        "deleted": str(target),
        "type": "file",
        "size_human": "3.0B",
    }
    assert not target.exists()
