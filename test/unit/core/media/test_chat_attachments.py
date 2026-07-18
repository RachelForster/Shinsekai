from __future__ import annotations

from pathlib import Path

import pytest

from core.media.chat_attachments import (
    chat_attachment_display_text,
    chat_file_tool_prompt,
    resolve_chat_attachments,
)


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


def test_chat_attachment_prompts_keep_display_names_separate_from_tool_paths(tmp_path: Path):
    document = tmp_path / "story.txt"
    document.write_text("Once upon a time", encoding="utf-8")
    attachments = resolve_chat_attachments([{"kind": "file", "path": str(document)}])

    assert chat_attachment_display_text("Summarize", attachments) == "Summarize\n[file: story.txt]"
    prompt = chat_file_tool_prompt(attachments)
    assert "file_read" in prompt
    assert str(document.resolve()) in prompt
