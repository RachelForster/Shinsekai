from __future__ import annotations

import pytest
from types import SimpleNamespace

from ai.vision import VisionAdapter, VisionManager
from ai.vision.moondream_adapter import (
    MoondreamPluginUnavailable,
    MoondreamVisionAdapter,
)


class FakeVisionAdapter(VisionAdapter):
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return f"{len(image_bytes)}:{prompt}"


def test_vision_manager_dispatches_to_registered_adapter(monkeypatch):
    monkeypatch.setattr(VisionManager, "_adapters", dict(VisionManager._adapters))
    VisionManager.register_adapter("fake", FakeVisionAdapter)

    manager = VisionManager("FAKE")

    assert manager.describe(b"image", "describe") == "5:describe"


def test_builtin_vision_uses_the_supplied_config_snapshot_including_extra_options(
    monkeypatch,
):
    calls = []

    class ConfiguredAdapter(FakeVisionAdapter):
        def __init__(self, api_key, base_url, model, detail="auto"):
            calls.append((api_key, base_url, model, detail))

    monkeypatch.setitem(VisionManager._builtin_adapters, "deepseek", ConfiguredAdapter)
    monkeypatch.setitem(VisionManager._adapters, "deepseek", ConfiguredAdapter)
    config = SimpleNamespace(
        llm_api_key={"Deepseek": "snapshot-key"},
        llm_provider="Deepseek",
        llm_base_urls={"Deepseek": "https://snapshot.example.com/v1"},
        llm_model={"Deepseek": "snapshot-model"},
        vision_model={},
        vision_extra_configs={"deepseek": {"detail": "high"}},
    )
    manager = VisionManager("deepseek", api_config=config)
    assert manager.describe(b"image", "inspect") == "5:inspect"
    assert calls == [
        ("snapshot-key", "https://snapshot.example.com/v1", "snapshot-model", "high")
    ]


def test_legacy_saved_default_reaches_the_adapter_as_the_current_llm_model(monkeypatch):
    from ai.vision import configured_vision_manager
    from config.schema import ApiConfig

    models = []

    class ConfiguredAdapter(FakeVisionAdapter):
        def __init__(self, model, **kwargs):
            models.append(model)

    monkeypatch.setitem(VisionManager._builtin_adapters, "deepseek", ConfiguredAdapter)
    monkeypatch.setitem(VisionManager._adapters, "deepseek", ConfiguredAdapter)
    config = ApiConfig.model_validate(
        {
            "vision_provider": "auto",
            "vision_model": {"deepseek": "deepseek-flash"},
            "llm_provider": "Deepseek",
            "llm_model": {"Deepseek": "current-model"},
        }
    )
    configured_vision_manager(api_config=config)
    assert models == ["current-model"]


def test_moondream_adapter_requires_the_optional_plugin(monkeypatch):
    monkeypatch.setattr(
        "ai.vision.moondream_adapter.installed_moondream_directory", lambda: None
    )

    with pytest.raises(MoondreamPluginUnavailable, match="Moondream"):
        MoondreamVisionAdapter()


def test_moondream_adapter_requires_the_model_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai.vision.moondream_adapter.installed_moondream_directory",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "ai.vision.moondream_adapter.moondream_model_cached",
        lambda: False,
    )

    with pytest.raises(MoondreamPluginUnavailable, match="模型尚未下载"):
        MoondreamVisionAdapter()
