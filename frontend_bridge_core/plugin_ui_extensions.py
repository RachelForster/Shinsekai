"""Bridge serialization and callback dispatch for workspace plugin UI extensions."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from application.plugins.catalog import (
    frontend_chat_ui_contributions,
    frontend_page_contributions,
    frontend_section_contributions,
)
from frontend_bridge_core.i18n_helpers import bind_bridge_state, bridge_error, bridge_tr
from frontend_bridge_core.plugin_ui import (
    _frontend_page_contribution,
    _frontend_page_payload,
    _plugin_ui_detail,
)
from sdk.lang import SUPPORTED_LANGS, LocaleCode, normalize_lang
from sdk.ui_extensions import (
    PLUGIN_ACTION_SLOTS,
    PLUGIN_SECTION_PAGE_SLOTS,
    FrontendActionContext,
    FrontendSectionContext,
)

__all__ = [
    "_frontend_section_payloads",
    "_run_frontend_action_with_context",
    "_run_frontend_section_action",
    "_save_frontend_section_values",
    "_should_inject_host_theme",
    "_sidebar_page_payloads",
]

_ALLOWED_REFRESH_TARGETS = frozenset(
    {
        "agent",
        "api",
        "backgrounds",
        "character-relations",
        "characters",
        "chat",
        "config",
        "effects",
        "novel",
        "plugins",
        "sections",
        "sidebar-pages",
        "story-library",
        "system",
        "templates",
    }
)
_SECTION_PAGE_ALIASES = {
    "backgrounds": "background",
    "characters": "character",
    "effects": "effect",
    "templates": "template",
}
_SUPPORTED_LOCALE_SET = frozenset(SUPPORTED_LANGS)


def _invoke_with_optional_context(
    fn: Callable[..., Any],
    *positional: Any,
    ctx: Any,
) -> Any:
    """Call legacy no-context callbacks or context-aware callbacks transparently."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*positional)
    params = list(sig.parameters.values())
    positional_caps = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    if has_varargs or len(positional_caps) > len(positional):
        return fn(*positional, ctx)
    if "ctx" in sig.parameters:
        return fn(*positional, ctx=ctx)
    if "context" in sig.parameters:
        return fn(*positional, context=ctx)
    return fn(*positional)


