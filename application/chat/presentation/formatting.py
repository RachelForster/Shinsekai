"""HTML and compact status formatting helpers for chat presentation."""

from __future__ import annotations

import html
import re
import time
from typing import Any, Dict


def _native_tool_confirmation_options(
    *,
    confirmation_id: str,
    tool_name: str,
    detail: str = "",
) -> list[dict[str, str]]:
    from i18n import tr

    confirm_label = tr("tool_confirmation.confirm", tool=tool_name)
    if detail:
        confirm_label = f"{confirm_label}\n{detail}"
    base = {
        "confirmationId": str(confirmation_id or ""),
        "kind": "tool-confirmation",
    }
    return [
        {
            **base,
            "action": "cancel",
            "label": tr("common.cancel"),
        },
        {
            **base,
            "action": "confirm",
            "label": confirm_label,
        },
    ]


def _format_token_count(value: Any) -> str:
    try:
        count = max(0, int(value or 0))
    except (TypeError, ValueError):
        count = 0
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}m"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def format_context_token_estimate(estimate: Dict[str, Any]) -> str:
    """Compact one-line token budget status for the desktop overlay."""
    return (
        "tokens "
        f"sys {_format_token_count(estimate.get('system_prompt_tokens'))} | "
        f"hist {_format_token_count(estimate.get('history_tokens'))} | "
        f"tools {_format_token_count(estimate.get('tool_definition_tokens'))} | "
        f"total {_format_token_count(estimate.get('estimated_total_tokens'))}"
    )


def _safe_css_color(value: Any, fallback: str) -> str:
    color = str(value or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", color):
        return color
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", color):
        return color
    if re.fullmatch(
        r"rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)",
        color,
    ):
        return color
    return fallback


def _format_dialog_html(name: str, speech: str, color: str, is_system: bool) -> str:
    separator = "\uff1a"
    safe_name = html.escape(str(name or ""), quote=False)
    safe_speech = html.escape(str(speech or ""), quote=False).replace("\n", "<br>")
    safe_color = _safe_css_color(color, "#84C2D5" if is_system else "#FFFFFF")
    if is_system:
        return (
            f"<p style='line-height: 135%; letter-spacing: 2px; color:{safe_color};'>"
            f"<b>{safe_name}</b>{separator}{safe_speech}</p>"
        )
    return (
        f"<p style='line-height: 135%; letter-spacing: 2px;'>"
        f"<b style='color:{safe_color};'>{safe_name}</b>{separator}{safe_speech}</p>"
    )


def _format_user_html(text: str) -> str:
    created_at = int(time.time() * 1000)
    safe_text = html.escape(str(text or ""), quote=False).replace("\n", "<br>")
    return (
        f"<p data-created-at='{created_at}' style='line-height: 135%; letter-spacing: 2px; color:white;'>"
        f"<b style='color:white;'>你</b>: {safe_text}</p>"
    )
