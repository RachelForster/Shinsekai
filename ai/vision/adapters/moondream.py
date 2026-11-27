"""Optional local Moondream vision plugin adapter."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any

from ai.vision.vision_adapter import VisionAdapter
from core.adapters import builtin_adapter
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot
from plugin_system.host import infer_plugin_package_directory, read_plugin_manifest_items
from plugin_system.requirements.install import (
    ensure_plugin_site_packages_on_syspath,
    ensure_plugins_namespace_on_syspath,
)

MOONDREAM_PLUGIN_ID = "com.shinsekai.moondream_vision"
MOONDREAM_PLUGIN_ENTRY = "plugins.moondream_vision.plugin:MoondreamVisionPlugin"
MOONDREAM_MODEL_ASSET = ModelAssetSpec(
    asset_id="vision.moondream",
    title="Moondream 视觉模型",
    variant="vikhyatk/moondream2",
    repo_id="vikhyatk/moondream2",
    allow_patterns=(
        "*.json",
        "*.py",
        "*.safetensors",
        "*.bin",
        "*.txt",
        "*.model",
    ),
    required_file_groups=(
        ("config.json",),
        ("model.safetensors", "model-*.safetensors", "pytorch_model.bin", "pytorch_model-*.bin"),
        ("*.py",),
    ),
    enforce_allow_patterns=False,
)


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


def moondream_model_cached() -> bool:
    return find_cached_huggingface_snapshot(MOONDREAM_MODEL_ASSET) is not None


_DEFAULT_INSTALLED_MOONDREAM_DIRECTORY = installed_moondream_directory
_DEFAULT_MOONDREAM_MODEL_CACHED = moondream_model_cached


def _resolve_moondream_directory() -> Path | None:
    compat = sys.modules.get("ai.vision.moondream_adapter")
    patched = getattr(
        compat, "installed_moondream_directory", _DEFAULT_INSTALLED_MOONDREAM_DIRECTORY
    )
    if patched is not _DEFAULT_INSTALLED_MOONDREAM_DIRECTORY:
        return patched()
    return installed_moondream_directory()


def _is_moondream_model_cached() -> bool:
    compat = sys.modules.get("ai.vision.moondream_adapter")
    patched = getattr(compat, "moondream_model_cached", _DEFAULT_MOONDREAM_MODEL_CACHED)
    if patched is not _DEFAULT_MOONDREAM_MODEL_CACHED:
        return bool(patched())
    return moondream_model_cached()


@builtin_adapter("moondream", label="Moondream（本地）", order=60)
class MoondreamVisionAdapter(VisionAdapter):
    """Lazy adapter over the optional Moondream Vision plugin."""

    def __init__(self) -> None:
        plugin_dir = _resolve_moondream_directory()
        if plugin_dir is None:
            raise MoondreamPluginUnavailable("Moondream 插件未安装，无法自动标注图片。")
        if not _is_moondream_model_cached():
            raise MoondreamPluginUnavailable(
                "Moondream 模型尚未下载，请先在 AI 服务的视觉配置中下载模型。"
            )

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
