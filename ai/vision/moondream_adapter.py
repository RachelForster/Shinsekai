from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ai.vision.vision_adapter import VisionAdapter
from core.paths import (
    managed_project_directory,
    project_root,
    require_directory_without_links,
    require_regular_file_without_links,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_path,
)
from plugin_system.host import (
    infer_plugin_package_directory,
    read_plugin_manifest_items,
)
from plugin_system.requirements.install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)


MOONDREAM_PLUGIN_ID = "com.shinsekai.moondream_vision"
MOONDREAM_PLUGIN_ENTRY = "plugins.moondream_vision.plugin:MoondreamVisionPlugin"


class MoondreamPluginUnavailable(RuntimeError):
    pass


def _selected_project_root(root: str | Path | None) -> Path:
    return (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )


def _moondream_config_path(
    config_module: Any,
    runtime_module: Any,
    *,
    root: str | Path | None = None,
) -> Path:
    """Resolve the optional plugin config against one writable project root."""

    active_root = _selected_project_root(root)
    try:
        configured = runtime_module.plugin_config_path()
    except RuntimeError:
        plugin_data = managed_project_directory(
            "data/plugins",
            MOONDREAM_PLUGIN_ID,
            root=active_root,
        )
        configured = config_module.default_config_path(plugin_data)
    return resolve_managed_project_path(configured, root=active_root)


def _bind_plugin_config_paths(
    config: Any,
    *,
    root: str | Path | None = None,
) -> Any:
    """Bind optional plugin paths to the host's authoritative project root."""

    raw_cache_dir = str(getattr(config, "cache_dir", "") or "")
    if raw_cache_dir:
        config.cache_dir = resolve_project_output_path(
            raw_cache_dir,
            root=_selected_project_root(root),
        ).as_posix()
    return config


def installed_moondream_directory(
    *,
    root: str | Path | None = None,
) -> Path | None:
    active_root = _selected_project_root(root)
    for item in read_plugin_manifest_items(root=active_root):
        entry = str(item.get("entry") or "")
        if entry != MOONDREAM_PLUGIN_ENTRY:
            continue
        directory = infer_plugin_package_directory(
            entry,
            root=active_root,
        )
        if directory is None:
            continue
        try:
            directory = require_directory_without_links(
                directory,
                field="Moondream plugin directory",
            )
            require_regular_file_without_links(
                directory / "plugin.py",
                field="Moondream plugin entry",
            )
        except (OSError, RuntimeError, ValueError):
            continue
        return directory
    return None


class MoondreamVisionAdapter(VisionAdapter):
    """Lazy adapter over the optional Moondream Vision plugin."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
    ) -> None:
        active_root = _selected_project_root(root)
        plugin_dir = installed_moondream_directory(root=active_root)
        if plugin_dir is None:
            raise MoondreamPluginUnavailable("Moondream 插件未安装，无法自动标注图片。")

        ensure_plugins_namespace_on_syspath(root=active_root)
        ensure_plugin_site_packages_on_syspath(root=active_root)
        try:
            config_module = importlib.import_module("plugins.moondream_vision.config_model")
            infer_module = importlib.import_module("plugins.moondream_vision.local_infer")
            runtime_module = importlib.import_module("plugins.moondream_vision.runtime")
            config_path = _moondream_config_path(
                config_module,
                runtime_module,
                root=active_root,
            )
            self._config: Any = _bind_plugin_config_paths(
                config_module.load_config(config_path),
                root=active_root,
            )
            self._infer = infer_module.infer_screen_png
        except (ImportError, AttributeError) as exc:
            raise MoondreamPluginUnavailable(f"Moondream 插件不可用：{exc}") from exc

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return str(self._infer(image_bytes, prompt, self._config) or "")
