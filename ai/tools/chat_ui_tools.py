"""Chat presentation command tools."""

from __future__ import annotations
from typing import Any

from core.chat_history.text import sanitize_user_display_name
from sdk.llm_runtime import get_llm_host_runtime
from sdk.tool_registry import tool


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

    error = get_llm_host_runtime().set_user_display_name(display_name)
    if error is not None:
        return {
            "ok": False,
            "error": error,
            "userDisplayName": display_name,
        }

    return {"ok": True, "userDisplayName": display_name}
