from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ai.vision.vision_adapter import VisionAdapter
from core.plugins.plugin_host import infer_plugin_package_directory, read_plugin_manifest_items
from core.plugins.plugin_requirements_install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)


MOONDREAM_PLUGIN_ID = "com.shinsekai.moondream_vision"
MOONDREAM_PLUGIN_ENTRY = "plugins.moondream_vision.plugin:MoondreamVisionPlugin"


class MoondreamPluginUnavailable(RuntimeError):
    pass


def installed_moondream_directory() -> Path | None:
    for item in read_plugin_manifest_items():
        entry = str(item.get("entry") or "").strip()
        if entry != MOONDREAM_PLUGIN_ENTRY:
            continue
        directory = infer_plugin_package_directory(entry)
        if directory is not None and directory.is_dir() and (directory / "plugin.py").is_file():
            return directory.resolve()
    return None


class MoondreamVisionAdapter(VisionAdapter):
    """Lazy adapter over the optional Moondream Vision plugin."""

    def __init__(self) -> None:
        plugin_dir = installed_moondream_directory()
        if plugin_dir is None:
            raise MoondreamPluginUnavailable("Moondream 插件未安装，无法自动标注图片。")

        ensure_plugins_namespace_on_syspath()
        ensure_plugin_site_packages_on_syspath()
        try:
            config_module = importlib.import_module("plugins.moondream_vision.config_model")
            infer_module = importlib.import_module("plugins.moondream_vision.local_infer")
            runtime_module = importlib.import_module("plugins.moondream_vision.runtime")
            try:
                config_path = runtime_module.plugin_config_path()
            except RuntimeError:
                config_path = config_module.default_config_path(plugin_dir)
            self._config: Any = config_module.load_config(config_path)
            self._infer = infer_module.infer_screen_png
        except (ImportError, AttributeError) as exc:
            raise MoondreamPluginUnavailable(f"Moondream 插件不可用：{exc}") from exc

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return str(self._infer(image_bytes, prompt, self._config) or "")

