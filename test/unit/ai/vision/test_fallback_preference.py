from __future__ import annotations

from pathlib import Path

import pytest

from ai.vision import fallback_registry
from ai.vision.service import ChatVisionService
from core.media.chat_attachments import ResolvedChatAttachment
from sdk.adapters import VisionFallbackContribution


class _TextAdapter:
    supports_native_vision = False


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        self.calls.append((image_bytes, prompt))
        return "cloud vision saw a red apple"


@pytest.fixture(autouse=True)
def _clean_registry():
    fallback_registry.configure_registered_fallbacks([])
    yield
    fallback_registry.configure_registered_fallbacks([])


def _image(tmp_path: Path) -> ResolvedChatAttachment:
    path = tmp_path / "apple.png"
    path.write_bytes(b"apple-bytes")
    return ResolvedChatAttachment(
        kind="image", mime_type="image/png", name="apple.png", path=path, size=path.stat().st_size
    )


def test_default_service_uses_registered_preferred_fallback(tmp_path: Path):
    manager = _FakeManager()
    fallback_registry.configure_registered_fallbacks(
        [VisionFallbackContribution("plugin.cloud", lambda: manager, lambda: True)]
    )

    prepared = ChatVisionService().prepare("what's this?", [_image(tmp_path)], adapter=_TextAdapter())

    assert prepared.mode == "fallback"
    assert "cloud vision saw a red apple" in prepared.content
    assert manager.calls and manager.calls[0][0] == b"apple-bytes"


def test_unavailable_preferred_fallback_is_bypassed(tmp_path: Path, monkeypatch):
    # No Moondream installed and the preferred fallback reports unavailable →
    # the service must not use the preferred fallback and reports "unavailable".
    monkeypatch.setattr("ai.vision.service.installed_moondream_directory", lambda: None)
    manager = _FakeManager()
    fallback_registry.configure_registered_fallbacks(
        [VisionFallbackContribution("plugin.cloud", lambda: manager, lambda: False)]
    )

    prepared = ChatVisionService().prepare("what's this?", [_image(tmp_path)], adapter=_TextAdapter())

    assert prepared.mode == "unavailable"
    assert not manager.calls


def test_no_registration_falls_back_to_moondream_default(tmp_path: Path, monkeypatch):
    # With nothing registered and no Moondream, behavior is unchanged from stock 2.3.
    monkeypatch.setattr("ai.vision.service.installed_moondream_directory", lambda: None)

    prepared = ChatVisionService().prepare("what's this?", [_image(tmp_path)], adapter=_TextAdapter())

    assert prepared.mode == "unavailable"
    assert "Moondream" in prepared.content
