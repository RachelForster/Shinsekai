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
- :mod:`sdk.chat_ui_theme` — chat_ui 主题 mod 校验/打包 (validate_manifest, pack_theme; CLI: ``python -m sdk.chat_ui_theme``)
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "apply_registered_tools",
    "ASRAdapter",
    "BeforeChatContext",
    "BeforeCompactContext",
    "ChatInitService",
    "ChatUIContribution",
    "ChatUIContext",
    "ChatOutputContract",
    "clear_shutdown_hooks",
    "FieldPatch",
    "FrontendConfigAction",
    "FrontendConfigContribution",
    "FrontendPageContribution",
    "ExceptionInfo",
    "format_llm_exception_message",
    "get_chat_ui_context",
    "HTTP_REASON_UNPAIRED_TOOL_MESSAGES",
    "HttpClientError",
    "HookRegistration",
    "InitChatCancellationToken",
    "InitChatCancelled",
    "InitChatContext",
    "InitChatHookError",
    "InitChatHookFailure",
    "iter_registered_tools",
    "iter_shutdown_hooks",
    "LLMAdapter",
    "LLMDialogMessage",
    "MessageHandler",
    "OutputContractPatch",
    "OutputFieldSpec",
    "PluginBase",
    "PluginCapabilityRegistry",
    "PluginDescriptor",
    "PluginDiscoveryRegistry",
    "PluginHookDispatcher",
    "PluginHookEvent",
    "PluginHostContext",
    "PluginManager",
    "PluginRegister",
    "PluginSettingsUIContext",
    "registered_tool_entries",
    "register_shutdown_hook",
    "RequirementPatch",
    "RequirementSpec",
    "RuntimeDependencyError",
    "ShutdownHookRegistration",
    "ShutdownHookRegistry",
    "classify_exception",
    "SettingsUIContribution",
    "get_logger",
    "handle_main_exception",
    "http_client_error_from_exception",
    "install_main_exception_hook",
    "is_unpaired_tool_messages_error",
    "log_context",
    "llm_http_action_message",
    "missing_module_from_exception",
    "missing_module_from_text",
    "new_log_id",
    "package_for_module",
    "report_main_exception",
    "runtime_dependency_error_from_exception",
    "runtime_dependency_error_from_module",
    "runtime_dependency_error_from_text",
    "show_error_dialog",
    "stopwatch",
    "T2IAdapter",
    "TTSAdapter",
    "TTSOutputMessage",
    "MessageAddedContext",
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
    "BeforeChatContext": ("sdk.hooks", "BeforeChatContext"),
    "BeforeCompactContext": ("sdk.hooks", "BeforeCompactContext"),
    "ChatInitService": ("sdk.chat_init", "ChatInitService"),
    "HookRegistration": ("sdk.hooks", "HookRegistration"),
    "InitChatCancellationToken": ("sdk.chat_init", "InitChatCancellationToken"),
    "InitChatCancelled": ("sdk.chat_init", "InitChatCancelled"),
    "InitChatContext": ("sdk.chat_init", "InitChatContext"),
    "InitChatHookError": ("sdk.hooks", "InitChatHookError"),
    "InitChatHookFailure": ("sdk.hooks", "InitChatHookFailure"),
    "MessageAddedContext": ("sdk.hooks", "MessageAddedContext"),
    "PluginHookDispatcher": ("sdk.hooks", "PluginHookDispatcher"),
    "PluginHookEvent": ("sdk.hooks", "PluginHookEvent"),
    "ShutdownHookRegistration": ("sdk.hooks", "ShutdownHookRegistration"),
    "ShutdownHookRegistry": ("sdk.hooks", "ShutdownHookRegistry"),
    "clear_shutdown_hooks": ("sdk.hooks", "clear_shutdown_hooks"),
    "iter_shutdown_hooks": ("sdk.hooks", "iter_shutdown_hooks"),
    "register_shutdown_hook": ("sdk.hooks", "register_shutdown_hook"),
    # ── types ──
    "ChatUIContribution": ("sdk.types", "ChatUIContribution"),
    "ChatUIContext": ("sdk.chat_ui_context", "ChatUIContext"),
    "ChatOutputContract": ("sdk.types", "ChatOutputContract"),
    "FieldPatch": ("sdk.types", "FieldPatch"),
    "FrontendConfigAction": ("sdk.types", "FrontendConfigAction"),
    "FrontendConfigContribution": ("sdk.types", "FrontendConfigContribution"),
    "FrontendPageContribution": ("sdk.types", "FrontendPageContribution"),
    "ExceptionInfo": ("sdk.exception.types", "ExceptionInfo"),
    "HTTP_REASON_UNPAIRED_TOOL_MESSAGES": ("sdk.exception.types", "HTTP_REASON_UNPAIRED_TOOL_MESSAGES"),
    "OutputContractPatch": ("sdk.types", "OutputContractPatch"),
    "OutputFieldSpec": ("sdk.types", "OutputFieldSpec"),
    "PluginDescriptor": ("sdk.types", "PluginDescriptor"),
    "RequirementPatch": ("sdk.types", "RequirementPatch"),
    "RequirementSpec": ("sdk.types", "RequirementSpec"),
    "RuntimeDependencyError": ("sdk.exception.types", "RuntimeDependencyError"),
    "HttpClientError": ("sdk.exception.types", "HttpClientError"),
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
    "classify_exception": ("sdk.exception.types", "classify_exception"),
    "format_llm_exception_message": ("sdk.exception.presenter", "format_llm_exception_message"),
    "handle_main_exception": ("sdk.exception.handler", "handle_main_exception"),
    "http_client_error_from_exception": ("sdk.exception.types", "http_client_error_from_exception"),
    "install_main_exception_hook": ("sdk.exception.handler", "install_main_exception_hook"),
    "is_unpaired_tool_messages_error": ("sdk.exception.types", "is_unpaired_tool_messages_error"),
    "log_context": ("sdk.logging", "log_context"),
    "llm_http_action_message": ("sdk.exception.presenter", "llm_http_action_message"),
    "missing_module_from_exception": ("sdk.exception.types", "missing_module_from_exception"),
    "missing_module_from_text": ("sdk.exception.types", "missing_module_from_text"),
    "new_log_id": ("sdk.logging", "new_log_id"),
    "package_for_module": ("sdk.exception.types", "package_for_module"),
    "report_main_exception": ("sdk.exception.handler", "report_main_exception"),
    "runtime_dependency_error_from_exception": ("sdk.exception.types", "runtime_dependency_error_from_exception"),
    "runtime_dependency_error_from_module": ("sdk.exception.types", "runtime_dependency_error_from_module"),
    "runtime_dependency_error_from_text": ("sdk.exception.types", "runtime_dependency_error_from_text"),
    "show_error_dialog": ("sdk.exception.handler", "show_error_dialog"),
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
