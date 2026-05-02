"""
ChatUI 信号桥：把 :class:`~ui.chat_ui.chat_ui.ChatUIWindow` 及其关键子控件上的信号
同步转发到本模块单例 :class:`ChatUISignalBridge`，供插件只连接一处即可监听。

**窗口级信号**（定义在 ``ChatUIWindow`` 上，由 :func:`attach_chat_ui_window` 转发）

- 用户与菜单：``message_submitted``、``open_chat_history_dialog``、``change_voice_language``、
  ``clear_chat_history``、``copy_chat_history_to_clipboard``、``revert_chat_history``
- 语音 / LLM：``skip_speech_signal``、``llm_reply_finished``、``pause_asr_signal``、
  ``llm_response_received``（字典，非流式 ChatWorker 一次结果）
- 选项与展示：``option_selected``、``display_words_changed``、``numeric_info_changed``
- 输入框焦点：``user_input_started``（输入框获得焦点）、``user_input_ended``（失去焦点）
- 背景与提示：``background_image_changed``、``notification_changed``
- 生命周期：``close_window``

**子控件转发**（无同名窗口信号时，从 ``mic_button`` / ``cg_widget`` / ``dialog_label`` /
``display_thread`` 转发）

- 麦克风：``mic_transcription_update``、``mic_asr_state_changed``、``mic_asr_pause_requested``、
  ``mic_asr_resume_requested``、``mic_send_final_transcription``
- CG：``cg_display_changed``
- 对话框：``dialog_typing_finished``、``dialog_area_clicked``（气泡可点击区域）
- 立绘帧：``sprite_frame_updated``（``numpy.ndarray``，无图像线程时不触发）

**插件用法**

通过 :class:`~sdk.chat_ui_context.ChatUIContext` 的 ``on_*`` 注册回调（不推荐直接
``get_chat_ui_signal_bridge().connect``，以免与宿主/多插件连接语义纠缠）：

.. code-block:: python

    from sdk.chat_ui_context import try_get_chat_ui_context

    ctx = try_get_chat_ui_context()
    if ctx:
        unsub = ctx.on_message_submitted(lambda text: ...)

宿主导线仍使用 :func:`get_chat_ui_signal_bridge` 与窗口 :func:`attach_chat_ui_window` 转发。

**旧式直接连桥（仅高级 / 调试）**

.. code-block:: python

    from ui.chat_ui.signal_bridge import get_chat_ui_signal_bridge

    bridge = get_chat_ui_signal_bridge()
    bridge.message_submitted.connect(lambda text: ...)

窗口 ``__init__`` 结束时会 :func:`attach_chat_ui_window`；关闭时在 ``closeEvent`` 中
:func:`detach_chat_ui_window`。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

_logger = logging.getLogger(__name__)

_Relay = Tuple[Any, Callable[..., None]]
_relays: List[_Relay] = []
_attached_window: Optional[object] = None

_bridge: Optional["ChatUISignalBridge"] = None


class ChatUISignalBridge(QObject):
    """
    聚合 ChatUI 窗口与子控件的监听点；仅由本模块转发，插件请勿 ``emit``。
    """

    # --- ChatUIWindow ---
    message_submitted = Signal(str)
    open_chat_history_dialog = Signal()
    change_voice_language = Signal(str)
    close_window = Signal()
    clear_chat_history = Signal()
    skip_speech_signal = Signal()
    llm_reply_finished = Signal()
    pause_asr_signal = Signal()
    copy_chat_history_to_clipboard = Signal()
    revert_chat_history = Signal(int)

    option_selected = Signal(str)
    llm_response_received = Signal(object)
    background_image_changed = Signal(str)
    notification_changed = Signal(str)
    display_words_changed = Signal(str)
    numeric_info_changed = Signal(str)

    user_input_started = Signal()
    user_input_ended = Signal()

    # --- mic_button / ASR ---
    mic_transcription_update = Signal(str, bool)
    mic_asr_state_changed = Signal(bool)
    mic_asr_pause_requested = Signal()
    mic_asr_resume_requested = Signal()
    mic_send_final_transcription = Signal()

    # --- cg_widget ---
    cg_display_changed = Signal(bool)

    # --- dialog_label (TypingLabel) ---
    dialog_typing_finished = Signal()
    dialog_area_clicked = Signal()

    # --- ImageDisplayThread ---
    sprite_frame_updated = Signal(object)


def get_chat_ui_signal_bridge() -> ChatUISignalBridge:
    global _bridge
    if _bridge is None:
        _bridge = ChatUISignalBridge()
    return _bridge


def _relay0(bridge_sig: Any) -> Callable[[], None]:
    def _fn() -> None:
        bridge_sig.emit()

    return _fn


def _relay_bool(bridge_sig: Any) -> Callable[[bool], None]:
    def _fn(v: bool) -> None:
        bridge_sig.emit(v)

    return _fn


def _relay1_str(bridge_sig: Any) -> Callable[[str], None]:
    def _fn(s: str) -> None:
        bridge_sig.emit(s)

    return _fn


def _relay1_int(bridge_sig: Any) -> Callable[[int], None]:
    def _fn(n: int) -> None:
        bridge_sig.emit(n)

    return _fn


def _relay1_object(bridge_sig: Any) -> Callable[[object], None]:
    def _fn(o: object) -> None:
        bridge_sig.emit(o)

    return _fn


def _relay2_str_bool(bridge_sig: Any) -> Callable[[str, bool], None]:
    def _fn(s: str, partial: bool) -> None:
        bridge_sig.emit(s, partial)

    return _fn


def _connect_window_signal(
    window: object,
    b: ChatUISignalBridge,
    sig_name: str,
    factory: Callable[[Any], Callable[..., None]],
) -> None:
    if not hasattr(window, sig_name):
        _logger.warning("ChatUI bridge: window missing signal %r", sig_name)
        return
    bound = getattr(window, sig_name)
    if not hasattr(bound, "connect"):
        _logger.warning("ChatUI bridge: %r is not connectable", sig_name)
        return
    slot = factory(getattr(b, sig_name))
    bound.connect(slot)
    _relays.append((bound, slot))


def _connect_bound(
    bound: Any,
    bridge_sig: Any,
    factory: Callable[[Any], Callable[..., None]],
) -> None:
    if bound is None or not hasattr(bound, "connect"):
        return
    slot = factory(bridge_sig)
    bound.connect(slot)
    _relays.append((bound, slot))


def _wire_children(window: object, b: ChatUISignalBridge) -> None:
    mb = getattr(window, "mic_button", None)
    if mb is not None:
        asig = getattr(getattr(mb, "asr_signals", None), "transcription_update", None)
        _connect_bound(asig, b.mic_transcription_update, _relay2_str_bool)
        _connect_bound(mb.asr_state_changed, b.mic_asr_state_changed, _relay_bool)
        _connect_bound(mb.asr_pause_requested, b.mic_asr_pause_requested, _relay0)
        _connect_bound(mb.asr_resume_requested, b.mic_asr_resume_requested, _relay0)
        _connect_bound(
            mb.send_final_transcription, b.mic_send_final_transcription, _relay0
        )

    cg = getattr(window, "cg_widget", None)
    if cg is not None:
        _connect_bound(cg.cg_display_changed, b.cg_display_changed, _relay_bool)

    dlg = getattr(window, "dialog_label", None)
    if dlg is not None:
        _connect_bound(dlg.typingFinished, b.dialog_typing_finished, _relay0)
        _connect_bound(dlg.clicked, b.dialog_area_clicked, _relay0)

    dt = getattr(window, "display_thread", None)
    if dt is not None:
        us = getattr(dt, "update_signal", None)
        _connect_bound(us, b.sprite_frame_updated, _relay1_object)


def detach_chat_ui_window() -> None:
    global _attached_window
    for bound, slot in _relays:
        try:
            bound.disconnect(slot)
        except (TypeError, RuntimeError):
            pass
    _relays.clear()
    _attached_window = None


def attach_chat_ui_window(window: object) -> None:
    global _attached_window
    if _attached_window is not None and _attached_window is not window:
        detach_chat_ui_window()
    elif _attached_window is window:
        return

    b = get_chat_ui_signal_bridge()

    _connect_window_signal(window, b, "message_submitted", _relay1_str)
    _connect_window_signal(window, b, "open_chat_history_dialog", _relay0)
    _connect_window_signal(window, b, "change_voice_language", _relay1_str)
    _connect_window_signal(window, b, "close_window", _relay0)
    _connect_window_signal(window, b, "clear_chat_history", _relay0)
    _connect_window_signal(window, b, "skip_speech_signal", _relay0)
    _connect_window_signal(window, b, "llm_reply_finished", _relay0)
    _connect_window_signal(window, b, "pause_asr_signal", _relay0)
    _connect_window_signal(window, b, "copy_chat_history_to_clipboard", _relay0)
    _connect_window_signal(window, b, "revert_chat_history", _relay1_int)

    _connect_window_signal(window, b, "option_selected", _relay1_str)
    _connect_window_signal(window, b, "llm_response_received", _relay1_object)
    _connect_window_signal(window, b, "background_image_changed", _relay1_str)
    _connect_window_signal(window, b, "notification_changed", _relay1_str)
    _connect_window_signal(window, b, "display_words_changed", _relay1_str)
    _connect_window_signal(window, b, "numeric_info_changed", _relay1_str)
    _connect_window_signal(window, b, "user_input_started", _relay0)
    _connect_window_signal(window, b, "user_input_ended", _relay0)

    _wire_children(window, b)

    _attached_window = window
