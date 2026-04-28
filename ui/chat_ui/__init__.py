"""独立聊天窗口 UI（与 `ui.desktop_ui` 并列的子包）。"""

from ui.chat_ui.signal_bridge import (
    ChatUISignalBridge,
    attach_chat_ui_window,
    detach_chat_ui_window,
    get_chat_ui_signal_bridge,
)

__all__ = [
    "ChatUISignalBridge",
    "attach_chat_ui_window",
    "detach_chat_ui_window",
    "get_chat_ui_signal_bridge",
]