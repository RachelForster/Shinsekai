from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .plugin_catalog import _plugin_rows


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


def _builtin_plugin_config_page(plugin_id: str, page_id: str) -> dict[str, Any] | None:
    root = _plugin_data_root(plugin_id)
    if plugin_id == "com.shinsekai.moondream_vision" and page_id == "moondream_vision":
        from dataclasses import asdict

        from plugins.moondream_vision.config_model import default_config_path, load_config

        cfg = load_config(default_config_path(root))
        cfg.clamp()
        return {
            "description": (
                "使用 mss 截屏，通过 Hugging Face Transformers 加载 Moondream2。"
                "自动识屏按触发类型使用英文提示词，并受最短推理间隔限制。"
            ),
            "restartHint": "修改模型 ID、设备、量化或缓存目录后，建议重启聊天主程序以重新加载权重。",
            "schema": [
                {
                    "description": (
                        "首次启用后首次推理会从网络下载模型到 Hugging Face 缓存。"
                        "INT8 / INT4 需要 NVIDIA GPU + CUDA + bitsandbytes。"
                    ),
                    "fields": [
                        _plugin_config_field(
                            "enabled",
                            "启用识屏（差分 / 鼠标 / 系统窗口事件触发）",
                            "boolean",
                            default=False,
                            span="full",
                        ),
                        _plugin_config_field(
                            "model_id",
                            "模型 ID",
                            "text",
                            default="vikhyatk/moondream2",
                            placeholder="vikhyatk/moondream2",
                        ),
                        _plugin_config_field(
                            "revision",
                            "修订 revision",
                            "text",
                            default="",
                            placeholder="可选，如 2025-01-09",
                        ),
                        _plugin_config_field(
                            "cache_dir",
                            "缓存目录",
                            "text",
                            default="",
                            placeholder="可选；留空用系统默认 HF 缓存",
                            span="full",
                        ),
                        _plugin_config_field(
                            "device",
                            "设备",
                            "select",
                            default="auto",
                            options=[
                                ("自动", "auto"),
                                ("CUDA", "cuda"),
                                ("Apple MPS", "mps"),
                                ("CPU", "cpu"),
                            ],
                        ),
                        _plugin_config_field(
                            "quantization",
                            "权重量化",
                            "select",
                            default="none",
                            description="INT8 / INT4 需 NVIDIA CUDA 与 bitsandbytes；Apple MPS / CPU 不兼容。",
                            options=[
                                ("无（浮点）", "none"),
                                ("INT8", "int8"),
                                ("INT4（NF4）", "int4"),
                            ],
                        ),
                    ],
                    "id": "model",
                    "title": "Moondream 本地识屏",
                },
                {
                    "fields": [
                        _plugin_config_field(
                            "motion_poll_sec",
                            "触发采样间隔",
                            "number",
                            default=0.35,
                            description="采样鼠标、窗口与缩略图差分的间隔；越小越灵敏，占用略高。",
                            max_value=3.0,
                            min_value=0.12,
                            step=0.05,
                        ),
                        _plugin_config_field(
                            "diff_threshold",
                            "屏幕差分阈值",
                            "number",
                            default=0.35,
                            description="相对上次识别成功的缩略图，变化像素占比阈值。",
                            max_value=0.35,
                            min_value=0.003,
                            step=0.002,
                        ),
                        _plugin_config_field(
                            "mouse_move_percent",
                            "鼠标移动阈值（% 屏）",
                            "number",
                            default=1.1,
                            description="相对当前显示器画面的宽/高较大一边，移动直线距离超过该比例视为活动。",
                            max_value=25.0,
                            min_value=0.02,
                            step=0.05,
                        ),
                        _plugin_config_field(
                            "interval_sec",
                            "最短推理间隔",
                            "number",
                            default=30,
                            description="两次送模型推理之间的最短间隔。",
                            max_value=600.0,
                            min_value=5.0,
                            step=1.0,
                        ),
                        _plugin_config_field(
                            "monitor_index",
                            "显示器索引",
                            "integer",
                            default=1,
                            description="mss：0=所有显示器合成；1 通常为第一块物理屏。",
                            max_value=16,
                            min_value=0,
                            step=1,
                        ),
                        _plugin_config_field(
                            "infer_max_side",
                            "推理输入最长边 (px)",
                            "integer",
                            default=512,
                            description="送入 Moondream 前将截图较长边缩到此像素；0=不缩放。",
                            max_value=8192,
                            min_value=0,
                            step=128,
                        ),
                    ],
                    "id": "triggers",
                    "title": "触发与推理",
                },
                {
                    "fields": [
                        _plugin_config_field(
                            "question_screen_diff",
                            "屏幕差分 · screen_diff",
                            "textarea",
                            default="",
                            placeholder="screen thumbnail changed a lot since last successful capture",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_foreground",
                            "前台切换 · foreground",
                            "textarea",
                            default="",
                            placeholder="focused window changed (Windows)",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_new_window",
                            "新窗口 · new_window",
                            "textarea",
                            default="",
                            placeholder="new top-level window opened",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question_mouse",
                            "鼠标移动 · mouse",
                            "textarea",
                            default="",
                            placeholder="user moved mouse beyond threshold",
                            span="full",
                        ),
                        _plugin_config_field(
                            "question",
                            "统一提问（可选）",
                            "textarea",
                            default="",
                            placeholder="Legacy: one English prompt for all triggers only if the four fields above are empty",
                            span="full",
                        ),
                        _plugin_config_field(
                            "message_prefix",
                            "消息前缀",
                            "text",
                            default="[Screen] ",
                            placeholder="发到聊天里的前缀",
                            span="full",
                        ),
                    ],
                    "id": "prompts",
                    "title": "英文提示词（按触发类型，可留空用内置）",
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
            "description": (
                "Chromium / Firefox / WebKit 需要 playwright install 下载；"
                "Edge / Chrome 使用系统浏览器无需下载。修改后需重启生效。"
            ),
            "restartHint": "修改浏览器设置后，建议重启聊天主程序以重新创建浏览器会话。",
            "schema": [
                {
                    "fields": [
                        _plugin_config_field(
                            "browser_type",
                            "浏览器类型",
                            "select",
                            default="chromium",
                            options=[
                                ("Chromium（Playwright 内置，需下载）", "chromium"),
                                ("Firefox（Playwright 内置，需下载）", "firefox"),
                                ("WebKit（Playwright 内置，需下载）", "webkit"),
                                ("Microsoft Edge（使用系统已安装的 Edge）", "msedge"),
                                ("Google Chrome（使用系统已安装的 Chrome）", "chrome"),
                            ],
                        ),
                        _plugin_config_field(
                            "headless",
                            "无头模式（Headless）",
                            "boolean",
                            default=True,
                        ),
                    ],
                    "id": "browser",
                    "title": "Playwright 浏览器设置",
                },
            ],
            "values": asdict(cfg),
        }
    return None


def _frontend_config_contributions_for(plugin_id: str) -> list[Any]:
    try:
        from core.plugins.plugin_host import collect_frontend_config_contributions
    except Exception:
        return []
    out: list[Any] = []
    for contribution in collect_frontend_config_contributions():
        if str(getattr(contribution, "plugin_id", "") or "").strip() == plugin_id:
            out.append(contribution)
    return sorted(out, key=lambda item: float(getattr(item, "order", 100.0) or 100.0))


def _frontend_page_contributions_for(plugin_id: str) -> list[Any]:
    try:
        from core.plugins.plugin_host import collect_frontend_page_contributions
    except Exception:
        return []
    out: list[Any] = []
    for contribution in collect_frontend_page_contributions():
        if str(getattr(contribution, "plugin_id", "") or "").strip() == plugin_id:
            out.append(contribution)
    return sorted(out, key=lambda item: float(getattr(item, "order", 100.0) or 100.0))


def _frontend_chat_ui_contributions() -> list[Any]:
    try:
        from core.plugins.plugin_host import collect_frontend_chat_ui_contributions
    except Exception:
        return []
    return sorted(
        collect_frontend_chat_ui_contributions(),
        key=lambda item: float(getattr(item, "order", 100.0) or 100.0),
    )


def _frontend_chat_ui_contribution_payloads() -> list[dict[str, Any]]:
    allowed_slots = {"chat-dialog-actions", "chat-output", "chat-toolbar"}
    allowed_icons = {"info", "play", "puzzle", "settings", "sparkles"}
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
        icon = str(getattr(contribution, "icon", "") or "puzzle").strip()
        variant = str(getattr(contribution, "variant", "") or "ghost").strip()
        rows.append(
            {
                "actionLabel": str(getattr(contribution, "action_label", "") or "").strip() or title,
                "actionable": callable(getattr(contribution, "action", None)),
                "description": str(getattr(contribution, "description", "") or "").strip()[:500],
                "icon": icon if icon in allowed_icons else "puzzle",
                "id": contribution_id[:128],
                "order": float(getattr(contribution, "order", 100.0) or 100.0),
                "pluginId": plugin_id[:128],
                "pluginVersion": str(getattr(contribution, "plugin_version", "") or "")[:64],
                "slot": slot,
                "title": title[:160],
                "variant": variant if variant in allowed_variants else "ghost",
            }
        )
    return rows


def _run_frontend_chat_ui_contribution(plugin_id: str, contribution_id: str) -> dict[str, Any]:
    lookup_plugin = plugin_id.strip()
    lookup_contribution = contribution_id.strip()
    for contribution in _frontend_chat_ui_contributions():
        current_plugin = str(getattr(contribution, "plugin_id", "") or "").strip()
        current_id = str(getattr(contribution, "contribution_id", "") or "").strip()
        if current_plugin != lookup_plugin or current_id != lookup_contribution:
            continue
        action = getattr(contribution, "action", None)
        if not callable(action):
            raise ValueError("该插件插槽只提供状态展示，没有可执行动作。")
        result = action()
        if isinstance(result, Mapping):
            message = str(result.get("message") or "").strip()
            kind = str(result.get("kind") or "success").strip()
        else:
            message = str(result or "").strip()
            kind = "success"
        if kind not in {"error", "info", "success"}:
            kind = "success"
        return {
            "id": current_id,
            "kind": kind,
            "message": message[:1000],
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
        "id": page_id,
        "kind": kind,
        "order": float(getattr(contribution, "order", 100.0) or 100.0),
        "pluginId": plugin_id,
        "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
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


def _plugin_ui_detail(plugin_id_or_entry: str) -> dict[str, Any]:
    try:
        from core.plugins.plugin_host import collect_settings_contributions, collect_tools_tab_contributions
    except Exception:
        raise KeyError(f"plugin not found: {plugin_id_or_entry}")

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

    for contribution in collect_settings_contributions():
        if str(getattr(contribution, "plugin_id", "") or "").strip() != plugin_id:
            continue
        page_id = str(getattr(contribution, "page_id", "") or "").strip()
        if ("settings", page_id) in frontend_page_keys:
            continue
        title = str(getattr(contribution, "nav_label", "") or "").strip() or page_id
        page: dict[str, Any] = {
            "id": page_id,
            "kind": "settings",
            "order": float(getattr(contribution, "order", 100.0) or 100.0),
            "pluginId": plugin_id,
            "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
            "title": title,
        }
        builtin = _builtin_plugin_config_page(plugin_id, page_id)
        if builtin is not None:
            page.update(builtin)
        else:
            page["unavailableReason"] = "该插件设置页仍以 PyQt Widget 形式贡献，当前 React 端没有可渲染的配置 schema。"
        pages.append(page)

    for contribution in collect_tools_tab_contributions():
        if str(getattr(contribution, "plugin_id", "") or "").strip() != plugin_id:
            continue
        page_id = str(getattr(contribution, "tab_id", "") or "").strip()
        if ("tools", page_id) in frontend_page_keys:
            continue
        title = str(getattr(contribution, "title", "") or "").strip() or page_id
        page = {
            "id": page_id,
            "kind": "tools",
            "order": float(getattr(contribution, "order", 100.0) or 100.0),
            "pluginId": plugin_id,
            "pluginVersion": str(getattr(contribution, "plugin_version", "") or ""),
            "title": title,
        }
        builtin = _builtin_plugin_config_page(plugin_id, page_id)
        if builtin is not None:
            page.update(builtin)
        else:
            page["unavailableReason"] = "该插件工具页仍以 PyQt Widget 形式贡献，当前 React 端没有可渲染的配置 schema。"
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


def _save_plugin_ui_config(plugin_id_or_entry: str, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
                "message": "插件设置已保存。",
                "page": updated_page,
                "plugin": updated["plugin"],
            }

    if "schema" not in page:
        raise KeyError(f"plugin page config not supported: {plugin_id}/{page_id}")

    _save_builtin_plugin_config(plugin_id, page_id, raw_values)
    updated = _plugin_ui_detail(plugin_id)
    updated_page = next((candidate for candidate in updated["pages"] if candidate.get("id") == page_id), page)
    return {
        "message": "插件设置已保存。",
        "page": updated_page,
        "plugin": updated["plugin"],
    }


def _run_plugin_ui_action(
    plugin_id_or_entry: str,
    page_id: str,
    action_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Find the matching action on a FrontendConfigContribution and invoke its run callback."""
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
                return {
                    "message": f"操作 {action.label or action_id!r} 已完成。",
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
