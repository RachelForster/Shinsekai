from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.vision.cloud_vision_adapter import (
    CloudVisionAdapter,
    CloudVisionPluginUnavailable,
    installed_cloud_vision_directory,
)


@pytest.mark.parametrize("enabled", [False, 0, None, ""])
def test_installed_plugin_requires_enabled_manifest_entry(
    tmp_path: Path,
    monkeypatch,
    enabled,
):
    plugin_dir = tmp_path / "plugins" / "cloud_vision"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.read_plugin_manifest_items",
        lambda: [
            {
                "entry": "plugins.cloud_vision.plugin:CloudVisionPlugin",
                "enabled": enabled,
            }
        ],
    )

    assert installed_cloud_vision_directory() is None


def test_installed_plugin_defaults_manifest_entry_to_enabled(tmp_path: Path, monkeypatch):
    plugin_dir = tmp_path / "plugins" / "cloud_vision"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.read_plugin_manifest_items",
        lambda: [{"entry": "plugins.cloud_vision.plugin:CloudVisionPlugin"}],
    )

    assert installed_cloud_vision_directory() == plugin_dir.resolve()


def test_adapter_uses_selected_provider_and_plugin_image_helpers(tmp_path: Path, monkeypatch):
    calls: dict[str, object] = {}

    class FakeProvider:
        def describe_image(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
            calls["describe"] = (image_bytes, mime_type, prompt)
            return "cloud result"

    class FakeRegistry:
        @classmethod
        def get(cls, provider_id: str, **kwargs):
            calls["provider"] = (provider_id, kwargs)
            return FakeProvider()

    config = SimpleNamespace(
        use_cloud_api=True,
        vision_provider="gemini",
        vision_api_key="secret",
        vision_base_url="https://vision.example",
        vision_model="gemini-vision",
        max_image_size_mb=4.0,
    )
    modules = {
        "plugins.cloud_vision.plugin": SimpleNamespace(),
        "plugins.cloud_vision.config_model": SimpleNamespace(
            default_config_path=lambda root: root / "config.json",
            load_config=lambda path: config,
        ),
        "plugins.cloud_vision.image_utils": SimpleNamespace(
            compress_if_needed=lambda image, limit: b"compressed",
            detect_mime_type=lambda image: "image/jpeg",
        ),
        "plugins.cloud_vision.vision_provider": SimpleNamespace(
            VisionProviderRegistry=FakeRegistry,
        ),
    }
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.installed_cloud_vision_directory",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.cloud_vision_data_directory",
        lambda: tmp_path / "data",
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter._import_plugin_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.ensure_plugins_namespace_on_syspath",
        lambda: None,
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.ensure_plugin_site_packages_on_syspath",
        lambda: None,
    )

    result = CloudVisionAdapter().describe(b"original", "inspect this")

    assert result == "cloud result"
    assert calls["provider"] == (
        "gemini",
        {
            "api_key": "secret",
            "base_url": "https://vision.example",
            "model": "gemini-vision",
        },
    )
    assert calls["describe"] == (b"compressed", "image/jpeg", "inspect this")


def test_adapter_rejects_disabled_cloud_api(tmp_path: Path, monkeypatch):
    modules = {
        "plugins.cloud_vision.plugin": SimpleNamespace(),
        "plugins.cloud_vision.config_model": SimpleNamespace(
            default_config_path=lambda root: root / "config.json",
            load_config=lambda path: SimpleNamespace(use_cloud_api=False),
        ),
        "plugins.cloud_vision.image_utils": SimpleNamespace(),
        "plugins.cloud_vision.vision_provider": SimpleNamespace(),
    }
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.installed_cloud_vision_directory",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter._import_plugin_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.ensure_plugins_namespace_on_syspath",
        lambda: None,
    )
    monkeypatch.setattr(
        "ai.vision.cloud_vision_adapter.ensure_plugin_site_packages_on_syspath",
        lambda: None,
    )

    with pytest.raises(CloudVisionPluginUnavailable, match="disabled"):
        CloudVisionAdapter()
