from __future__ import annotations

from pathlib import Path

import pytest

from core.media.chat_attachments import (
    CHAT_ATTACHMENTS_ROOT_ENV,
    _chat_attachment_root,
    chat_attachment_display_text,
    resolve_chat_attachments,
)


@pytest.fixture(autouse=True)
def clear_attachment_root_cache():
    _chat_attachment_root.cache_clear()
    yield
    _chat_attachment_root.cache_clear()


def test_resolve_chat_attachments_derives_trusted_metadata_and_deduplicates(tmp_path: Path):
    image = tmp_path / "scene.png"
    image.write_bytes(b"png")

    attachments = resolve_chat_attachments(
        [
            {"kind": "image", "name": "spoofed.exe", "path": str(image)},
            {"kind": "image", "path": str(image)},
        ]
    )

    assert len(attachments) == 1
    assert attachments[0].name == "scene.png"
    assert attachments[0].mime_type == "image/png"
    assert attachments[0].path == image.resolve()


def test_resolve_chat_attachments_rejects_relative_and_non_image_paths(tmp_path: Path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("notes", encoding="utf-8")

    with pytest.raises(ValueError, match="absolute"):
        resolve_chat_attachments([{"kind": "file", "path": "notes.txt"}])
    with pytest.raises(ValueError, match="Unsupported chat image type"):
        resolve_chat_attachments([{"kind": "image", "path": str(text_file)}])


def test_resolve_chat_attachments_rejects_paths_outside_configured_root(tmp_path: Path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_file = tmp_path / "private.txt"
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(allowed_root))

    with pytest.raises(ValueError, match="outside the allowed directory"):
        resolve_chat_attachments([{"kind": "file", "path": str(outside_file)}])


def test_resolve_chat_attachments_requires_configured_root(tmp_path: Path, monkeypatch):
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    monkeypatch.delenv(CHAT_ATTACHMENTS_ROOT_ENV, raising=False)

    with pytest.raises(ValueError, match=f"{CHAT_ATTACHMENTS_ROOT_ENV} must be configured"):
        resolve_chat_attachments([{"kind": "file", "path": str(document)}])


def test_chat_attachment_display_uses_trusted_file_name(tmp_path: Path):
    document = tmp_path / "story.txt"
    document.write_text("Once upon a time", encoding="utf-8")
    attachments = resolve_chat_attachments([{"kind": "file", "path": str(document)}])

    assert chat_attachment_display_text("Summarize", attachments) == "Summarize\n[file: story.txt]"
