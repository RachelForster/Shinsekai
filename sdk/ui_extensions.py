"""Declarative workspace UI extension contracts and locale helpers for plugins."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sdk.lang import SUPPORTED_LANGS, LocaleCode
from sdk.path_utils import resolve_regular_path, safe_child_path

if TYPE_CHECKING:
    from sdk.types import FrontendChatUIContribution, FrontendConfigAction, FrontendPageContribution

__all__ = [
    "FrontendActionContext",
    "FrontendSectionContext",
    "FrontendSectionContribution",
    "PLUGIN_ACTION_SLOTS",
    "PLUGIN_CHAT_ACTION_SLOTS",
    "PLUGIN_SECTION_PAGE_SLOTS",
    "PLUGIN_UI_ICONS",
    "PLUGIN_WORKSPACE_ACTION_SLOTS",
    "load_plugin_locales",
    "validate_frontend_action_contribution",
    "validate_frontend_page_contribution",
    "validate_frontend_section_contribution",
]

PLUGIN_UI_ICONS: frozenset[str] = frozenset(
    {
        "book",
        "bot",
        "brush",
        "database",
        "file",
        "gamepad",
        "globe",
        "image",
        "info",
        "layers",
        "play",
        "puzzle",
        "settings",
        "sliders",
        "smartphone",
        "sparkles",
        "terminal",
        "wand",
        "wrench",
    }
)

PLUGIN_CHAT_ACTION_SLOTS: frozenset[str] = frozenset(
    {
        "chat-dialog-actions",
        "chat-output",
        "chat-toolbar",
        "chat-top-toolbar",
        "chat-workspace-actions",
    }
)

PLUGIN_WORKSPACE_ACTION_SLOTS: frozenset[str] = frozenset(
    {
        "app-topbar-actions",
        "character-header-actions",
        "api-header-actions",
        "background-header-actions",
        "effect-header-actions",
        "system-header-actions",
        "template-header-actions",
    }
)

PLUGIN_ACTION_SLOTS: frozenset[str] = (
    PLUGIN_CHAT_ACTION_SLOTS | PLUGIN_WORKSPACE_ACTION_SLOTS
)

PLUGIN_SECTION_PAGE_SLOTS: dict[str, frozenset[str]] = {
    "character": frozenset({"body", "top-grid"}),
    "api": frozenset({"body"}),
    "background": frozenset({"body"}),
    "effect": frozenset({"body"}),
    "system": frozenset({"body"}),
    "template": frozenset({"main", "sidebar"}),
}

PLUGIN_SECTION_PAGE_IDS: frozenset[str] = frozenset(PLUGIN_SECTION_PAGE_SLOTS)


@dataclass(frozen=True)
class FrontendActionContext:
    """Host context passed when a plugin UI action callback runs."""

    slot: str
    page: str = ""
    entity_type: str = ""
    entity_id: str = ""
    locale: LocaleCode = "zh_CN"
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FrontendSectionContext:
    """Host context passed when a plugin Section loads, saves, or triggers an action."""

    page: str
    slot: str
    entity_type: str = ""
    entity_id: str = ""
    locale: LocaleCode = "zh_CN"
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FrontendSectionContribution:
    """Declarative section injected into an existing host management or template page."""

    section_id: str
    page: Literal["character", "api", "background", "effect", "system", "template"]
    title: str
    renderer: Literal["schema", "iframe"] = "schema"
    slot: str = "body"
    description: str = ""
    nav_label: str = ""
    order: float = 100.0
    schema: list[dict[str, Any]] = field(default_factory=list)
    load_values: Callable[..., Mapping[str, Any]] | None = None
    save_values: Callable[..., Any] | None = None
    actions: list["FrontendConfigAction"] = field(default_factory=list)
    page_id: str = ""
    min_height: int = 160
    max_height: int = 960
    i18n: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    plugin_id: str | None = None
    plugin_version: str | None = None


def load_plugin_locales(directory: str | os.PathLike[str]) -> dict[str, dict[str, Any]]:
    """Load optional ``zh_CN.json``, ``en.json``, and ``ja.json`` files from a directory."""
    root = resolve_regular_path(directory)
    if not root.is_dir():
        return {}
    locales: dict[str, dict[str, Any]] = {}
    for code in SUPPORTED_LANGS:
        candidate = safe_child_path(root, f"{code}.json")
        if not candidate.is_file():
            continue
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            locales[code] = parsed
    return locales


def _require_identifier(value: object, *, label: str, max_len: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if len(cleaned) > max_len:
        raise ValueError(f"{label} cannot exceed {max_len} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError(f"{label} cannot contain control characters")
    return cleaned


def validate_frontend_page_contribution(
    contribution: "FrontendPageContribution",
    max_id_len: int,
) -> "FrontendPageContribution":
    clean_id = _require_identifier(
        getattr(contribution, "page_id", ""),
        label="FrontendPageContribution.page_id",
        max_len=max_id_len,
    )
    clean_icon = str(getattr(contribution, "nav_icon", "puzzle") or "puzzle").strip()
    if clean_icon not in PLUGIN_UI_ICONS:
        clean_icon = "puzzle"
    return replace(contribution, page_id=clean_id, nav_icon=clean_icon)


def validate_frontend_action_contribution(
    contribution: "FrontendChatUIContribution",
    max_id_len: int,
) -> "FrontendChatUIContribution":
    if contribution.slot not in PLUGIN_ACTION_SLOTS:
        raise ValueError(f"Unsupported frontend UI slot: {contribution.slot}")
    if not str(contribution.contribution_id or "").strip() or not str(contribution.title or "").strip():
        raise ValueError("FrontendChatUIContribution requires a non-empty id and title")
    clean_id = _require_identifier(
        contribution.contribution_id,
        label="FrontendChatUIContribution.contribution_id",
        max_len=max_id_len,
    )
    if contribution.presentation not in {"button", "icon-only"}:
        raise ValueError(
            f"Unsupported frontend UI presentation: {contribution.presentation}"
        )
    if isinstance(contribution.action, Mapping):
        action_type = str(contribution.action.get("type") or "").strip()
        page_id = str(
            contribution.action.get("page_id")
            or contribution.action.get("pageId")
            or ""
        ).strip()
        if action_type != "open-plugin-page" or not page_id:
            raise ValueError(
                "FrontendChatUIContribution open-plugin-page action requires a non-empty page_id"
            )
        _require_identifier(
            page_id,
            label="FrontendChatUIContribution.page_id",
            max_len=max_id_len,
        )
    return replace(contribution, contribution_id=clean_id)


def validate_frontend_section_contribution(
    contribution: FrontendSectionContribution,
    max_id_len: int,
) -> FrontendSectionContribution:
    clean_id = _require_identifier(
        contribution.section_id,
        label="FrontendSectionContribution.section_id",
        max_len=max_id_len,
    )
    if not str(contribution.title or "").strip():
        raise ValueError("FrontendSectionContribution requires a non-empty title")
    page = str(contribution.page or "").strip()
    if page not in PLUGIN_SECTION_PAGE_SLOTS:
        raise ValueError(f"Unsupported frontend section page: {page}")
    slot = str(contribution.slot or "").strip() or (
        "main" if page == "template" else "body"
    )
    if page == "template" and slot == "body":
        slot = "main"
    if slot not in PLUGIN_SECTION_PAGE_SLOTS[page]:
        raise ValueError(f"Unsupported slot {slot!r} for section page {page!r}")
    renderer = str(contribution.renderer or "schema").strip()
    if renderer not in {"schema", "iframe"}:
        raise ValueError(f"Unsupported frontend section renderer: {renderer}")
    if renderer == "iframe":
        clean_page_id = _require_identifier(
            contribution.page_id,
            label="FrontendSectionContribution.page_id",
            max_len=max_id_len,
        )
    else:
        clean_page_id = str(contribution.page_id or "").strip()
        if not callable(contribution.load_values):
            raise ValueError(
                "Schema FrontendSectionContribution requires a callable load_values"
            )
        if not isinstance(contribution.schema, list):
            raise ValueError("Schema FrontendSectionContribution requires a list schema")
    min_h = max(80, min(int(contribution.min_height or 160), 1200))
    max_h = max(min_h, min(int(contribution.max_height or 960), 1600))
    return replace(
        contribution,
        section_id=clean_id,
        slot=slot,
        page_id=clean_page_id,
        min_height=min_h,
        max_height=max_h,
    )
