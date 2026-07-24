from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from ai.vision.vision_adapter import VisionAdapter
from core.plugins.plugin_host import infer_plugin_package_directory, read_plugin_manifest_items
from core.plugins.plugin_requirements_install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)


CLOUD_VISION_PLUGIN_ID = "com.shinsekai.cloud_vision"
CLOUD_VISION_PLUGIN_ENTRY = "plugins.cloud_vision.plugin:CloudVisionPlugin"


class CloudVisionPluginUnavailable(RuntimeError):
    pass


def _import_plugin_module(name: str) -> Any:
    return importlib.import_module(name)


def installed_cloud_vision_directory() -> Path | None:
    """Return the enabled legacy Cloud Vision plugin directory, if installed."""
    for item in read_plugin_manifest_items():
        entry = str(item.get("entry") or "").strip()
        if entry != CLOUD_VISION_PLUGIN_ENTRY or not bool(item.get("enabled", True)):
            continue
        directory = infer_plugin_package_directory(entry)
        if directory is not None and directory.is_dir() and (directory / "plugin.py").is_file():
            return directory.resolve()
    return None


def cloud_vision_data_directory() -> Path:
    """Match the data directory passed to plugins by the default plugin host."""
    return Path("data/plugins") / CLOUD_VISION_PLUGIN_ID


class CloudVisionAdapter(VisionAdapter):
    """Lazy compatibility adapter over the legacy Cloud Vision plugin."""

    def __init__(self) -> None:
        if installed_cloud_vision_directory() is None:
            raise CloudVisionPluginUnavailable("Cloud Vision plugin is not enabled or installed.")

        ensure_plugins_namespace_on_syspath()
        ensure_plugin_site_packages_on_syspath()
        try:
            # Importing the plugin entry registers all bundled provider classes.
            _import_plugin_module("plugins.cloud_vision.plugin")
            config_module = _import_plugin_module("plugins.cloud_vision.config_model")
            image_module = _import_plugin_module("plugins.cloud_vision.image_utils")
            provider_module = _import_plugin_module("plugins.cloud_vision.vision_provider")

            config_path = config_module.default_config_path(cloud_vision_data_directory())
            config: Any = config_module.load_config(config_path)
            if not bool(getattr(config, "use_cloud_api", False)):
                raise CloudVisionPluginUnavailable("Cloud Vision cloud API is disabled.")

            provider_id = str(getattr(config, "vision_provider", "") or "").strip().lower()
            if not provider_id:
                raise CloudVisionPluginUnavailable("Cloud Vision provider is not configured.")

            self._provider = provider_module.VisionProviderRegistry.get(
                provider_id,
                api_key=str(getattr(config, "vision_api_key", "") or ""),
                base_url=str(getattr(config, "vision_base_url", "") or ""),
                model=str(getattr(config, "vision_model", "") or ""),
            )
            self._compress: Callable[[bytes, float], bytes] = image_module.compress_if_needed
            self._detect_mime: Callable[[bytes], str] = image_module.detect_mime_type
            self._max_image_size_mb = float(getattr(config, "max_image_size_mb", 10.0))
        except CloudVisionPluginUnavailable:
            raise
        except (AttributeError, ImportError, OSError, TypeError, ValueError) as exc:
            raise CloudVisionPluginUnavailable(f"Cloud Vision plugin is unavailable: {exc}") from exc

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        try:
            prepared = self._compress(image_bytes, self._max_image_size_mb)
            mime_type = self._detect_mime(prepared)
            return str(self._provider.describe_image(prepared, mime_type, prompt) or "")
        except CloudVisionPluginUnavailable:
            raise
        except Exception as exc:
            raise CloudVisionPluginUnavailable(f"Cloud Vision request failed: {exc}") from exc


def cloud_vision_available() -> bool:
    """Return whether the enabled plugin has a usable cloud-provider configuration."""
    try:
        CloudVisionAdapter()
    except CloudVisionPluginUnavailable:
        return False
    return True
