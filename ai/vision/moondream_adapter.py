"""Compatibility facade re-exporting Moondream vision adapter and helpers."""

from __future__ import annotations

from ai.vision.adapters.moondream import (
    MOONDREAM_MODEL_ASSET,
    MOONDREAM_PLUGIN_ENTRY,
    MOONDREAM_PLUGIN_ID,
    MoondreamPluginUnavailable,
    MoondreamVisionAdapter,
    installed_moondream_directory,
    moondream_model_cached,
)

__all__ = [
    "MOONDREAM_MODEL_ASSET",
    "MOONDREAM_PLUGIN_ENTRY",
    "MOONDREAM_PLUGIN_ID",
    "MoondreamPluginUnavailable",
    "MoondreamVisionAdapter",
    "installed_moondream_directory",
    "moondream_model_cached",
]
