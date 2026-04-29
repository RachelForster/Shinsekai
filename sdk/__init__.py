"""
SDK for Easy AI Desktop Assistant plugins.

- :class:`~sdk.plugin.PluginBase` — minimal lifecycle/meta plugin contract.
- :class:`sdk.manager.PluginManager` — load manifests, instantiate, aggregate.
- :class:`~sdk.register.PluginCapabilityRegistry` — capabilities passed to :meth:`~sdk.plugin.PluginBase.initialize` (alias ``PluginRegister``).
- :class:`~sdk.register.PluginDiscoveryRegistry` — manifest / class discovery before instantiation.
- Contribution dataclasses in :mod:`sdk.types`.
"""

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.register import (
    PluginCapabilityRegistry,
    PluginDiscoveryRegistry,
    PluginRegister,
)
from sdk.types import (
    ChatUIContribution,
    PluginDescriptor,
    SettingsUIContribution,
    ToolsTabContribution,
)

__all__ = [
    "ChatUIContribution",
    "PluginCapabilityRegistry",
    "PluginDescriptor",
    "PluginDiscoveryRegistry",
    "PluginManager",
    "PluginRegister",
    "SettingsUIContribution",
    "PluginBase",
    "ToolsTabContribution",
]
