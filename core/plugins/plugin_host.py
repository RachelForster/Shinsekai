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
from typing import TYPE_CHECKING, Any, Callable, List, Optional

import yaml

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
        from sdk.tool_registry import apply_registered_tools

        tm = ToolManager()
        apply_registered_tools(tm)
        mgr.apply_llm_tools(tm)
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


def read_plugin_manifest_items(path: Path | None = None) -> list[dict[str, Any]]:
    """
    Return manifest rows as mutable dicts (shallow copy each), preserving list order.
    Only includes dict items with a non-empty string ``entry``.
    """
    p = path if path is not None else _MANIFEST
    if not p.is_file():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to parse plugin manifest %s", p)
        return []
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry")
        if not isinstance(entry, str) or not entry.strip():
            continue
        out.append(dict(item))
    return out


def write_plugin_manifest_items(items: list[dict[str, Any]], path: Path | None = None) -> None:
    """Overwrite manifest with ``items`` (YAML list of mappings)."""
    p = path if path is not None else _MANIFEST
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        items,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    p.write_text(text, encoding="utf-8")


def set_plugin_manifest_enabled(entry: str, enabled: bool, path: Path | None = None) -> bool:
    """
    Set ``enabled`` on the manifest row whose ``entry`` matches (strip-wise).
    Returns True if a row was updated and the file was written.
    """
    items = read_plugin_manifest_items(path)
    norm = entry.strip()
    changed = False
    for item in items:
        e = item.get("entry")
        if isinstance(e, str) and e.strip() == norm:
            item["enabled"] = bool(enabled)
            changed = True
            break
    if changed:
        write_plugin_manifest_items(items, path)
    return changed


def normalize_manifest_entry(entry: str) -> str:
    """
    Registry rows often omit the repo-local package root; downloaded plugins live under
    ``plugins/``, so ensure ``entry`` uses the ``plugins.`` module prefix when absent.
    """
    norm = entry.strip()
    if not norm:
        return norm
    if norm.startswith("plugins."):
        return norm
    return f"plugins.{norm}"


def append_plugin_manifest_entry_if_missing(
    entry: str,
    *,
    enabled: bool = True,
    path: Path | None = None,
) -> str:
    """
    Append ``- entry: …`` row if not already present (strip-wise match on entry).

    ``entry`` is normalized with :func:`normalize_manifest_entry` (``plugins.`` prefix).

    Returns ``"added"`` | ``"exists"`` | ``"empty"``.
    """
    norm = normalize_manifest_entry(entry)
    if not norm:
        return "empty"
    items = read_plugin_manifest_items(path)
    for item in items:
        e = item.get("entry")
        if isinstance(e, str) and e.strip() == norm:
            return "exists"
    items.append({"entry": norm, "enabled": bool(enabled)})
    write_plugin_manifest_items(items, path)
    return "added"
