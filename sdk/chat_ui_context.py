"""Chat UI 宿主绑定：供插件安全查询状态、投递 UI 更新，并通过回调订阅聊天窗事件。"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Protocol

from PySide6.QtCore import QObject, Qt, Signal

from ui.chat_ui.signal_bridge import ChatUISignalBridge, get_chat_ui_signal_bridge

__all__ = [
    "ChatUIContext",
    "get_chat_ui_context",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
]

_chat_ui_ctx: Optional["ChatUIContext"] = None


def _wire_handler(signal_bound: Any, handler: Callable[..., object]) -> Callable[[], None]:
    signal_bound.connect(handler)

    def disconnect() -> None:
        try:
            signal_bound.disconnect(handler)
        except (TypeError, RuntimeError):
            pass

    return disconnect


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


class _ChatUIActions:
    """由宿主在绑定时填充，ChatUIContext 的更新操作最终调用这些回调。"""

    __slots__ = (
        "set_notification_hint",
        "set_busy_bar",
        "set_input_draft",
        "clear_input_draft",
        "set_choice_options",
        "set_dialog_html",
        "mount_chat_ui_contributions",
    )

    def __init__(
        self,
        set_notification_hint: Callable[[str], None],
        set_busy_bar: Callable[[str, float], None],
        set_input_draft: Callable[[str], None],
        clear_input_draft: Callable[[], None],
        set_choice_options: Callable[[List[str]], None],
        set_dialog_html: Callable[[str], None],
        mount_chat_ui_contributions: Callable[[list], None],
    ) -> None:
        self.set_notification_hint = set_notification_hint
        self.set_busy_bar = set_busy_bar
        self.set_input_draft = set_input_draft
        self.clear_input_draft = clear_input_draft
        self.set_choice_options = set_choice_options
        self.set_dialog_html = set_dialog_html
        self.mount_chat_ui_contributions = mount_chat_ui_contributions


class _ChatUIUpdater(QObject):
    """只负责在主线程触发更新，不再包含任何窗口逻辑。"""

    set_notification_hint = Signal(str)
    set_busy_bar = Signal(str, float)
    set_input_draft = Signal(str)
    clear_input_draft = Signal()
    set_choice_options = Signal(object)
    set_dialog_html = Signal(str)
    mount_chat_ui_contributions = Signal(object)


class ChatUIContext:
    """
    面向插件的安全入口：读取状态、投递 UI 更新、用 ``on_*`` 注册事件回调。

    不要也不会暴露底层 Qt ``Signal`` 对象；每个 ``on_*`` 返回 ``disconnect`` 可调用，
    用于注销该回调（同 ``handler`` 引用需与注册时一致）。
    """

    __slots__ = ("_state_proxy", "_submit_user_text", "_bridge", "_updater", "_actions")

    def __init__(
        self,
        *,
        state_proxy: _ChatUIStateProxy,
        submit_user_text: Callable[[str], None] | None,
        ui_actions: _ChatUIActions,
        bridge: ChatUISignalBridge | None = None,
    ) -> None:
        self._state_proxy = state_proxy
        self._submit_user_text = submit_user_text
        self._bridge = bridge if bridge is not None else get_chat_ui_signal_bridge()
        self._actions = ui_actions

        self._updater = _ChatUIUpdater()
        self._updater.set_notification_hint.connect(
            self._actions.set_notification_hint, Qt.ConnectionType.QueuedConnection
        )
        self._updater.set_busy_bar.connect(
            self._actions.set_busy_bar, Qt.ConnectionType.QueuedConnection
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

    def on_message_submitted(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.message_submitted, handler)

    def on_open_chat_history_dialog(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.open_chat_history_dialog, handler)

    def on_change_voice_language(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.change_voice_language, handler)

    def on_close_window(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.close_window, handler)

    def on_clear_chat_history(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.clear_chat_history, handler)

    def on_skip_speech_signal(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.skip_speech_signal, handler)

    def on_llm_reply_finished(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.llm_reply_finished, handler)

    def on_pause_asr_signal(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.pause_asr_signal, handler)

    def on_copy_chat_history_to_clipboard(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.copy_chat_history_to_clipboard, handler)

    def on_revert_chat_history(
        self, handler: Callable[[int], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.revert_chat_history, handler)

    def on_option_selected(self, handler: Callable[[str], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.option_selected, handler)

    def on_llm_response_received(
        self, handler: Callable[[object], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.llm_response_received, handler)

    def on_background_image_changed(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.background_image_changed, handler)

    def on_notification_changed(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.notification_changed, handler)

    def on_display_words_changed(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.display_words_changed, handler)

    def on_numeric_info_changed(
        self, handler: Callable[[str], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.numeric_info_changed, handler)

    def on_user_input_started(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.user_input_started, handler)

    def on_user_input_ended(self, handler: Callable[[], None]) -> Callable[[], None]:
        return _wire_handler(self._bridge.user_input_ended, handler)

    def on_mic_transcription_update(
        self, handler: Callable[[str, bool], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.mic_transcription_update, handler)

    def on_mic_asr_state_changed(
        self, handler: Callable[[bool], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.mic_asr_state_changed, handler)

    def on_mic_asr_pause_requested(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.mic_asr_pause_requested, handler)

    def on_mic_asr_resume_requested(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.mic_asr_resume_requested, handler)

    def on_mic_send_final_transcription(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.mic_send_final_transcription, handler)

    def on_cg_display_changed(
        self, handler: Callable[[bool], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.cg_display_changed, handler)

    def on_dialog_typing_finished(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.dialog_typing_finished, handler)

    def on_dialog_area_clicked(
        self, handler: Callable[[], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.dialog_area_clicked, handler)

    def on_sprite_frame_updated(
        self, handler: Callable[[object], None]
    ) -> Callable[[], None]:
        return _wire_handler(self._bridge.sprite_frame_updated, handler)

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

    def set_notification_hint(self, message: str) -> None:
        self._updater.set_notification_hint.emit(message)

    def set_busy_bar(self, text: str, duration_seconds: float = 3.0) -> None:
        """与宿主 ``setBusyBar`` 行为一致；空文案等价于隐藏。"""
        self._updater.set_busy_bar.emit(text, float(duration_seconds))

    def hide_busy_bar(self) -> None:
        self._updater.set_busy_bar.emit("", 0.0)

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
