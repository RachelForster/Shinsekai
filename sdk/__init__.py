"""
SDK for Easy AI Desktop Assistant plugins.

- :class:`~sdk.plugin.PluginBase` — minimal lifecycle/meta plugin contract.
- :class:`sdk.manager.PluginManager` — load manifests, instantiate, aggregate.
- :class:`sdk.register.PluginRegister` — on-demand plugin registration center.
- Contribution dataclasses in :mod:`sdk.types`.
"""

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.register import PluginRegister
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
    "PluginBase",
    "PluginRegister",
    "ToolsTabContribution",
]
