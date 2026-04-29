from __future__ import annotations

from typing import Any, Callable, List, Optional, Protocol

from PySide6.QtCore import QObject, Qt, Signal

from ui.chat_ui.signal_bridge import ChatUISignalBridge, get_chat_ui_signal_bridge

_chat_ui_ctx: Optional["ChatUIContext"] = None


def set_chat_ui_context(ctx: Optional["ChatUIContext"]) -> None:
    global _chat_ui_ctx
    _chat_ui_ctx = ctx


def get_chat_ui_context() -> "ChatUIContext":
    if _chat_ui_ctx is None:
        raise RuntimeError(
            "尚未设置 ChatUIContext：宿主在创建窗口后应调用 install / bind 与 set_chat_ui_context"
        )
    return _chat_ui_ctx


def try_get_chat_ui_context() -> Optional["ChatUIContext"]:
    return _chat_ui_ctx

# 定义宿主需要实现的查询接口
class _ChatUIStateProxy(Protocol):
    """宿主提供的只读状态访问，ChatUIContext 通过它查询 UI 现状。"""
    def notification_hint(self) -> str: ...
    def input_draft(self) -> str: ...
    def choice_options(self) -> List[str]: ...
    def is_dialog_visible(self) -> bool: ...
    def is_choice_panel_visible(self) -> bool: ...
    def dialog_text(self) -> str: ...
    def background_image_path(self) -> str | None: ...
    def base_font_size_px(self) -> int: ...

# 定义宿主需要提供的 UI 更新回调
class _ChatUIActions:
    """由宿主在绑定时填充，ChatUIContext 的更新操作最终调用这些回调。"""
    __slots__ = (
        "set_notification_hint",
        "set_input_draft",
        "clear_input_draft",
        "set_choice_options",
        "set_dialog_html",
        "mount_chat_ui_contributions",
    )

    def __init__(
        self,
        set_notification_hint: Callable[[str], None],
        set_input_draft: Callable[[str], None],
        clear_input_draft: Callable[[], None],
        set_choice_options: Callable[[List[str]], None],
        set_dialog_html: Callable[[str], None],
        mount_chat_ui_contributions: Callable[[list], None],
    ):
        self.set_notification_hint = set_notification_hint
        self.set_input_draft = set_input_draft
        self.clear_input_draft = clear_input_draft
        self.set_choice_options = set_choice_options
        self.set_dialog_html = set_dialog_html
        self.mount_chat_ui_contributions = mount_chat_ui_contributions


class _ChatUIUpdater(QObject):
    """只负责在主线程触发更新，不再包含任何窗口逻辑。"""
    set_notification_hint = Signal(str)
    set_input_draft = Signal(str)
    clear_input_draft = Signal()
    set_choice_options = Signal(object)
    set_dialog_html = Signal(str)
    mount_chat_ui_contributions = Signal(object)


class ChatUIContext:
    __slots__ = ("_state_proxy", "_submit_user_text", "_signals", "_updater", "_actions")

    def __init__(
        self,
        *,
        state_proxy: _ChatUIStateProxy,
        submit_user_text: Callable[[str], None] | None,
        ui_actions: _ChatUIActions,
        signals: ChatUISignalBridge | None = None,
    ) -> None:
        self._state_proxy = state_proxy
        self._submit_user_text = submit_user_text
        self._signals = signals if signals is not None else get_chat_ui_signal_bridge()
        self._actions = ui_actions

        self._updater = _ChatUIUpdater()
        # 信号连接到 ui_actions 中的回调，线程安全
        self._updater.set_notification_hint.connect(
            self._actions.set_notification_hint, Qt.ConnectionType.QueuedConnection
        )
        self._updater.set_input_draft.connect(
            self._actions.set_input_draft, Qt.ConnectionType.QueuedConnection
        )
        self._updater.clear_input_draft.connect(
            self._actions.clear_input_draft, Qt.ConnectionType.QueuedConnection
        )
        self._updater.set_choice_options.connect(
            lambda opts: self._actions.set_choice_options(list(opts)),
            Qt.ConnectionType.QueuedConnection,
        )
        self._updater.set_dialog_html.connect(
            self._actions.set_dialog_html, Qt.ConnectionType.QueuedConnection
        )
        self._updater.mount_chat_ui_contributions.connect(
            lambda contrib: self._actions.mount_chat_ui_contributions(list(contrib)),
            Qt.ConnectionType.QueuedConnection,
        )

    @classmethod
    def bind(
        cls,
        *,
        state_proxy: _ChatUIStateProxy,
        ui_actions: _ChatUIActions,
        submit_user_text: Callable[[str], None] | None = None,
    ) -> ChatUIContext:
        return cls(
            state_proxy=state_proxy,
            submit_user_text=submit_user_text,
            ui_actions=ui_actions,
        )

    @property
    def signals(self) -> ChatUISignalBridge:
        return self._signals

    # --- 查询（委托给 state_proxy）---
    def notification_hint(self) -> str:
        return self._state_proxy.notification_hint()

    def input_draft(self) -> str:
        return self._state_proxy.input_draft()

    def choice_options(self) -> List[str]:
        return list(self._state_proxy.choice_options())

    def is_dialog_visible(self) -> bool:
        return self._state_proxy.is_dialog_visible()

    def is_choice_panel_visible(self) -> bool:
        return self._state_proxy.is_choice_panel_visible()

    def dialog_text(self) -> str:
        return self._state_proxy.dialog_text()

    def background_image_path(self) -> str | None:
        return self._state_proxy.background_image_path()

    def base_font_size_px(self) -> int:
        return self._state_proxy.base_font_size_px()

    # --- 更新（通过信号 → ui_actions）---
    def set_notification_hint(self, message: str) -> None:
        self._updater.set_notification_hint.emit(message)

    def set_input_draft(self, text: str) -> None:
        self._updater.set_input_draft.emit(text)

    def clear_input_draft(self) -> None:
        self._updater.clear_input_draft.emit()

    def set_choice_options(self, option_list: List[str]) -> None:
        self._updater.set_choice_options.emit(option_list)

    def set_dialog_html(self, html: str) -> None:
        self._updater.set_dialog_html.emit(html)

    def submit_user_message(self, text: str) -> None:
        if self._submit_user_text is None:
            raise RuntimeError(
                "ChatUIContext：未绑定 submit_user_text，无法代用户投递（宿主应传入 wire_user_input_plugins 返回值）"
            )
        self._submit_user_text(text)

    def apply_chat_ui_plugin_widgets(self, contributions: list) -> None:
        if contributions:
            self._updater.mount_chat_ui_contributions.emit(contributions)