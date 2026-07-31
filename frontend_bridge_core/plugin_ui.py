from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from sdk.file_transactions import ensure_portable_name_available
from sdk.path_contract import (
    managed_project_directory,
    project_root as runtime_project_root,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_path,
    resolve_project_read_path,
    safe_path_component,
)

from application.plugins.catalog import _plugin_rows
from sdk.path_references import make_path_reference, path_reference_value
from .security import portable_path_text, safe_child_path


def _plugin_identity(value: Any, *, field: str = "plugin id") -> str:
    return safe_path_component(str(value or ""), field=field)


def _identity_matches(value: Any, expected: str, *, field: str) -> bool:
    try:
        return _plugin_identity(value, field=field) == expected
    except ValueError:
        return False


def _plugin_data_root(plugin_id: str, *, project_root: Path | None = None) -> Path:
    cleaned = safe_path_component(str(plugin_id or ""), field="plugin id")
    root = require_directory_without_links(
        runtime_project_root() if project_root is None else project_root,
        field="plugin project root",
    )
    storage = managed_project_directory("data/plugins", cleaned, root=root)
    ensure_portable_name_available(storage.parent, cleaned)
    return storage


def _plugin_config_file(
    plugin_root: Path,
    candidate: Path,
    *,
    project_root: Path | None = None,
) -> Path:
    """Validate a built-in plugin config leaf before third-party file I/O."""

    project = (
        runtime_project_root()
        if project_root is None
        else resolve_project_path(".", root=project_root)
    )
    exact_root = resolve_managed_project_path(plugin_root, root=project)
    exact_file = resolve_managed_project_path(candidate, root=project)
    if exact_file.parent != exact_root:
        raise PermissionError("plugin config file is outside the plugin data root")
    return exact_file


def _stored_plugin_cache_path(
    value: Any,
    *,
    project_root: Path | None = None,
) -> str:
    """Serialize an optional plugin cache directory without cwd ownership."""

    raw = str(value or "")
    if not raw:
        return ""
    root = (
        runtime_project_root()
        if project_root is None
        else resolve_project_path(".", root=project_root)
    )
    reference = make_path_reference(
        raw,
        root,
        legacy_project_prefixes=(("data", "cache"),),
        recover_legacy_absolute=False,
    )
    stored = path_reference_value(reference)
    if stored is None:
        raise ValueError("plugin cache directory could not be classified")
    # Revalidate the spelling at the output boundary. This rejects linked
    # parents and ambiguous relative aliases before an optional plugin receives
    # the persisted value.
    stored_path = Path(stored).expanduser()
    if stored_path.is_absolute():
        require_symlink_free_absolute_path(
            stored_path,
            field="plugin cache directory",
        )
    resolve_project_output_path(stored, root=root)
    return stored


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
    *,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    root = _plugin_data_root(plugin_id, project_root=project_root)
    if plugin_id == "com.shinsekai.moondream_vision" and page_id == "moondream_vision":
        from dataclasses import asdict

        from plugins.moondream_vision.config_model import default_config_path, load_config

        config_path = _plugin_config_file(
            root,
            default_config_path(root),
            project_root=project_root,
        )
        cfg = load_config(config_path)
        cfg.clamp()
        cfg.cache_dir = _stored_plugin_cache_path(
            cfg.cache_dir,
            project_root=project_root,
        )
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
                            "file",
                            default="",
                            path_kind="directory",
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

        config_path = _plugin_config_file(
            root,
            default_config_path(root),
            project_root=project_root,
        )
        cfg = load_config(config_path)
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
    from application.plugins.catalog import frontend_config_contributions_for

    exact_plugin_id = _plugin_identity(plugin_id)
    out: list[Any] = []
    for contribution in frontend_config_contributions_for(exact_plugin_id):
        if _identity_matches(
            getattr(contribution, "plugin_id", ""),
            exact_plugin_id,
            field="plugin id",
        ):
            out.append(contribution)
    return sorted(out, key=lambda item: float(getattr(item, "order", 100.0) or 100.0))


