from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from application.plugins.catalog import _plugin_rows
from frontend_bridge_core.i18n_helpers import bind_bridge_state, bridge_error, bridge_tr
from sdk.ui_extensions import PLUGIN_ACTION_SLOTS, PLUGIN_UI_ICONS


def _plugin_data_root(plugin_id: str) -> Path:
    cleaned = plugin_id.strip().replace("/", "_") or "unknown"
    return Path("data/plugins") / cleaned


def _plugin_config_field(
    key: str,
    label: str,
    field_type: str,
    *,
    default: Any = None,
    description: str = "",
    max_value: float | int | None = None,
    min_value: float | int | None = None,
    options: list[tuple[str, str]] | None = None,
    path_kind: str | None = None,
    placeholder: str = "",
    span: str | None = None,
    step: float | int | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "defaultValue": default,
        "key": key,
        "label": label,
        "type": field_type,
    }
    if description:
        field["description"] = description
    if max_value is not None:
        field["max"] = max_value
    if min_value is not None:
        field["min"] = min_value
    if options:
        field["options"] = [{"label": option_label, "value": option_value} for option_label, option_value in options]
    if path_kind:
        field["pathKind"] = path_kind
    if placeholder:
        field["placeholder"] = placeholder
    if span:
        field["span"] = span
    if step is not None:
        field["step"] = step
    return field


