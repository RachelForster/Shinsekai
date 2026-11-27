"""Host-bundled built-in plugin registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sdk.plugin import PluginBase

BUILTIN_PLUGIN_CLASSES: tuple[type[PluginBase], ...] = ()


def register_builtin_plugins(manager: Any) -> None:
    """Register host-bundled built-in plugins onto a PluginManager instance."""
    register_fn = getattr(manager, "register_plugin_class", None)
    if not callable(register_fn):
        return
    for plugin_cls in BUILTIN_PLUGIN_CLASSES:
        register_fn(plugin_cls)
