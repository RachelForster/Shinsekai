"""
SDK for Easy AI Desktop Assistant plugins.

Developer CLI (run from this repository root)::

    python -m sdk.cli --help

Heavy imports (Qt, managers, …) load lazily so ``python -m sdk.cli`` works in
minimal environments. Use explicit submodule imports when possible, e.g.
``from sdk.plugin import PluginBase``.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "apply_registered_tools",
    "ASRAdapter",
    "ChatUIContribution",
    "iter_registered_tools",
    "LLMAdapter",
    "PluginCapabilityRegistry",
    "PluginDescriptor",
    "PluginDiscoveryRegistry",
    "PluginHostContext",
    "PluginManager",
    "PluginRegister",
    "PluginSettingsUIContext",
    "registered_tool_entries",
    "SettingsUIContribution",
    "PluginBase",
    "T2IAdapter",
    "tool",
    "ToolsTabContribution",
    "TranscriptionCallback",
    "TTSAdapter",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "PluginManager": ("sdk.manager", "PluginManager"),
    "PluginBase": ("sdk.plugin", "PluginBase"),
    "PluginHostContext": ("sdk.plugin_host_context", "PluginHostContext"),
    "PluginSettingsUIContext": ("sdk.plugin_host_context", "PluginSettingsUIContext"),
    "PluginCapabilityRegistry": ("sdk.register", "PluginCapabilityRegistry"),
    "PluginDiscoveryRegistry": ("sdk.register", "PluginDiscoveryRegistry"),
    "PluginRegister": ("sdk.register", "PluginRegister"),
    "ChatUIContribution": ("sdk.types", "ChatUIContribution"),
    "PluginDescriptor": ("sdk.types", "PluginDescriptor"),
    "SettingsUIContribution": ("sdk.types", "SettingsUIContribution"),
    "ToolsTabContribution": ("sdk.types", "ToolsTabContribution"),
    "ASRAdapter": ("sdk.adapters", "ASRAdapter"),
    "LLMAdapter": ("sdk.adapters", "LLMAdapter"),
    "T2IAdapter": ("sdk.adapters", "T2IAdapter"),
    "TTSAdapter": ("sdk.adapters", "TTSAdapter"),
    "TranscriptionCallback": ("sdk.adapters", "TranscriptionCallback"),
    "apply_registered_tools": ("sdk.tool_registry", "apply_registered_tools"),
    "iter_registered_tools": ("sdk.tool_registry", "iter_registered_tools"),
    "registered_tool_entries": ("sdk.tool_registry", "registered_tool_entries"),
    "tool": ("sdk.tool_registry", "tool"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        mod_path, attr = _LAZY_EXPORTS[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
