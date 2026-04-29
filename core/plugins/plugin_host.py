"""
Host integration for :mod:`sdk` plugins: load manifest, merge factories/tools/handlers,
and expose contributions for Settings / Tools / Chat UI.

Call :func:`ensure_plugins_loaded` once per process after :class:`~config.config_manager.ConfigManager`
is available (``main_sprite`` and/or Settings UI). Safe to call multiple times (idempotent).
"""

from __future__ import annotations

import logging
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Callable, List, Optional

from config.config_manager import ConfigManager
from core.messaging.message import UserInputMessage
from llm.llm_manager import LLMAdapterFactory
from llm.tools.tool_manager import ToolManager
from sdk.manager import PluginManager
from tts.tts_manager import TTSAdapterFactory

if TYPE_CHECKING:
    from core.handlers.handler_registry import MessageHandler, UIOutputMessageHandler
    from sdk.types import (
        ChatUIContribution,
        SettingsUIContribution,
        ToolsTabContribution,
    )
    from ui.settings_ui.context import SettingsUIContext

logger = logging.getLogger(__name__)

_MANIFEST = Path("data/config/plugins.yaml")
_loaded: bool = False
_plugin_manager: PluginManager | None = None
_plugin_tts_handlers: List["MessageHandler"] = []
_plugin_ui_handlers: List["UIOutputMessageHandler"] = []


def get_plugin_manager() -> PluginManager | None:
    return _plugin_manager


def get_plugin_tts_handlers() -> List["MessageHandler"]:
    return list(_plugin_tts_handlers)


def get_plugin_ui_handlers() -> List["UIOutputMessageHandler"]:
    return list(_plugin_ui_handlers)


def ensure_plugins_loaded(config: ConfigManager | None = None) -> PluginManager | None:
    """
    Load ``data/config/plugins.yaml`` if present, instantiate plugins, merge LLM/TTS
    provider tables, register tools on the global ToolManager, and cache message handlers
    for :mod:`core.handlers.handler_registry`.
    """
    global _loaded, _plugin_manager, _plugin_tts_handlers, _plugin_ui_handlers
    if _loaded:
        return _plugin_manager

    mgr = PluginManager()
    if _MANIFEST.is_file():
        try:
            mgr.load_manifest_file(_MANIFEST)
        except Exception:
            logger.exception("Failed to load plugin manifest %s", _MANIFEST)
    mgr.instantiate_all()
    cfg = config if config is not None else ConfigManager()
    mgr.load_own_config_all(app_config=cfg)
    try:
        mgr.apply_llm_providers(LLMAdapterFactory._adapters)
    except Exception:
        logger.exception("apply_llm_providers failed")
    try:
        mgr.apply_tts_providers(TTSAdapterFactory._adapters)
    except Exception:
        logger.exception("apply_tts_providers failed")
    try:
        mgr.apply_llm_tools(ToolManager())
    except Exception:
        logger.exception("apply_llm_tools failed")
    try:
        tts, ui = mgr.collect_message_handlers()
        _plugin_tts_handlers = tts
        _plugin_ui_handlers = ui
    except Exception:
        logger.exception("collect_message_handlers failed")
        _plugin_tts_handlers = []
        _plugin_ui_handlers = []

    _plugin_manager = mgr
    _loaded = True
    return _plugin_manager


def wire_user_input_plugins(user_input_queue: Queue) -> Callable[[str], None]:
    """
    Build the user-input pipeline (plugin processors) and return ``emit_user_text``
    for code that registers hooks via :meth:`sdk.register.PluginCapabilityRegistry.register_user_input_trigger`
    or :meth:`~sdk.register.PluginCapabilityRegistry.register_user_input_processor` inside
    :meth:`sdk.plugin.PluginBase.initialize`.

    The returned callable runs processors then enqueues :class:`~core.messaging.message.UserInputMessage`.
    """
    mgr = _plugin_manager
    processors: list[Callable[[str], str | None]] = []

    def emit_user_text(text: str) -> None:
        t = text
        for proc in processors:
            try:
                out = proc(t)
            except Exception:
                logger.exception("user_input processor failed")
                return
            if out is None:
                return
            t = out
        user_input_queue.put(UserInputMessage(text=t))

    if mgr is not None:
        try:
            mgr.wire_user_input(emit_user_text, processors)
        except Exception:
            logger.exception("wire_user_input failed")
    return emit_user_text


def collect_settings_contributions() -> List["SettingsUIContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_settings_contributions()
    except Exception:
        logger.exception("collect_settings_contributions failed")
        return []


def collect_tools_tab_contributions() -> List["ToolsTabContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_tools_tab_contributions()
    except Exception:
        logger.exception("collect_tools_tab_contributions failed")
        return []


def collect_chat_ui_contributions() -> List["ChatUIContribution"]:
    mgr = _plugin_manager
    if mgr is None:
        return []
    try:
        return mgr.collect_chat_ui_contributions()
    except Exception:
        logger.exception("collect_chat_ui_contributions failed")
        return []