def _sanitized_extra(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _sanitized_refresh(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    seen: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name in _ALLOWED_REFRESH_TARGETS and name not in seen:
            seen.append(name)
    return seen


def _sanitized_i18n_message(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        lang = str(key or "").strip()
        if lang in _SUPPORTED_LOCALE_SET and isinstance(val, str) and val.strip():
            out[lang] = val.strip()[:1000]
    return out


def _normalize_callback_response(
    result: Any,
    *,
    default_kind: str = "success",
) -> tuple[str, str, dict[str, str], list[str], dict[str, Any]]:
    if isinstance(result, Mapping):
        kind = str(result.get("kind") or default_kind).strip()
        if kind not in {"error", "info", "success"}:
            kind = default_kind
        message = str(result.get("message") or "").strip()[:1000]
        i18n_message = _sanitized_i18n_message(result.get("i18nMessage"))
        refresh = _sanitized_refresh(result.get("refresh"))
        return kind, message, i18n_message, refresh, dict(result)
    message = str(result or "").strip()[:1000]
    return default_kind, message, {}, [], {}


def _build_section_context(
    page: str,
    slot: str,
    *,
    entity_type: str = "",
    entity_id: str = "",
    locale: str = "zh_CN",
    extra: Mapping[str, Any] | None = None,
) -> FrontendSectionContext:
    norm_locale: LocaleCode = normalize_lang(locale)
    return FrontendSectionContext(
        page=str(page or "").strip(),
        slot=str(slot or "").strip(),
        entity_type=str(entity_type or "").strip()[:64],
        entity_id=str(entity_id or "").strip()[:160],
        locale=norm_locale,
        extra=_sanitized_extra(extra),
    )


def _sidebar_page_payloads() -> list[dict[str, Any]]:
    """Return metadata for plugin frontend pages pinned in the sidebar nav."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for contribution in frontend_page_contributions():
        if not bool(getattr(contribution, "show_in_sidebar", False)):
            continue
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        page_id = str(getattr(contribution, "page_id", "") or "").strip()
        key = (plugin_id, page_id)
        if not plugin_id or not page_id or key in seen:
            continue
        seen.add(key)
        base = _frontend_page_payload(contribution)
        rows.append(
            {
                "description": str(base.get("description") or ""),
                "frontendUrl": str(base.get("frontendUrl") or ""),
                "i18n": dict(getattr(contribution, "i18n", {}) or {}),
                "navIcon": str(getattr(contribution, "nav_icon", "puzzle") or "puzzle").strip(),
                "navLabel": (
                    str(getattr(contribution, "nav_label", "") or "").strip()
                    or str(base.get("title") or page_id)
                ),
                "order": float(base.get("order") or 100.0),
                "pageId": page_id,
                "pluginId": plugin_id,
                "pluginVersion": str(base.get("pluginVersion") or ""),
                "title": str(base.get("title") or page_id),
            }
        )
    return rows


def _section_actions_payload(actions: Any) -> list[dict[str, Any]]:
    if not actions:
        return []
    return sorted(
        [
            {
                "confirm": str(getattr(action, "confirm", "") or ""),
                "description": str(getattr(action, "description", "") or ""),
                "id": str(getattr(action, "id", "") or ""),
                "label": str(getattr(action, "label", "") or ""),
                "order": float(getattr(action, "order", 100.0) or 100.0),
                "variant": str(getattr(action, "variant", "ghost") or "ghost"),
            }
            for action in actions
        ],
        key=lambda item: (float(item.get("order") or 100.0), str(item.get("label") or "")),
    )


def _serialize_section_contribution(
    contribution: Any,
    ctx: FrontendSectionContext,
) -> dict[str, Any] | None:
    plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
    section_id = str(getattr(contribution, "section_id", "") or "").strip()
    page = str(getattr(contribution, "page", "") or "").strip()
    slot = str(getattr(contribution, "slot", "body") or "body").strip()
    title = str(getattr(contribution, "title", "") or "").strip() or section_id
    renderer = str(getattr(contribution, "renderer", "schema") or "schema").strip()
    if not plugin_id or not section_id or page not in PLUGIN_SECTION_PAGE_SLOTS:
        return None
    payload: dict[str, Any] = {
        "description": str(getattr(contribution, "description", "") or ""),
        "i18n": dict(getattr(contribution, "i18n", {}) or {}),
        "id": section_id,
        "navLabel": str(getattr(contribution, "nav_label", "") or "").strip() or title,
        "order": float(getattr(contribution, "order", 100.0) or 100.0),
        "page": page,
        "pluginId": plugin_id,
        "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
        "renderer": renderer,
        "slot": slot,
        "title": title,
    }
    if renderer == "iframe":
        page_id = str(getattr(contribution, "page_id", "") or "").strip()
        target_page = _frontend_page_contribution(plugin_id, page_id)
        if target_page is None:
            return None
        payload["pageId"] = page_id
        payload["frontendUrl"] = (
            f"/api/plugins/{quote(plugin_id, safe='')}/frontend/{quote(page_id, safe='')}/"
            f"?pluginId={quote(plugin_id, safe='')}&pageId={quote(page_id, safe='')}"
        )
        payload["minHeight"] = int(getattr(contribution, "min_height", 160) or 160)
        payload["maxHeight"] = int(getattr(contribution, "max_height", 960) or 960)
        return payload

    loader = getattr(contribution, "load_values", None)
    if not callable(loader):
        return None
    raw_values = _invoke_with_optional_context(loader, ctx=ctx)
    if not isinstance(raw_values, Mapping):
        raise ValueError(f"section {section_id!r} load_values must return a mapping")
    payload["schema"] = list(getattr(contribution, "schema", []) or [])
    payload["values"] = dict(raw_values)
    payload["canSave"] = callable(getattr(contribution, "save_values", None))
    actions = _section_actions_payload(getattr(contribution, "actions", None))
    if actions:
        payload["actions"] = actions
    return payload


def _frontend_section_payloads(
    page: str | None = None,
    *,
    entity_type: str = "",
    entity_id: str = "",
    locale: str = "zh_CN",
    extra: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_page = str(page or "").strip().lower()
    page_filter = _SECTION_PAGE_ALIASES.get(raw_page, raw_page)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for contribution in frontend_section_contributions():
        current_page = str(getattr(contribution, "page", "") or "").strip()
        if page_filter and current_page != page_filter:
            continue
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        section_id = str(getattr(contribution, "section_id", "") or "").strip()
        key = (plugin_id, current_page, section_id)
        if key in seen:
            continue
        ctx = _build_section_context(
            current_page,
            str(getattr(contribution, "slot", "body") or "body"),
            entity_type=entity_type,
            entity_id=entity_id,
            locale=locale,
            extra=extra,
        )
        item = _serialize_section_contribution(contribution, ctx)
        if item is not None:
            seen.add(key)
            rows.append(item)
    return rows


def _find_section_contribution(plugin_id: str, section_id: str) -> Any | None:
    target_plugin = plugin_id.strip()
    target_section = section_id.strip()
    for contribution in frontend_section_contributions():
        if (
            str(getattr(contribution, "plugin_id", "") or "").strip() == target_plugin
            and str(getattr(contribution, "section_id", "") or "").strip() == target_section
        ):
            return contribution
    return None


def _save_frontend_section_values(
    plugin_id: str,
    section_id: str,
    payload: Mapping[str, Any],
    state: Any = None,
) -> dict[str, Any]:
    with bind_bridge_state(state):
        contribution = _find_section_contribution(plugin_id, section_id)
        if contribution is None:
            raise KeyError(f"plugin section not found: {plugin_id}/{section_id}")
        raw_values = payload.get("values", payload)
        if not isinstance(raw_values, Mapping):
            raise ValueError("values must be an object")
        raw_ctx = payload.get("context") if isinstance(payload.get("context"), Mapping) else {}
        ctx = _build_section_context(
            str(getattr(contribution, "page", "") or ""),
            str(getattr(contribution, "slot", "body") or "body"),
            entity_type=str(raw_ctx.get("entityType") or ""),
            entity_id=str(raw_ctx.get("entityId") or ""),
            locale=str(raw_ctx.get("locale") or "zh_CN"),
            extra=raw_ctx.get("extra") if isinstance(raw_ctx.get("extra"), Mapping) else None,
        )
        saver = getattr(contribution, "save_values", None)
        if not callable(saver):
            raise KeyError(f"section save not supported: {plugin_id}/{section_id}")
        raw_result = _invoke_with_optional_context(saver, dict(raw_values), ctx=ctx)
        kind, message, i18n_message, refresh, _ = _normalize_callback_response(raw_result)
        updated = _serialize_section_contribution(contribution, ctx)
        if updated is None:
            raise KeyError(f"plugin section unavailable after save: {plugin_id}/{section_id}")
        return {
            "kind": kind,
            "message": message or bridge_tr(state, "plugin_ui.saved"),
            **({"i18nMessage": i18n_message} if i18n_message else {}),
            **({"refresh": refresh} if refresh else {}),
            "section": updated,
        }


def _run_frontend_section_action(
    plugin_id: str,
    section_id: str,
    action_id: str,
    payload: Mapping[str, Any],
    state: Any = None,
) -> dict[str, Any]:
    with bind_bridge_state(state):
        contribution = _find_section_contribution(plugin_id, section_id)
        if contribution is None:
            raise KeyError(f"plugin section not found: {plugin_id}/{section_id}")
        raw_values = payload.get("values", {})
        if not isinstance(raw_values, Mapping):
            raise ValueError("values must be an object")
        raw_ctx = payload.get("context") if isinstance(payload.get("context"), Mapping) else {}
        ctx = _build_section_context(
            str(getattr(contribution, "page", "") or ""),
            str(getattr(contribution, "slot", "body") or "body"),
            entity_type=str(raw_ctx.get("entityType") or ""),
            entity_id=str(raw_ctx.get("entityId") or ""),
            locale=str(raw_ctx.get("locale") or "zh_CN"),
            extra=raw_ctx.get("extra") if isinstance(raw_ctx.get("extra"), Mapping) else None,
        )
        for action in getattr(contribution, "actions", None) or []:
            if str(getattr(action, "id", "") or "") != action_id:
                continue
            raw_result = _invoke_with_optional_context(action.run, dict(raw_values), ctx=ctx)
            kind, message, i18n_message, refresh, extra_dict = _normalize_callback_response(
                raw_result
            )
            updated = _serialize_section_contribution(contribution, ctx)
            if updated is None:
                raise KeyError(f"plugin section unavailable after action: {plugin_id}/{section_id}")
            action_label = str(getattr(action, "label", "") or "") or repr(action_id)
            return {
                "kind": kind,
                "message": message or bridge_tr(state, "plugin_ui.action_done", action=action_label),
                **({"i18nMessage": i18n_message} if i18n_message else {}),
                **({"refresh": refresh} if refresh else {}),
                "result": extra_dict,
                "section": updated,
            }
        raise KeyError(f"section action not found: {plugin_id}/{section_id}/{action_id}")


def _run_frontend_action_with_context(
    plugin_id: str,
    contribution_id: str,
    payload: Mapping[str, Any] | None = None,
    state: Any = None,
) -> dict[str, Any]:
    lookup_plugin = plugin_id.strip()
    lookup_contribution = contribution_id.strip()
    body = payload if isinstance(payload, Mapping) else {}
    raw_ctx = body.get("context") if isinstance(body.get("context"), Mapping) else body
    for contribution in frontend_chat_ui_contributions():
        current_plugin = str(getattr(contribution, "plugin_id", "") or "").strip()
        current_id = str(getattr(contribution, "contribution_id", "") or "").strip()
        if current_plugin != lookup_plugin or current_id != lookup_contribution:
            continue
        slot = str(getattr(contribution, "slot", "") or "").strip()
        if slot not in PLUGIN_ACTION_SLOTS:
            continue
        action = getattr(contribution, "action", None)
        if not callable(action):
            raise bridge_error(ValueError, state, "plugin_slot_display_only")
        ctx = FrontendActionContext(
            slot=slot,
            page=str(raw_ctx.get("page") or "").strip()[:64],
            entity_type=str(raw_ctx.get("entityType") or "").strip()[:64],
            entity_id=str(raw_ctx.get("entityId") or "").strip()[:160],
            locale=normalize_lang(str(raw_ctx.get("locale") or "zh_CN")),
            extra=_sanitized_extra(raw_ctx.get("extra")),
        )
        raw_result = _invoke_with_optional_context(action, ctx=ctx)
        kind, message, i18n_message, refresh, extra_dict = _normalize_callback_response(
            raw_result
        )
        conversation_id = extra_dict.get("conversationId")
        if conversation_id is not None and (
            slot != "chat-workspace-actions"
            or kind != "success"
            or not isinstance(conversation_id, str)
            or not conversation_id
            or len(conversation_id) > 128
        ):
            raise ValueError("Invalid plugin conversation launch request")
        return {
            "id": current_id,
            "kind": kind,
            "message": message,
            **({"i18nMessage": i18n_message} if i18n_message else {}),
            **({"refresh": refresh} if refresh else {}),
            **({"conversationId": conversation_id} if conversation_id else {}),
            "pluginId": current_plugin,
        }
    raise KeyError(f"plugin UI contribution not found: {lookup_plugin}/{lookup_contribution}")


def _should_inject_host_theme(plugin_id_or_entry: str, page_id: str) -> bool:
    lookup = str(plugin_id_or_entry or "").strip()
    clean_page = str(page_id or "").strip()
    if not lookup or not clean_page:
        return True
    plugin_id = lookup
    try:
        detail = _plugin_ui_detail(lookup)
        resolved = str(detail.get("plugin", {}).get("id") or "").strip()
        if resolved:
            plugin_id = resolved
    except KeyError:
        pass
    contribution = _frontend_page_contribution(plugin_id, clean_page)
    if contribution is None:
        return True
    return bool(getattr(contribution, "inject_host_theme", True))
