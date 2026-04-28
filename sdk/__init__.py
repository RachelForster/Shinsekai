"""
SDK for Easy AI Desktop Assistant plugins.

- :class:`~sdk.plugin.ShinsekaiPlugin` — abstract base with all extension hooks.
- :class:`sdk.manager.PluginManager` — load manifests, instantiate, aggregate.
- Contribution dataclasses in :mod:`sdk.types`.
"""

from sdk.manager import PluginManager
from sdk.plugin import ShinsekaiPlugin
from sdk.types import (
    DesktopUIContribution,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
)

__all__ = [
    "DesktopUIContribution",
    "PluginDescriptor",
    "PluginManager",
    "SettingsUIContribution",
    "ShinsekaiPlugin",
    "ToolsTabContribution",
]
