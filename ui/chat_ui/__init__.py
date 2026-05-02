"""独立聊天窗口 UI（与 `ui.desktop_ui` 并列的子包）。"""

from __future__ import annotations

import importlib
from typing import Any

from ui.chat_ui.signal_bridge import (
    ChatUISignalBridge,
    attach_chat_ui_window,
    detach_chat_ui_window,
    get_chat_ui_signal_bridge,
)

__all__ = [
    "ChatUIContext",
    "ChatUISignalBridge",
    "attach_chat_ui_window",
    "detach_chat_ui_window",
    "get_chat_ui_context",
    "get_chat_ui_signal_bridge",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
]

_SDK_CTX_NAMES = frozenset({
    "ChatUIContext",
    "get_chat_ui_context",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
})


def __getattr__(name: str) -> Any:
    if name in _SDK_CTX_NAMES:
        mod = importlib.import_module("sdk.chat_ui_context")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
