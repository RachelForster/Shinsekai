"""Shared validation of the human user's visible chat name."""

from __future__ import annotations

from typing import Any

from core.chat_history.text import DEFAULT_USER_DISPLAY_NAME


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
    if not name or name == DEFAULT_USER_DISPLAY_NAME:
        return ""
    if len(name) > 24 or any(ch in name for ch in "\r\n<>"):
        return ""
    return name
