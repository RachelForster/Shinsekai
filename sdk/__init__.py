"""
SDK for Easy AI Desktop Assistant plugins.

- :class:`~sdk.plugin.PluginBase` — minimal lifecycle/meta plugin contract.
- :class:`sdk.manager.PluginManager` — load manifests, instantiate, aggregate.
- :class:`~sdk.register.PluginCapabilityRegistry` — capabilities passed to :meth:`~sdk.plugin.PluginBase.initialize` (alias ``PluginRegister``).
- :class:`~sdk.register.PluginDiscoveryRegistry` — manifest / class discovery before instantiation.
- :mod:`sdk.adapters` — abstract :class:`~sdk.adapters.LLMAdapter`, :class:`~sdk.adapters.TTSAdapter`, :class:`~sdk.adapters.ASRAdapter`, :class:`~sdk.adapters.T2IAdapter`.
- :func:`~sdk.tool_registry.tool` — declare LLM tools without touching :class:`~llm.tools.tool_manager.ToolManager`; host calls :func:`~sdk.tool_registry.apply_registered_tools` during startup.
- :class:`~sdk.plugin_host_context.PluginHostContext` / :class:`~sdk.plugin_host_context.PluginSettingsUIContext` — read-only host snapshots for plugins (no API keys or save APIs).
- Contribution dataclasses in :mod:`sdk.types`.
"""

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext, PluginSettingsUIContext
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

from sdk.adapters import (
    ASRAdapter,
    LLMAdapter,
    T2IAdapter,
    TTSAdapter,
    TranscriptionCallback,
)
from sdk.tool_registry import (
    apply_registered_tools,
    iter_registered_tools,
    registered_tool_entries,
    tool,
)

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
