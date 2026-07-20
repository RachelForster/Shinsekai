from __future__ import annotations

import base64
from pathlib import Path

from ai.vision.message_content import normalize_anthropic_user_content, normalize_openai_messages
from ai.vision.service import ChatVisionService
from core.media.chat_attachments import resolve_chat_attachments


class _NativeAdapter:
    supports_native_vision = True


class _TextAdapter:
    supports_native_vision = False


class _UnknownAdapter:
    pass


class _FallbackVision:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        self.calls.append((image_bytes, prompt))
        return "a moon over a quiet lake"


def _image_attachment(tmp_path: Path):
    path = tmp_path / "moon.png"
    path.write_bytes(b"image-bytes")
    return resolve_chat_attachments([{"kind": "image", "path": str(path)}])[0]


def test_chat_vision_service_prefers_native_image_blocks(tmp_path: Path):
    image = _image_attachment(tmp_path)

    prepared = ChatVisionService().prepare("What is here?", [image], adapter=_NativeAdapter())

    assert prepared.mode == "native"
    assert isinstance(prepared.content, list)
    assert prepared.content[0] == {"type": "text", "text": "What is here?\n\nImage attachments: moon.png"}
    assert prepared.content[1]["type"] == "local_image"
    assert prepared.content[1]["path"] == str(image.path)
    assert prepared.content[1]["data"] == base64.b64encode(b"image-bytes").decode("ascii")


def test_chat_vision_service_falls_back_to_moondream_for_text_only_adapter(tmp_path: Path):
    image = _image_attachment(tmp_path)
    fallback = _FallbackVision()

    prepared = ChatVisionService(lambda: fallback).prepare("Explain", [image], adapter=_TextAdapter())

    assert prepared.mode == "fallback"
    assert "a moon over a quiet lake" in prepared.content
    assert fallback.calls[0][0] == b"image-bytes"


def test_native_image_blocks_are_encoded_only_at_provider_boundary(tmp_path: Path):
    image = _image_attachment(tmp_path)
    prepared = ChatVisionService().prepare("Inspect", [image], adapter=_NativeAdapter())
    messages = [{"role": "user", "content": prepared.content}]

    openai = normalize_openai_messages(messages, supports_native_vision=True)
    data_url = openai[0]["content"][1]["image_url"]["url"]
    assert data_url == f"data:image/png;base64,{base64.b64encode(b'image-bytes').decode('ascii')}"
    assert messages[0]["content"][1]["type"] == "local_image"

    anthropic = normalize_anthropic_user_content(prepared.content)
    assert anthropic[1]["type"] == "image"
    assert anthropic[1]["source"]["media_type"] == "image/png"
    assert anthropic[1]["source"]["data"] == base64.b64encode(b"image-bytes").decode("ascii")


def test_persisted_image_data_survives_deleted_source_file(tmp_path: Path):
    image = _image_attachment(tmp_path)
    prepared = ChatVisionService().prepare("Inspect", [image], adapter=_NativeAdapter())
    messages = [{"role": "user", "content": prepared.content}]
    image.path.unlink()

    openai = normalize_openai_messages(messages, supports_native_vision=True)
    assert openai[0]["content"][1]["image_url"]["url"].endswith(
        base64.b64encode(b"image-bytes").decode("ascii")
    )
    anthropic = normalize_anthropic_user_content(prepared.content)
    assert anthropic[1]["source"]["data"] == base64.b64encode(b"image-bytes").decode("ascii")


def test_stale_legacy_image_path_is_safely_omitted(tmp_path: Path):
    missing = tmp_path / "missing.png"
    content = [
        {"type": "text", "text": "Continue the conversation"},
        {"type": "local_image", "media_type": "image/png", "name": "missing.png", "path": str(missing)},
    ]

    openai = normalize_openai_messages(
        [{"role": "user", "content": content}],
        supports_native_vision=True,
    )
    assert openai[0]["content"][1]["type"] == "text"
    assert "no longer available" in openai[0]["content"][1]["text"]
    anthropic = normalize_anthropic_user_content(content)
    assert anthropic[1]["type"] == "text"
    assert "no longer available" in anthropic[1]["text"]


def test_historical_images_are_downgraded_for_text_only_model(tmp_path: Path):
    image = _image_attachment(tmp_path)
    prepared = ChatVisionService().prepare("Inspect", [image], adapter=_NativeAdapter())

    normalized = normalize_openai_messages(
        [
            {
                "role": "user",
                "content": prepared.content,
                "display_content": "Inspect\n[image: moon.png]",
                "input_text": "Inspect",
                "attachments": [{"kind": "image", "path": str(image.path)}],
            }
        ],
        supports_native_vision=False,
    )

    assert isinstance(normalized[0]["content"], str)
    assert "current model does not support image input" in normalized[0]["content"]
    assert "image_url" not in normalized[0]["content"]
    assert "display_content" not in normalized[0]
    assert "input_text" not in normalized[0]
    assert "attachments" not in normalized[0]


def test_unknown_vision_capability_defaults_to_safe_unavailable_fallback(tmp_path: Path):
    image = _image_attachment(tmp_path)
    factory_called = False

    def fallback_factory():
        nonlocal factory_called
        factory_called = True
        return _FallbackVision()

    prepared = ChatVisionService(
        fallback_factory,
        fallback_available=lambda: False,
    ).prepare("Inspect", [image], adapter=_UnknownAdapter())

    assert ChatVisionService.supports_native_images(_UnknownAdapter()) is False
    assert prepared.mode == "unavailable"
    assert "Moondream" in prepared.content
    assert "moon.png" in prepared.content
    assert factory_called is False


def test_missing_default_moondream_plugin_returns_recoverable_prompt(tmp_path: Path, monkeypatch):
    image = _image_attachment(tmp_path)
    monkeypatch.setattr("ai.vision.service.installed_moondream_directory", lambda: None)

    prepared = ChatVisionService().prepare("Inspect", [image], adapter=_TextAdapter())

    assert prepared.mode == "unavailable"
    assert "switch to a vision-capable model" in prepared.content


def test_file_attachments_are_read_locally_and_passed_to_the_llm(tmp_path: Path):
    document = tmp_path / "facts.txt"
    document.write_text("facts", encoding="utf-8")
    attachment = resolve_chat_attachments([{"kind": "file", "path": str(document)}])[0]
    reads: list[str] = []

    def local_file_read(path: str):
        reads.append(path)
        return {"content": "facts from local file_read", "path": path, "truncated": False}

    prepared = ChatVisionService(file_reader=local_file_read).prepare("Read it", [attachment], adapter=_NativeAdapter())

    assert prepared.mode == "text"
    assert reads == [str(document.resolve())]
    assert "facts from local file_read" in prepared.content
    assert "BEGIN ATTACHED FILE: facts.txt" in prepared.content