def _frontend_page_contributions_for(plugin_id: str) -> list[Any]:
    from application.plugins.catalog import frontend_page_contributions_for

    exact_plugin_id = _plugin_identity(plugin_id)
    out: list[Any] = []
    for contribution in frontend_page_contributions_for(exact_plugin_id):
        if _identity_matches(
            getattr(contribution, "plugin_id", ""),
            exact_plugin_id,
            field="plugin id",
        ):
            out.append(contribution)
    return sorted(out, key=lambda item: float(getattr(item, "order", 100.0) or 100.0))


def _frontend_chat_ui_contributions() -> list[Any]:
    from application.plugins.catalog import frontend_chat_ui_contributions

    return sorted(
        frontend_chat_ui_contributions(),
        key=lambda item: float(getattr(item, "order", 100.0) or 100.0),
    )


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
    allowed_slots = {"chat-dialog-actions", "chat-output", "chat-toolbar", "chat-top-toolbar"}
    allowed_icons = {"info", "play", "puzzle", "settings", "smartphone", "sparkles"}
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
        rows.append(
            {
                "actionLabel": str(getattr(contribution, "action_label", "") or "").strip() or title,
                "actionType": action_type,
                "actionable": action_type != "none",
                "description": str(getattr(contribution, "description", "") or "").strip()[:500],
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
    exact_page_id = _plugin_identity(page_id, field="frontend page id")
    for contribution in _frontend_page_contributions_for(plugin_id):
        if _identity_matches(
            getattr(contribution, "page_id", ""),
            exact_page_id,
            field="frontend page id",
        ):
            return contribution
    return None


def _frontend_config_page_payload(contribution: Any) -> dict[str, Any]:
    page_id = _plugin_identity(
        getattr(contribution, "page_id", ""),
        field="frontend page id",
    )
    raw_plugin_id = getattr(contribution, "plugin_id", None)
    plugin_id = (
        _plugin_identity(raw_plugin_id)
        if raw_plugin_id is not None
        else ""
    )
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
        "pluginId": plugin_id,
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
                    "id": _plugin_identity(
                        getattr(action, "id", ""),
                        field="frontend action id",
                    ),
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
    page_id = _plugin_identity(
        getattr(contribution, "page_id", ""),
        field="frontend page id",
    )
    title = str(getattr(contribution, "title", "") or "").strip() or page_id
    kind = str(getattr(contribution, "kind", "") or "settings").strip()
    if kind not in {"settings", "tools"}:
        kind = "settings"
    plugin_id = _plugin_identity(getattr(contribution, "plugin_id", ""))
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
        if not _identity_matches(
            getattr(config_contribution, "page_id", ""),
            page_id,
            field="frontend page id",
        ):
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


def _plugin_ui_detail(
    plugin_id_or_entry: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    lookup = portable_path_text(
        plugin_id_or_entry,
        field="plugin id or manifest entry",
    )
    plugin_row = None
    for row in _plugin_rows():
        if row.get("id") == lookup or row.get("entry") == lookup:
            plugin_row = row
            break
    if plugin_row is None:
        raise KeyError(f"plugin not found: {lookup}")

    try:
        plugin_id = _plugin_identity(plugin_row.get("id"))
    except ValueError:
        # An offline row can only expose its import entry as an identifier.
        # It has no live contributions, but remains useful as uninstall/error
        # metadata and must not be reinterpreted as a local storage name.
        return {"pages": [], "plugin": plugin_row}
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


def _save_builtin_plugin_config(
    plugin_id: str,
    page_id: str,
    values: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> None:
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

    root = _plugin_data_root(plugin_id, project_root=project_root)
    if plugin_id == "com.shinsekai.moondream_vision" and page_id == "moondream_vision":
        from plugins.moondream_vision.config_model import (
            MoondreamVisionConfig,
            default_config_path,
            save_config,
        )

        cache_dir = _stored_plugin_cache_path(
            values.get("cache_dir"),
            project_root=project_root,
        )
        cfg = MoondreamVisionConfig(
            enabled=bool(values.get("enabled", False)),
            model_id=str(values.get("model_id") or "vikhyatk/moondream2").strip() or "vikhyatk/moondream2",
            revision=str(values.get("revision") or "").strip(),
            cache_dir=cache_dir,
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
        config_path = _plugin_config_file(
            root,
            default_config_path(root),
            project_root=project_root,
        )
        save_config(config_path, cfg)
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
        config_path = _plugin_config_file(
            root,
            default_config_path(root),
            project_root=project_root,
        )
        save_config(config_path, cfg)
        browser.set_plugin_root(str(root))
        return

    raise KeyError(f"plugin page config not supported: {plugin_id}/{page_id}")


def _detail_for_project_root(
    plugin_id_or_entry: str,
    project_root: Path | None,
) -> dict[str, Any]:
    if project_root is None:
        return _plugin_ui_detail(plugin_id_or_entry)
    return _plugin_ui_detail(plugin_id_or_entry, project_root=project_root)


def _save_plugin_ui_config(
    plugin_id_or_entry: str,
    page_id: str,
    payload: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    detail = _detail_for_project_root(plugin_id_or_entry, project_root)
    plugin = detail["plugin"]
    plugin_id = _plugin_identity(plugin.get("id"))
    page_id = _plugin_identity(page_id, field="frontend page id")
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
        if _identity_matches(
            getattr(contribution, "page_id", ""),
            page_id,
            field="frontend page id",
        ):
            contribution.save_values(raw_values)
            updated = _detail_for_project_root(plugin_id, project_root)
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

    _save_builtin_plugin_config(
        plugin_id,
        page_id,
        raw_values,
        project_root=project_root,
    )
    updated = _detail_for_project_root(plugin_id, project_root)
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
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Find the matching action on a FrontendConfigContribution and invoke its run callback."""
    detail = _detail_for_project_root(plugin_id_or_entry, project_root)
    plugin = detail["plugin"]
    plugin_id = _plugin_identity(plugin.get("id"))
    page_id = _plugin_identity(page_id, field="frontend page id")
    action_id = _plugin_identity(action_id, field="frontend action id")
    raw_values = payload.get("values", payload)
    if not isinstance(raw_values, dict):
        raise ValueError("values must be an object")

    for contribution in _frontend_config_contributions_for(plugin_id):
        if not _identity_matches(
            getattr(contribution, "page_id", ""),
            page_id,
            field="frontend page id",
        ):
            continue
        for action in getattr(contribution, "actions", None) or []:
            if str(getattr(action, "id", "") or "") == action_id:
                result = action.run(raw_values) or {}
                if not isinstance(result, Mapping):
                    raise ValueError(f"action {action_id!r} run must return a mapping or None")
                updated = _detail_for_project_root(plugin_id, project_root)
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


def _resolve_plugin_frontend_file(
    plugin_id_or_entry: str,
    page_id: str,
    asset_path: str,
    *,
    project_root: Path | None = None,
) -> Path:
    detail = _detail_for_project_root(plugin_id_or_entry, project_root)
    plugin = detail["plugin"]
    plugin_id = _plugin_identity(plugin.get("id"))
    contribution = _frontend_page_contribution(plugin_id, page_id)
    if contribution is None:
        raise KeyError(f"plugin frontend page not found: {plugin_id}/{page_id}")
    entry_text = portable_path_text(
        str(getattr(contribution, "entry", "") or ""),
        field="plugin frontend entry",
    )
    entry = resolve_project_read_path(
        entry_text,
        root=(
            runtime_project_root()
            if project_root is None
            else project_root
        ),
    )
    if not entry.is_file():
        raise FileNotFoundError(entry.as_posix())
    root = entry.parent
    raw_asset = str(asset_path or "")
    if not raw_asset:
        target = entry
    else:
        cleaned_asset = portable_path_text(raw_asset, field="plugin frontend asset")
        if "\\" in cleaned_asset or cleaned_asset.startswith("/"):
            raise ValueError("plugin frontend asset must be an exact relative URL path")
        parts = cleaned_asset.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("plugin frontend asset must be an exact relative URL path")
        target = safe_child_path(root, cleaned_asset)
    if target.is_dir():
        relative = target.relative_to(root) / "index.html"
        target = safe_child_path(root, relative.as_posix())
    if not target.is_file():
        raise FileNotFoundError(target.as_posix())
    return target
