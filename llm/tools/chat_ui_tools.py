from __future__ import annotations
from typing import Any

from core.runtime.app_runtime import try_get_app_runtime
from sdk.tool_registry import tool

_DEFAULT_USER_DISPLAY_NAME = "你"


def _strip_markup(value: str) -> str | None:
    output = ""
    in_tag = False
    for char in value:
        if char == "<":
            if in_tag:
                return None
            in_tag = True
            continue
        if char == ">":
            if not in_tag:
                return None
            in_tag = False
            continue
        if not in_tag:
            output += char
    return None if in_tag else output


def sanitize_user_display_name(value: Any) -> str:
    stripped = _strip_markup(str(value or ""))
    if stripped is None:
        return ""
    name = stripped.strip()
    name = name.strip(" \t\r\n\"'“”‘’「」『』《》[]()（）")
    name = " ".join(name.split()).strip()
    if not name or name == _DEFAULT_USER_DISPLAY_NAME:
        return ""
    if len(name) > 24 or any(ch in name for ch in "\r\n<>"):
        return ""
    return name


@tool(
    name="set_user_display_name",
    group="default",
    description=(
        "Set the human user's visible nameplate in the chat UI. "
        "Call this only when the user or scenario explicitly gives the name/call-sign to use, "
        "and call it before the first visible dialog line. Parameter name is the exact display name."
    ),
)
def _tool_set_user_display_name(name: str) -> dict[str, Any]:
    display_name = sanitize_user_display_name(name)
    if not display_name:
        return {
            "ok": False,
            "error": "display name is empty, unsafe, too long, or equivalent to the default name",
        }

    runtime = try_get_app_runtime()
    if runtime is None:
        return {
            "ok": False,
            "error": "chat runtime is not ready",
            "userDisplayName": display_name,
        }

    ui = getattr(runtime, "ui_update_manager", None)
    if ui is None or not hasattr(ui, "set_user_display_name"):
        return {
            "ok": False,
            "error": "chat UI does not support user display name updates",
            "userDisplayName": display_name,
        }

    ui.set_user_display_name(display_name)
    return {"ok": True, "userDisplayName": display_name}
