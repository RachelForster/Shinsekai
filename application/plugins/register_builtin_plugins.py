"""Application composition-root registration for built-in host plugins."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sdk.plugin import PluginBase


def get_builtin_plugin_classes() -> tuple[type[PluginBase], ...]:
    """Return built-in plugin classes assembled at the application layer."""
    from ai.llm.template.dialog.renpy_plugin import RenpyDslPlugin

    return (RenpyDslPlugin,)


def register_builtin_dialog_formats() -> None:
    """Register core dialog formats and built-in plugin dialog contributions."""
    from core.messaging.formats.registry import (
        configure_builtin_dialog_formats,
        configure_registered_dialog_formats,
    )
    from sdk.hooks import PluginHookDispatcher
    from sdk.plugin_host_context import PluginHostContext
    from sdk.register import PluginCapabilityRegistry

    configure_builtin_dialog_formats()
    registry = PluginCapabilityRegistry(hook_dispatcher=PluginHookDispatcher())
    host = PluginHostContext.from_config_manager(None)
    for plugin_cls in get_builtin_plugin_classes():
        plugin = plugin_cls()
        if not plugin.enabled:
            continue
        registry.set_settings_ui_plugin_context(plugin.plugin_id, plugin.plugin_version)
        try:
            plugin.initialize(registry, Path("data/plugins") / plugin.plugin_id, host)
        finally:
            registry.clear_settings_ui_plugin_context()
    configure_registered_dialog_formats(registry.dialog_formats)


__all__ = [
    "get_builtin_plugin_classes",
    "register_builtin_dialog_formats",
]