def _builtin_plugin_config_page(
    plugin_id: str,
    page_id: str,
    state: Any = None,
) -> dict[str, Any] | None:
    tr = lambda key: bridge_tr(state, f"plugin_ui.{key}")
    root = _plugin_data_root(plugin_id)
    if plugin_id == "com.shinsekai.moondream_vision" and page_id == "moondream_vision":
        from dataclasses import asdict

        from plugins.moondream_vision.config_model import default_config_path, load_config

        cfg = load_config(default_config_path(root))
        cfg.clamp()
        return {
            "description": tr("moondream_desc"),
            "restartHint": tr("moondream_restart_hint"),
            "schema": [
                {
                    "description": tr("moondream_model_section_desc"),
                    "fields": [
                        _plugin_config_field(
                            "enabled",
                            tr("moondream_enabled"),
                            "boolean",
                            default=False,
                            span="full",
                        ),
                        _plugin_config_field(
                            "model_id",
                            tr("moondream_model_id"),
                            "text",
                            default="vikhyatk/moondream2",
                            placeholder="vikhyatk/moondream2",
                        ),
                        _plugin_config_field(
                            "revision",
                            tr("moondream_revision"),
                            "text",
                            default="",
                            placeholder=tr("moondream_revision_ph"),
                        ),
                        _plugin_config_field(
                            "cache_dir",
                            tr("moondream_cache_dir"),
                            "text",
                            default="",
                            placeholder=tr("moondream_cache_dir_ph"),
                            span="full",
                        ),
                        _plugin_config_field(
                            "device",
                            tr("moondream_device"),
                            "select",
                            default="auto",
                            options=[
                                (tr("moondream_device_auto"), "auto"),
                                ("CUDA", "cuda"),
                                ("Apple MPS", "mps"),
                                ("CPU", "cpu"),
                            ],
                        ),
                        _plugin_config_field(
                            "quantization",
                            tr("moondream_quantization"),
                            "select",
                            default="none",
                            description=tr("moondream_quantization_desc"),
                            options=[
                                (tr("moondream_quant_none"), "none"),
                                ("INT8", "int8"),
                                ("INT4 (NF4)", "int4"),
                            ],
                        ),
                    ],
                    "id": "model",
                    "title": tr("moondream_model_section_title"),
                },
                {
                    "fields": [
                        _plugin_config_field(
                            "motion_poll_sec",
                            tr("moondream_motion_poll"),
                            "number",
                            default=0.35,
                            description=tr("moondream_motion_poll_desc"),
                            max_value=3.0,
                            min_value=0.12,
                            step=0.05,
                        ),
                        _plugin_config_field(
                            "diff_threshold",
                            tr("moondream_diff_threshold"),
                            "number",
                            default=0.35,
                            description=tr("moondream_diff_threshold_desc"),
                            max_value=0.35,
                            min_value=0.003,
                            step=0.002,
                        ),
                        _plugin_config_field(
                            "mouse_move_percent",
                            tr("moondream_mouse_move"),
                            "number",
                            default=1.1,
                            description=tr("moondream_mouse_move_desc"),
                            max_value=25.0,
                            min_value=0.02,
                            step=0.05,
                        ),
                        _plugin_config_field(
                            "interval_sec",
                            tr("moondream_interval_sec"),
                            "number",
                            default=30,
                            description=tr("moondream_interval_sec_desc"),
                            max_value=600.0,
                            min_value=5.0,
                            step=1.0,
                        ),
                        _plugin_config_field(
                            "monitor_index",
                            tr("moondream_monitor_index"),
                            "integer",
                            default=1,
                            description=tr("moondream_monitor_index_desc"),
                            max_value=16,
                            min_value=0,
                            step=1,
                        ),
                        _plugin_config_field(
                            "infer_max_side",
                            tr("moondream_infer_max_side"),
                            "integer",
                            default=512,
                            description=tr("moondream_infer_max_side_desc"),
                            max_value=8192,
                            min_value=0,
                            step=128,
                        ),
                    ],
                    "id": "triggers",
                    "title": tr("moondream_triggers_title"),
                },
                {
                    "fields": [
                        _plugin_config_field(
                            "question_screen_diff",
                            tr("moondream_q_screen_diff"),
                            "textarea",
                            default="",
                            placeholder="screen thumbnail changed a lot since last successful capture",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_foreground",
                            tr("moondream_q_foreground"),
                            "textarea",
                            default="",
                            placeholder="focused window changed (Windows)",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_new_window",
                            tr("moondream_q_new_window"),
                            "textarea",
                            default="",
                            placeholder="new top-level window opened",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_mouse",
                            tr("moondream_q_mouse"),
                            "textarea",
                            default="",
                            placeholder="user moved mouse beyond threshold",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question",
                            tr("moondream_q_unified"),
                            "textarea",
                            default="",
                            placeholder="Legacy: one English prompt for all triggers only if the four fields above are empty",
                            span="full",
                        ),
                        _plugin_config_field(
                            "message_prefix",
                            tr("moondream_message_prefix"),
                            "text",
                            default="[Screen] ",
                            placeholder=tr("moondream_message_prefix_ph"),
                            span="full",
                        ),
                    ],
                    "id": "prompts",
                    "title": tr("moondream_prompts_title"),
                },
            ],
            "values": asdict(cfg),
        }
    if plugin_id == "com.shinsekai.playwright_browser" and page_id == "playwright_browser":
        from dataclasses import asdict

        from plugins.playwright_browser.config_model import default_config_path, load_config

        cfg = load_config(default_config_path(root))
        cfg.clamp()
        return {
            "description": tr("playwright_desc"),
            "restartHint": tr("playwright_restart_hint"),
            "schema": [
                {
                    "fields": [
                        _plugin_config_field(
                            "browser_type",
                            tr("playwright_browser_type"),
                            "select",
                            default="chromium",
                            options=[
                                (tr("playwright_opt_chromium"), "chromium"),
                                (tr("playwright_opt_firefox"), "firefox"),
                                (tr("playwright_opt_webkit"), "webkit"),
                                (tr("playwright_opt_msedge"), "msedge"),
                                (tr("playwright_opt_chrome"), "chrome"),
                            ],
                        ),
                        _plugin_config_field(
                            "headless",
                            tr("playwright_headless"),
                            "boolean",
                            default=True,
                        ),
                    ],
                    "id": "browser",
                    "title": tr("playwright_title"),
                },
            ],
            "values": asdict(cfg),
        }
    return None


def _frontend_config_contributions_for(plugin_id: str) -> list[Any]:
    from application.plugins.catalog import frontend_config_contributions_for

    return frontend_config_contributions_for(plugin_id)


def _frontend_page_contributions_for(plugin_id: str) -> list[Any]:
    from application.plugins.catalog import frontend_page_contributions_for

    return frontend_page_contributions_for(plugin_id)


def _frontend_chat_ui_contributions() -> list[Any]:
    from application.plugins.catalog import frontend_chat_ui_contributions

    return frontend_chat_ui_contributions()


