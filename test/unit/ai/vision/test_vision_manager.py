from __future__ import annotations

import pytest

from ai.vision import VisionAdapter, VisionManager
from ai.vision.moondream_adapter import MoondreamPluginUnavailable, MoondreamVisionAdapter


class FakeVisionAdapter(VisionAdapter):
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return f"{len(image_bytes)}:{prompt}"


def test_vision_manager_dispatches_to_registered_adapter(monkeypatch):
    monkeypatch.setattr(VisionManager, "_adapters", dict(VisionManager._adapters))
    VisionManager.register_adapter("fake", FakeVisionAdapter)

    manager = VisionManager("FAKE")

    assert manager.describe(b"image", "describe") == "5:describe"


def test_moondream_adapter_requires_the_optional_plugin(monkeypatch):
    monkeypatch.setattr("ai.vision.moondream_adapter.installed_moondream_directory", lambda: None)

    with pytest.raises(MoondreamPluginUnavailable, match="Moondream"):
        MoondreamVisionAdapter()
