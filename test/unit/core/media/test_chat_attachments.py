from __future__ import annotations

from pathlib import Path

import pytest

from core.media import chat_attachments
from core.media.chat_attachments import (
    CHAT_ATTACHMENT_STAGE_SUBDIR,
    CHAT_ATTACHMENTS_ROOT_ENV,
    MAX_CHAT_ATTACHMENTS,
    _chat_attachment_root,
    chat_attachment_display_text,
    resolve_chat_attachments,
    stage_uploaded_chat_attachments,
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


def test_resolve_chat_attachments_rejects_explicit_traversal_segments(tmp_path: Path):
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    traversal_path = tmp_path / "nested" / ".." / document.name

    with pytest.raises(ValueError, match="invalid traversal segments"):
        resolve_chat_attachments([{"kind": "file", "path": str(traversal_path)}])


def test_resolve_chat_attachments_rejects_paths_outside_configured_root(tmp_path: Path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_root = tmp_path / "allowed-private"
    outside_root.mkdir()
    outside_file = outside_root / "private.txt"
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


def test_stage_uploaded_attachments_rejects_count_before_copying(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    sources = []
    for index in range(MAX_CHAT_ATTACHMENTS + 1):
        source = uploads / f"file-{index}.txt"
        source.write_text("x", encoding="utf-8")
        sources.append(source)
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))

    with pytest.raises(ValueError, match="at most"):
        stage_uploaded_chat_attachments(sources)

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_copies_validated_batch_inside_allowed_root(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    image = uploads / "scene.png"
    document = uploads / "notes.txt"
    image.write_bytes(b"png")
    document.write_text("notes", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))

    payloads = stage_uploaded_chat_attachments([image, document])
    resolved = resolve_chat_attachments(payloads)

    assert [attachment.kind for attachment in resolved] == ["image", "file"]
    assert [attachment.name for attachment in resolved] == ["scene.png", "notes.txt"]
    assert all(attachment.path.is_relative_to(root) for attachment in resolved)


def test_stage_uploaded_attachments_rejects_aggregate_size_before_copying(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    first = uploads / "first.txt"
    second = uploads / "second.txt"
    first.write_bytes(b"123")
    second.write_bytes(b"456")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    monkeypatch.setattr(chat_attachments, "MAX_CHAT_ATTACHMENTS_TOTAL_BYTES", 5)

    with pytest.raises(ValueError, match="total size"):
        stage_uploaded_chat_attachments([first, second])

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_rolls_back_partial_copy(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    first = uploads / "first.txt"
    second = uploads / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    real_copy = chat_attachments.shutil.copyfile
    copy_count = 0

    def fail_second_copy(source, destination):
        nonlocal copy_count
        copy_count += 1
        if copy_count == 2:
            raise OSError("copy failed")
        return real_copy(source, destination)

    monkeypatch.setattr(chat_attachments.shutil, "copyfile", fail_second_copy)

    with pytest.raises(OSError, match="copy failed"):
        stage_uploaded_chat_attachments([first, second])

    stage_root = root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    assert stage_root.is_dir()
    assert list(stage_root.iterdir()) == []
