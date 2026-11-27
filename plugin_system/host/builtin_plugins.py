"""Host-bundled built-in plugin registrations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sdk.plugin import PluginBase

BUILTIN_PLUGIN_CLASSES: tuple[type[PluginBase], ...] = ()


def register_builtin_plugins(
    manager: Any,
    *,
    extra_plugins: Iterable[type[PluginBase]] = (),
) -> None:
    """Register host-bundled and caller-supplied built-in plugins onto a PluginManager."""
    register_fn = getattr(manager, "register_plugin_class", None)
    if not callable(register_fn):
        return
    seen: set[type[PluginBase]] = set()
    for plugin_cls in (*BUILTIN_PLUGIN_CLASSES, *extra_plugins):
        if plugin_cls in seen:
            continue
        seen.add(plugin_cls)
        register_fn(plugin_cls)
