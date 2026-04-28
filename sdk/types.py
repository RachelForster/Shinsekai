"""
Shared types for plugin contributions (settings/tools/desktop UI).

These dataclasses describe *what* a plugin wants to add. The host application
is responsible for actually inserting widgets into sidebars, tab bars, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from ui.desktop_ui import DesktopAssistantWindow
    from ui.settings_ui.context import SettingsUIContext


@dataclass(frozen=True)
class SettingsUIContribution:
    """
    One extra page/section for the PyQt settings window.

    ``build`` receives the same ``SettingsUIContext`` as built-in tabs
    (config, characters, template generator, …). Return a QWidget tree rooted
    at ``parent=None``; the host will reparent it into the stacked layout or
    a scroll area.

    ``nav_label`` is shown on the sidebar (or host may map it through i18n).
    ``page_id`` must be unique across all plugins (and ideally across the app).
    """

    page_id: str
    nav_label: str
    build: Callable[[SettingsUIContext], QWidget]
    order: float = 100.0


@dataclass(frozen=True)
class ToolsTabContribution:
    """
    An additional tab inside **Settings → Tools** (or host-defined tools area).

    ``build`` builds the tab body. ``tab_id`` must be unique.
    """

    tab_id: str
    title: str
    build: Callable[[SettingsUIContext], QWidget]
    order: float = 100.0


@dataclass(frozen=True)
class DesktopUIContribution:
    """
    Extra widgets for the desktop assistant window (``DesktopAssistantWindow``).

    ``placement`` is a hint: e.g. ``"toolbar"``, ``"overlay"``, ``"input_row"``.
    The host decides how to interpret placements that it supports.

    ``build`` receives the live desktop window so you can connect signals
    (e.g. ``message_submitted``) or read layout state.
    """

    widget_id: str
    placement: str
    build: Callable[[DesktopAssistantWindow], QWidget]
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