def _frontend_chat_ui_action(contribution: Any) -> tuple[str, str, str]:
    """Return (actionType, pageId, pageMode). pageMode is how an open-plugin-page
    contribution presents its page: "navigate" (default) or "overlay" (a floating
    window hosted over the chat stage)."""
    action = getattr(contribution, "action", None)
    if callable(action):
        return "callback", "", "navigate"
    if isinstance(action, Mapping):
        action_type = str(action.get("type") or "").strip()
        page_id = str(action.get("page_id") or action.get("pageId") or "").strip()
        if action_type == "open-plugin-page" and page_id:
            mode = str(action.get("mode") or "navigate").strip().lower()
            if mode not in ("navigate", "overlay"):
                mode = "navigate"
            return action_type, page_id, mode
    return "none", "", "navigate"


def _frontend_chat_ui_contribution_payloads() -> list[dict[str, Any]]:
    allowed_slots = PLUGIN_ACTION_SLOTS
    allowed_icons = PLUGIN_UI_ICONS
    allowed_presentations = {"button", "icon-only"}
    allowed_variants = {"danger", "ghost", "primary"}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for contribution in _frontend_chat_ui_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        contribution_id = str(getattr(contribution, "contribution_id", "") or "").strip()
        title = str(getattr(contribution, "title", "") or "").strip()
        slot = str(getattr(contribution, "slot", "") or "").strip()
        key = (plugin_id, contribution_id)
        if not plugin_id or not contribution_id or not title or slot not in allowed_slots or key in seen:
            continue
        seen.add(key)
        action_type, page_id, page_mode = _frontend_chat_ui_action(contribution)
        icon = str(getattr(contribution, "icon", "") or "puzzle").strip()
        presentation = str(getattr(contribution, "presentation", "") or "button").strip()
        if slot == "chat-top-toolbar":
            presentation = "icon-only"
        variant = str(getattr(contribution, "variant", "") or "ghost").strip()
        raw_i18n = getattr(contribution, "i18n", None)
        i18n_dict = dict(raw_i18n) if isinstance(raw_i18n, Mapping) and raw_i18n else None
        rows.append(
            {
                "actionLabel": str(getattr(contribution, "action_label", "") or "").strip() or title,
                "actionType": action_type,
                "actionable": action_type != "none",
                **({"externalLaunch": True} if slot == "chat-workspace-actions"
                   and getattr(contribution, "external_launch", False) is True else {}),
                "description": str(getattr(contribution, "description", "") or "").strip()[:500],
                **({"i18n": i18n_dict} if i18n_dict else {}),
                "icon": icon if icon in allowed_icons else "puzzle",
                "id": contribution_id,
                "order": float(getattr(contribution, "order", 100.0) or 100.0),
                "pageId": page_id,
                "pageMode": page_mode,
                "pluginId": plugin_id,
                "pluginVersion": str(getattr(contribution, "plugin_version", "") or "")[:64],
                "presentation": presentation if presentation in allowed_presentations else "button",
                "slot": slot,
                "title": title[:160],
                "variant": variant if variant in allowed_variants else "ghost",
            }
        )
    return rows


def _run_frontend_chat_ui_contribution(
    plugin_id: str,
    contribution_id: str,
    state: Any = None,
) -> dict[str, Any]:
    lookup_plugin = plugin_id.strip()
    lookup_contribution = contribution_id.strip()
    for contribution in _frontend_chat_ui_contributions():
        current_plugin = str(getattr(contribution, "plugin_id", "") or "").strip()
        current_id = str(getattr(contribution, "contribution_id", "") or "").strip()
        if current_plugin != lookup_plugin or current_id != lookup_contribution:
            continue
        action = getattr(contribution, "action", None)
        if not callable(action):
            raise bridge_error(ValueError, state, "plugin_slot_display_only")
        result = action()
        if isinstance(result, Mapping):
            message = str(result.get("message") or "").strip()
            kind = str(result.get("kind") or "success").strip()
        else:
            message = str(result or "").strip()
            kind = "success"
        conversation_id = result.get("conversationId") if isinstance(result, Mapping) else None
        if conversation_id is not None and (
            contribution.slot != "chat-workspace-actions" or kind != "success"
            or not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 128
        ):
            raise ValueError("Invalid plugin conversation launch request")
        if kind not in {"error", "info", "success"}:
            kind = "success"
        return {
            "id": current_id,
            "kind": kind,
            "message": message[:1000],
            **({"conversationId": conversation_id} if conversation_id else {}),
            "pluginId": current_plugin,
        }
    raise KeyError(f"plugin chat UI contribution not found: {lookup_plugin}/{lookup_contribution}")


