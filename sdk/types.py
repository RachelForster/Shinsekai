"""
Shared types for plugin contributions (settings/tools/Chat UI).

These dataclasses describe *what* a plugin wants to add. The host application
is responsible for actually inserting widgets into sidebars, tab bars, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtWidgets import QWidget

from sdk.plugin_host_context import PluginSettingsUIContext
from ui.chat_ui.context import ChatUIContext

__all__ = [
    "ChatUIContext",
    "ChatUIContribution",
    "PluginDescriptor",
    "PluginSettingsUIContext",
    "QWidget",
    "SettingsUIContribution",
    "ToolsTabContribution",
]


@dataclass(frozen=True)
class SettingsUIContribution:
    """
    One extra page/section for the PySide6 settings window.

    ``build`` receives :class:`~sdk.plugin_host_context.PluginSettingsUIContext` only
    (read-only app snapshot + paths / name lists). It does **not** receive
    :class:`~config.config_manager.ConfigManager` or full :class:`~ui.settings_ui.context.SettingsUIContext`.

    ``nav_label`` is shown on the sidebar (or host may map it through i18n).
    ``page_id`` must be unique across all plugins (and ideally across the app).
    """

    page_id: str
    nav_label: str
    build: Callable[[PluginSettingsUIContext], QWidget]
    order: float = 100.0


@dataclass(frozen=True)
class ToolsTabContribution:
    """
    An additional tab inside **Settings → Tools** (or host-defined tools area).

    ``build`` receives :class:`~sdk.plugin_host_context.PluginSettingsUIContext` only
    (same restricted surface as settings pages). ``tab_id`` must be unique.
    """

    tab_id: str
    title: str
    build: Callable[[PluginSettingsUIContext], QWidget]
    order: float = 100.0


@dataclass(frozen=True)
class ChatUIContribution:
    """
    Extra widgets for the Chat UI window (:class:`~ui.chat_ui.chat_ui.ChatUIWindow`).

    ``placement`` is a hint: e.g. ``"toolbar"``, ``"overlay"``, ``"input_row"``.
    The host decides how to interpret placements that it supports.

    ``build`` receives :class:`~ui.chat_ui.context.ChatUIContext` for safe state access;
    the host may also pass a window reference if the plugin documents it.
    """

    widget_id: str
    placement: str
    build: Callable[[ChatUIContext], QWidget]
    order: float = 100.0


@dataclass
class PluginDescriptor:
    """
    Lightweight metadata for discovery and logging.

    ``entry``: dotted path ``package.module:PluginClass``, or importable module
    name that exposes a ``Plugin`` class.
    """

    entry: str
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
