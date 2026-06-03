"""
SDK for Easy AI Desktop Assistant plugins.

Developer CLI (run from this repository root)::

    python -m sdk.cli --help

Heavy imports (Qt, managers, …) load lazily so ``python -m sdk.cli`` works in
minimal environments. Use explicit submodule imports when possible, e.g.
``from sdk.plugin import PluginBase``.

Quick reference
---------------
- :mod:`sdk.messages` — 队列消息模型 (UserInputMessage, LLMDialogMessage, TTSOutputMessage)
- :mod:`sdk.handlers` — 抽象处理器基类 (MessageHandler, UIOutputMessageHandler)
- :mod:`sdk.adapters` — 适配器抽象 (LLMAdapter, ASRAdapter, TTSAdapter, T2IAdapter)
- :mod:`sdk.plugin` — 插件入口 (PluginBase)
- :mod:`sdk.types` — 贡献声明 (SettingsUIContribution, ToolsTabContribution, ChatUIContribution)
- :mod:`sdk.tool_registry` — LLM 工具注册 (@tool 装饰器)
- :mod:`sdk.register` — 能力注册表 (PluginCapabilityRegistry)
- :mod:`sdk.manager` — 插件管理器 (PluginManager)
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "apply_registered_tools",
    "ASRAdapter",
    "ChatUIContribution",
    "ChatUIContext",
    "ChatOutputContract",
    "FieldPatch",
    "FrontendConfigAction",
    "FrontendConfigContribution",
    "FrontendPageContribution",
    "get_chat_ui_context",
    "iter_registered_tools",
    "LLMAdapter",
    "LLMDialogMessage",
    "MessageHandler",
    "OutputContractPatch",
    "OutputFieldSpec",
    "PluginBase",
    "PluginCapabilityRegistry",
    "PluginDescriptor",
    "PluginDiscoveryRegistry",
    "PluginHostContext",
    "PluginManager",
    "PluginRegister",
    "PluginSettingsUIContext",
    "registered_tool_entries",
    "RequirementPatch",
    "RequirementSpec",
    "SettingsUIContribution",
    "get_logger",
    "log_context",
    "new_log_id",
    "stopwatch",
    "T2IAdapter",
    "TTSAdapter",
    "TTSOutputMessage",
    "tool",
    "ToolsTabContribution",
    "TranscriptionCallback",
    "UIOutputMessageHandler",
    "UserInputMessage",
    "WorkflowContribution",
    "normalize_lang",
    "set_chat_ui_context",
    "SUPPORTED_LANGS",
    "try_get_chat_ui_context",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # ── adapters ──
    "ASRAdapter": ("sdk.adapters", "ASRAdapter"),
    "LLMAdapter": ("sdk.adapters", "LLMAdapter"),
    "T2IAdapter": ("sdk.adapters", "T2IAdapter"),
    "TTSAdapter": ("sdk.adapters", "TTSAdapter"),
    "TranscriptionCallback": ("sdk.adapters", "TranscriptionCallback"),
    # ── messages ──
    "LLMDialogMessage": ("sdk.messages", "LLMDialogMessage"),
    "TTSOutputMessage": ("sdk.messages", "TTSOutputMessage"),
    "UserInputMessage": ("sdk.messages", "UserInputMessage"),
    # ── handlers ──
    "MessageHandler": ("sdk.handlers", "MessageHandler"),
    "UIOutputMessageHandler": ("sdk.handlers", "UIOutputMessageHandler"),
    # ── plugin ──
    "PluginManager": ("sdk.manager", "PluginManager"),
    "PluginBase": ("sdk.plugin", "PluginBase"),
    "PluginHostContext": ("sdk.plugin_host_context", "PluginHostContext"),
    "PluginSettingsUIContext": ("sdk.plugin_host_context", "PluginSettingsUIContext"),
    "PluginCapabilityRegistry": ("sdk.register", "PluginCapabilityRegistry"),
    "PluginDiscoveryRegistry": ("sdk.register", "PluginDiscoveryRegistry"),
    "PluginRegister": ("sdk.register", "PluginRegister"),
    # ── types ──
    "ChatUIContribution": ("sdk.types", "ChatUIContribution"),
    "ChatUIContext": ("sdk.chat_ui_context", "ChatUIContext"),
    "ChatOutputContract": ("sdk.types", "ChatOutputContract"),
    "FieldPatch": ("sdk.types", "FieldPatch"),
    "FrontendConfigAction": ("sdk.types", "FrontendConfigAction"),
    "FrontendConfigContribution": ("sdk.types", "FrontendConfigContribution"),
    "FrontendPageContribution": ("sdk.types", "FrontendPageContribution"),
    "OutputContractPatch": ("sdk.types", "OutputContractPatch"),
    "OutputFieldSpec": ("sdk.types", "OutputFieldSpec"),
    "PluginDescriptor": ("sdk.types", "PluginDescriptor"),
    "RequirementPatch": ("sdk.types", "RequirementPatch"),
    "RequirementSpec": ("sdk.types", "RequirementSpec"),
    "SettingsUIContribution": ("sdk.types", "SettingsUIContribution"),
    "ToolsTabContribution": ("sdk.types", "ToolsTabContribution"),
    "WorkflowContribution": ("sdk.types", "WorkflowContribution"),
    "get_chat_ui_context": ("sdk.chat_ui_context", "get_chat_ui_context"),
    "set_chat_ui_context": ("sdk.chat_ui_context", "set_chat_ui_context"),
    "try_get_chat_ui_context": ("sdk.chat_ui_context", "try_get_chat_ui_context"),
    # ── tools ──
    "apply_registered_tools": ("sdk.tool_registry", "apply_registered_tools"),
    "iter_registered_tools": ("sdk.tool_registry", "iter_registered_tools"),
    "registered_tool_entries": ("sdk.tool_registry", "registered_tool_entries"),
    "tool": ("sdk.tool_registry", "tool"),
    # ── logging ──
    "get_logger": ("sdk.logging", "get_logger"),
    "log_context": ("sdk.logging", "log_context"),
    "new_log_id": ("sdk.logging", "new_log_id"),
    "stopwatch": ("sdk.logging", "stopwatch"),
    # ── lang ──
    "normalize_lang": ("sdk.lang", "normalize_lang"),
    "SUPPORTED_LANGS": ("sdk.lang", "SUPPORTED_LANGS"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        mod_path, attr = _LAZY_EXPORTS[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