def _frontend_page_contribution(plugin_id: str, page_id: str) -> Any | None:
    for contribution in _frontend_page_contributions_for(plugin_id):
        if str(getattr(contribution, "page_id", "") or "").strip() == page_id:
            return contribution
    return None


def _frontend_config_page_payload(contribution: Any) -> dict[str, Any]:
    page_id = str(getattr(contribution, "page_id", "") or "").strip()
    title = str(getattr(contribution, "title", "") or "").strip() or page_id
    kind = str(getattr(contribution, "kind", "") or "settings").strip()
    if kind not in {"settings", "tools"}:
        kind = "settings"
    raw_values = contribution.load_values()
    if not isinstance(raw_values, Mapping):
        raise ValueError(f"frontend config page {page_id!r} load_values must return a mapping")
    payload: dict[str, Any] = {
        "description": str(getattr(contribution, "description", "") or ""),
        "i18n": dict(getattr(contribution, "i18n", {}) or {}),
        "id": page_id,
        "kind": kind,
        "order": float(getattr(contribution, "order", 100.0) or 100.0),
        "pluginId": str(getattr(contribution, "plugin_id", "") or ""),
        "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
        "restartHint": str(getattr(contribution, "restart_hint", "") or ""),
        "schema": list(getattr(contribution, "schema", []) or []),
        "title": title,
        "values": dict(raw_values),
    }
    actions = getattr(contribution, "actions", None) or []
    if actions:
        payload["actions"] = sorted(
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
    return payload


def _frontend_page_payload(contribution: Any) -> dict[str, Any]:
    page_id = str(getattr(contribution, "page_id", "") or "").strip()
    title = str(getattr(contribution, "title", "") or "").strip() or page_id
    kind = str(getattr(contribution, "kind", "") or "settings").strip()
    if kind not in {"settings", "tools"}:
        kind = "settings"
    plugin_id = str(getattr(contribution, "plugin_id", "") or "")
    page = {
        "description": str(getattr(contribution, "description", "") or ""),
        "frontendUrl": (
            f"/api/plugins/{quote(plugin_id, safe='')}/frontend/{quote(page_id, safe='')}/"
            f"?pluginId={quote(plugin_id, safe='')}&pageId={quote(page_id, safe='')}"
        ),
        "i18n": dict(getattr(contribution, "i18n", {}) or {}),
        "id": page_id,
        "injectHostTheme": bool(getattr(contribution, "inject_host_theme", True)),
        "kind": kind,
        "navIcon": str(getattr(contribution, "nav_icon", "puzzle") or "puzzle").strip(),
        "navLabel": str(getattr(contribution, "nav_label", "") or "").strip() or title,
        "order": float(getattr(contribution, "order", 100.0) or 100.0),
        "pluginId": plugin_id,
        "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
        "showInSidebar": bool(getattr(contribution, "show_in_sidebar", False)),
        "title": title,
    }
    for config_contribution in _frontend_config_contributions_for(plugin_id):
        if str(getattr(config_contribution, "page_id", "") or "").strip() != page_id:
            continue
        config_page = _frontend_config_page_payload(config_contribution)
        if str(config_page.get("kind") or "settings") != kind:
            continue
        for key in ("i18n", "restartHint", "schema", "values"):
            if key in config_page:
                page[key] = config_page[key]
        if not page["description"] and config_page.get("description"):
            page["description"] = config_page["description"]
        break
    return page


def _plugin_ui_detail(plugin_id_or_entry: str, state: Any = None) -> dict[str, Any]:
    lookup = plugin_id_or_entry.strip()
    plugin_row = None
    for row in _plugin_rows():
        if row.get("id") == lookup or row.get("entry") == lookup:
            plugin_row = row
            break
    if plugin_row is None:
        raise KeyError(f"plugin not found: {lookup}")

    plugin_id = str(plugin_row.get("id") or "").strip()
    pages: list[dict[str, Any]] = []
    frontend_page_keys: set[tuple[str, str]] = set()

    for contribution in _frontend_page_contributions_for(plugin_id):
        page = _frontend_page_payload(contribution)
        frontend_page_keys.add((str(page.get("kind") or ""), str(page.get("id") or "")))
        pages.append(page)

    for contribution in _frontend_config_contributions_for(plugin_id):
        page = _frontend_config_page_payload(contribution)
        if (str(page.get("kind") or ""), str(page.get("id") or "")) in frontend_page_keys:
            continue
        frontend_page_keys.add((str(page.get("kind") or ""), str(page.get("id") or "")))
        pages.append(page)

    pages.sort(key=lambda item: (float(item.get("order") or 100.0), str(item.get("title") or "")))
    return {"pages": pages, "plugin": plugin_row}


def _save_builtin_plugin_config(plugin_id: str, page_id: str, values: dict[str, Any]) -> None:
    def _float_value(key: str, default: float) -> float:
        raw = values.get(key, default)
        if raw is None or raw == "":
            return default
        return float(raw)

    def _int_value(key: str, default: int) -> int:
        raw = values.get(key, default)
        if raw is None or raw == "":
            return default
        return int(raw)

    root = _plugin_data_root(plugin_id)
    if plugin_id == "com.shinsekai.moondream_vision" and page_id == "moondream_vision":
        from plugins.moondream_vision.config_model import (
            MoondreamVisionConfig,
            default_config_path,
            save_config,
        )

        cfg = MoondreamVisionConfig(
            enabled=bool(values.get("enabled", False)),
            model_id=str(values.get("model_id") or "vikhyatk/moondream2").strip() or "vikhyatk/moondream2",
            revision=str(values.get("revision") or "").strip(),
            cache_dir=str(values.get("cache_dir") or "").strip(),
            device=str(values.get("device") or "auto").strip().lower(),
            quantization=str(values.get("quantization") or "none").strip().lower(),
            motion_poll_sec=_float_value("motion_poll_sec", MoondreamVisionConfig.motion_poll_sec),
            diff_threshold=_float_value("diff_threshold", MoondreamVisionConfig.diff_threshold),
            mouse_move_percent=_float_value("mouse_move_percent", MoondreamVisionConfig.mouse_move_percent),
            interval_sec=_float_value("interval_sec", MoondreamVisionConfig.interval_sec),
            monitor_index=_int_value("monitor_index", MoondreamVisionConfig.monitor_index),
            infer_max_side=_int_value("infer_max_side", MoondreamVisionConfig.infer_max_side),
            question=str(values.get("question") or "").strip(),
            question_screen_diff=str(values.get("question_screen_diff") or "").strip(),
            question_mouse=str(values.get("question_mouse") or "").strip(),
            question_new_window=str(values.get("question_new_window") or "").strip(),
            question_foreground=str(values.get("question_foreground") or "").strip(),
            message_prefix=str(values.get("message_prefix") or MoondreamVisionConfig.message_prefix),
        )
        save_config(default_config_path(root), cfg)
        return

    if plugin_id == "com.shinsekai.playwright_browser" and page_id == "playwright_browser":
        from plugins.playwright_browser import browser
        from plugins.playwright_browser.config_model import (
            PlaywrightBrowserConfig,
            default_config_path,
            save_config,
        )

        cfg = PlaywrightBrowserConfig(
            browser_type=str(values.get("browser_type") or "chromium").strip().lower(),
            headless=bool(values.get("headless", True)),
        )
        save_config(default_config_path(root), cfg)
        browser.set_plugin_root(str(root))
        return

    raise KeyError(f"plugin page config not supported: {plugin_id}/{page_id}")


def _save_plugin_ui_config(
    plugin_id_or_entry: str,
    page_id: str,
    payload: dict[str, Any],
    state: Any = None,
) -> dict[str, Any]:
    with bind_bridge_state(state):
        detail = _plugin_ui_detail(plugin_id_or_entry)
        plugin = detail["plugin"]
        plugin_id = str(plugin.get("id") or "").strip()
        page = None
        for candidate in detail["pages"]:
            if str(candidate.get("id") or "") == page_id:
                page = candidate
                break
        if page is None:
            raise KeyError(f"plugin page not found: {page_id}")
        raw_values = payload.get("values", payload)
        if not isinstance(raw_values, dict):
            raise ValueError("values must be an object")

        for contribution in _frontend_config_contributions_for(plugin_id):
            if str(getattr(contribution, "page_id", "") or "").strip() == page_id:
                contribution.save_values(raw_values)
                updated = _plugin_ui_detail(plugin_id)
                updated_page = next(
                    (candidate for candidate in updated["pages"] if candidate.get("id") == page_id),
                    page,
                )
                return {
                    "message": bridge_tr(state, "plugin_ui.saved"),
                    "page": updated_page,
                    "plugin": updated["plugin"],
                }

        if "schema" not in page:
            raise KeyError(f"plugin page config not supported: {plugin_id}/{page_id}")

        _save_builtin_plugin_config(plugin_id, page_id, raw_values)
        updated = _plugin_ui_detail(plugin_id)
        updated_page = next((candidate for candidate in updated["pages"] if candidate.get("id") == page_id), page)
        return {
            "message": bridge_tr(state, "plugin_ui.saved"),
            "page": updated_page,
            "plugin": updated["plugin"],
        }


def _run_plugin_ui_action(
    plugin_id_or_entry: str,
    page_id: str,
    action_id: str,
    payload: dict[str, Any],
    state: Any = None,
) -> dict[str, Any]:
    """Find the matching action on a FrontendConfigContribution and invoke its run callback."""
    with bind_bridge_state(state):
        detail = _plugin_ui_detail(plugin_id_or_entry)
        plugin = detail["plugin"]
        plugin_id = str(plugin.get("id") or "").strip()
        raw_values = payload.get("values", payload)
        if not isinstance(raw_values, dict):
            raise ValueError("values must be an object")

        for contribution in _frontend_config_contributions_for(plugin_id):
            if str(getattr(contribution, "page_id", "") or "").strip() != page_id:
                continue
            for action in getattr(contribution, "actions", None) or []:
                if str(getattr(action, "id", "") or "") == action_id:
                    result = action.run(raw_values) or {}
                    if not isinstance(result, Mapping):
                        raise ValueError(f"action {action_id!r} run must return a mapping or None")
                    updated = _plugin_ui_detail(plugin_id)
                    updated_page = next(
                        (candidate for candidate in updated["pages"] if candidate.get("id") == page_id),
                        None,
                    )
                    if updated_page is None:
                        raise KeyError(f"plugin page not found after action: {page_id}")
                    action_label = action.label or repr(action_id)
                    return {
                        "message": bridge_tr(state, "plugin_ui.action_done", action=action_label),
                        "page": updated_page,
                        "plugin": updated["plugin"],
                        "result": dict(result),
                    }

        raise KeyError(f"action not found: {plugin_id}/{page_id}/{action_id}")


def _resolve_plugin_frontend_file(plugin_id_or_entry: str, page_id: str, asset_path: str) -> Path:
    detail = _plugin_ui_detail(plugin_id_or_entry)
    plugin = detail["plugin"]
    plugin_id = str(plugin.get("id") or "").strip()
    contribution = _frontend_page_contribution(plugin_id, page_id)
    if contribution is None:
        raise KeyError(f"plugin frontend page not found: {plugin_id}/{page_id}")
    entry = Path(str(getattr(contribution, "entry", "") or "")).expanduser()
    if not entry.is_absolute():
        entry = (Path.cwd() / entry).resolve()
    else:
        entry = entry.resolve()
    if not entry.is_file():
        raise FileNotFoundError(entry.as_posix())
    root = entry.parent.resolve()
    cleaned_asset = str(asset_path or "").replace("\\", "/").strip("/")
    target = entry if not cleaned_asset else (root / cleaned_asset).resolve()
    if root not in target.parents and target != root and target != entry:
        raise PermissionError("plugin frontend asset is outside frontend root")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise FileNotFoundError(target.as_posix())
    return target
