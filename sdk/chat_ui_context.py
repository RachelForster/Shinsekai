"""Retired Qt chat-context compatibility surface.

React/Tauri plugins use :mod:`sdk.frontend_ui`. The names remain importable so
older plugins fail with an actionable runtime message instead of importing Qt.
"""

from __future__ import annotations

from typing import Any

_chat_ui_ctx: Any | None = None


def set_chat_ui_context(ctx: Any | None) -> None:
    global _chat_ui_ctx
    _chat_ui_ctx = ctx


def get_chat_ui_context() -> Any:
    if _chat_ui_ctx is None:
        raise RuntimeError(
            "ChatUIContext was retired with the Qt UI; use register.frontend_ui()."
        )
    return _chat_ui_ctx


def try_get_chat_ui_context() -> Any | None:
    return _chat_ui_ctx


class ChatUIContext:
    """Deprecated placeholder for the removed Qt chat integration."""

    @classmethod
    def bind(cls, *args: Any, **kwargs: Any) -> "ChatUIContext":
        del args, kwargs
        raise RuntimeError(
            "ChatUIContext was retired with the Qt UI; use register.frontend_ui()."
        )
