from __future__ import annotations

from pathlib import Path

import pytest

from ai.vision import fallback_registry
from ai.vision.cloud_vision_adapter import CloudVisionPluginUnavailable
from ai.vision.moondream_adapter import MoondreamPluginUnavailable
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


class _ScriptedManager:
    def __init__(self, *results: str | Exception) -> None:
        self.results = list(results)
        self.calls: list[tuple[bytes, str]] = []

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        self.calls.append((image_bytes, prompt))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _clean_registry():
    fallback_registry.configure_registered_fallbacks([])
    yield
    fallback_registry.configure_registered_fallbacks([])


def _image(
    tmp_path: Path,
    name: str = "apple.png",
    image_bytes: bytes = b"apple-bytes",
) -> ResolvedChatAttachment:
    path = tmp_path / name
    path.write_bytes(image_bytes)
    return ResolvedChatAttachment(
        kind="image", mime_type="image/png", name=name, path=path, size=path.stat().st_size
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
    monkeypatch.setattr("ai.vision.service.cloud_vision_available", lambda: False)
    monkeypatch.setattr("ai.vision.service.installed_moondream_directory", lambda: None)

    prepared = ChatVisionService().prepare("what's this?", [_image(tmp_path)], adapter=_TextAdapter())

    assert prepared.mode == "unavailable"
    assert "Moondream" in prepared.content


def test_legacy_cloud_vision_is_preferred_over_moondream(tmp_path: Path, monkeypatch):
    manager = _FakeManager()
    providers: list[str] = []

    def manager_factory(provider: str):
        providers.append(provider)
        return manager

    monkeypatch.setattr("ai.vision.service.cloud_vision_available", lambda: True)
    monkeypatch.setattr("ai.vision.service.VisionManager", manager_factory)

    prepared = ChatVisionService().prepare("what's this?", [_image(tmp_path)], adapter=_TextAdapter())

    assert prepared.mode == "fallback"
    assert providers == ["cloud_vision"]
    assert "cloud vision saw a red apple" in prepared.content


def test_cloud_failure_switches_current_and_remaining_images_to_moondream(
    tmp_path: Path,
    monkeypatch,
):
    providers: list[str] = []
    cloud = _ScriptedManager(
        "cloud first",
        CloudVisionPluginUnavailable("cloud request failed"),
    )
    moondream = _ScriptedManager("moondream second", "moondream third")

    def manager_factory(provider: str):
        providers.append(provider)
        return cloud if provider == "cloud_vision" else moondream

    images = [
        _image(tmp_path, "first.png", b"first"),
        _image(tmp_path, "second.png", b"second"),
        _image(tmp_path, "third.png", b"third"),
    ]
    monkeypatch.setattr("ai.vision.service.cloud_vision_available", lambda: True)
    monkeypatch.setattr("ai.vision.service.VisionManager", manager_factory)

    prepared = ChatVisionService().prepare("inspect", images, adapter=_TextAdapter())

    assert prepared.mode == "fallback"
    assert providers == ["cloud_vision", "moondream"]
    assert [call[0] for call in cloud.calls] == [b"first", b"second"]
    assert [call[0] for call in moondream.calls] == [b"second", b"third"]
    assert prepared.content == (
        "inspect\n\n"
        "Image attachment first.png:\ncloud first\n\n"
        "Image attachment second.png:\nmoondream second\n\n"
        "Image attachment third.png:\nmoondream third"
    )


def test_cloud_and_moondream_failure_returns_unavailable(
    tmp_path: Path,
    monkeypatch,
):
    providers: list[str] = []
    cloud = _ScriptedManager(CloudVisionPluginUnavailable("cloud request failed"))
    moondream = _ScriptedManager(MoondreamPluginUnavailable("moondream failed"))

    def manager_factory(provider: str):
        providers.append(provider)
        return cloud if provider == "cloud_vision" else moondream

    image = _image(tmp_path)
    monkeypatch.setattr("ai.vision.service.cloud_vision_available", lambda: True)
    monkeypatch.setattr("ai.vision.service.VisionManager", manager_factory)

    prepared = ChatVisionService().prepare("inspect", [image], adapter=_TextAdapter())

    assert prepared.mode == "unavailable"
    assert providers == ["cloud_vision", "moondream"]
    assert [call[0] for call in cloud.calls] == [b"apple-bytes"]
    assert [call[0] for call in moondream.calls] == [b"apple-bytes"]
    assert "apple.png" in prepared.content
