"""
Shared types for plugin contributions (settings/tools/Chat UI).

These dataclasses describe *what* a plugin wants to add. The host application
is responsible for actually inserting widgets into sidebars, tab bars, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
else:
    QWidget = Any

if TYPE_CHECKING:
    from sdk.chat_ui_context import ChatUIContext
    from sdk.plugin_host_context import PluginSettingsUIContext
else:
    ChatUIContext = Any
    PluginSettingsUIContext = Any

__all__ = [
    "ChatUIContext",
    "ChatUIContribution",
    "ChatOutputContract",
    "FieldPatch",
    "FrontendConfigContribution",
    "OutputContractPatch",
    "OutputFieldSpec",
    "PluginDescriptor",
    "PluginSettingsUIContext",
    "QWidget",
    "RequirementPatch",
    "RequirementSpec",
    "SettingsUIContribution",
    "ToolsTabContribution",
    "WorkflowContribution",
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

    ``plugin_id`` / ``plugin_version`` are normally injected by the host during
    :meth:`~sdk.plugin.PluginBase.initialize`; plugins may override explicitly when registering.
    """

    page_id: str
    nav_label: str
    build: Callable[[PluginSettingsUIContext], QWidget]
    order: float = 100.0
    plugin_id: str | None = None
    plugin_version: str | None = None


@dataclass(frozen=True)
class ToolsTabContribution:
    """
    An additional tab inside **Settings → Tools** (or host-defined tools area).

    ``build`` receives :class:`~sdk.plugin_host_context.PluginSettingsUIContext` only
    (same restricted surface as settings pages). ``tab_id`` must be unique.

    ``plugin_id`` / ``plugin_version`` are injected by the host during
    :meth:`~sdk.plugin.PluginBase.initialize` when omitted.
    """

    tab_id: str
    title: str
    build: Callable[[PluginSettingsUIContext], QWidget]
    order: float = 100.0
    plugin_id: str | None = None
    plugin_version: str | None = None


@dataclass(frozen=True)
class FrontendConfigContribution:
    """
    A React-renderable plugin page described by JSON-safe schema and callbacks.

    Unlike :class:`SettingsUIContribution` and :class:`ToolsTabContribution`,
    this contribution does not expose a Qt ``QWidget``. The bridge serializes
    ``schema`` and ``load_values()`` to the frontend, then calls
    ``save_values(values)`` when the user saves.
    """

    page_id: str
    title: str
    schema: list[dict[str, Any]]
    load_values: Callable[[], Mapping[str, Any]]
    save_values: Callable[[Mapping[str, Any]], None]
    kind: Literal["settings", "tools"] = "settings"
    description: str = ""
    restart_hint: str = ""
    order: float = 100.0
    plugin_id: str | None = None
    plugin_version: str | None = None


@dataclass(frozen=True)
class ChatUIContribution:
    """
    Extra widgets for the Chat UI window (:class:`~ui.chat_ui.chat_ui.ChatUIWindow`).

    ``placement`` is a hint: e.g. ``"toolbar"``, ``"overlay"``, ``"input_row"``.
    The host decides how to interpret placements that it supports.

    ``build`` receives :class:`~sdk.chat_ui_context.ChatUIContext` for safe state access
    and event subscription via ``on_*`` callbacks (not raw Qt signals).
    The host may also pass a window reference if the plugin documents it.
    """

    widget_id: str
    placement: str
    build: Callable[[ChatUIContext], QWidget]
    order: float = 100.0
    plugin_id: str | None = None
    plugin_version: str | None = None


@dataclass(frozen=True)
class OutputFieldSpec:
    """One field in an LLM JSON output contract.

    ``key`` should be a simple JSON object member name. ``aliases`` are
    prompt-facing hints for alternative names the LLM may see or produce.
    """

    key: str
    type: str = "string"
    description: str = ""
    required: bool = False
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementSpec:
    """One stable, patchable requirement in an LLM output contract."""

    id: str
    text: str
    order: float = 100.0
    enabled: bool = True


@dataclass(frozen=True)
class FieldPatch:
    """Partial override for one output field's prompt-facing contract.

    ``description=None`` keeps the current description. ``description=""`` is
    also treated as keep-current so plugins do not accidentally erase guidance.
    """

    description: str | None = None
    required: bool | None = None
    type: str | None = None
    enum: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class RequirementPatch:
    """Patch operation for a requirement identified by stable id."""

    mode: Literal["append", "prepend", "replace", "remove"]
    text: str = ""


@dataclass(frozen=True)
class OutputContractPatch:
    """
    Local modification to an existing LLM output contract.

    Use this when a plugin wants to reuse an existing workflow but adjust prompt
    requirements or field semantics, such as tightening ``speech`` output rules.
    """

    id: str
    target_contract: str
    priority: float = 100.0
    field_patches: dict[str, FieldPatch] = field(default_factory=dict)
    add_fields: tuple[OutputFieldSpec, ...] = ()
    remove_fields: tuple[str, ...] = ()
    requirement_patches: dict[str, RequirementPatch] = field(default_factory=dict)
    add_requirements: tuple[RequirementSpec, ...] = ()


@dataclass(frozen=True)
class ChatOutputContract:
    """Complete schema contract owned by a workflow."""

    id: str
    json_schema: dict[str, Any]
    requirements: tuple[str, ...] = ()
    target_export: str = "llm.output"
    stream_mode: Literal["json_object", "json_lines", "json_array"] = "json_object"


@dataclass(frozen=True)
class WorkflowContribution:
    """A plugin-provided workflow YAML plus optional LLM output contract."""

    id: str
    name: str
    yaml_path: str
    description: str = ""
    output_contract: ChatOutputContract | None = None


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
