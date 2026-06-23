from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import QApplication

from sdk.chat_ui_context import (
    _ChatUIActions,
    ChatUIContext,
    get_chat_ui_context,
    set_chat_ui_context,
    try_get_chat_ui_context,
)
from ui.chat_ui.signal_bridge import ChatUISignalBridge


@dataclass
class _StateProxy:
    hint: str = "ready"
    draft: str = "draft"
    options: list[str] = field(default_factory=lambda: ["A", "B"])
    dialog_visible: bool = True
    choice_visible: bool = False
    dialog: str = "<b>Hello</b>"
    background: str | None = "bg.png"
    font_size: int = 42

    def notification_hint(self) -> str:
        return self.hint

    def input_draft(self) -> str:
        return self.draft

    def choice_options(self) -> list[str]:
        return self.options

    def is_dialog_visible(self) -> bool:
        return self.dialog_visible

    def is_choice_panel_visible(self) -> bool:
        return self.choice_visible

    def dialog_text(self) -> str:
        return self.dialog

    def background_image_path(self) -> str | None:
        return self.background

    def base_font_size_px(self) -> int:
        return self.font_size


def _process_events() -> None:
    app = QApplication.instance() or QApplication([])
    app.processEvents()


def _make_context(
    actions_seen: list[tuple[str, Any]],
) -> tuple[ChatUIContext, list[str]]:
    actions = _ChatUIActions(
        set_notification_hint=lambda value: actions_seen.append(("hint", value)),
        set_busy_bar=lambda text, duration: actions_seen.append(("busy", text, duration)),
        set_input_draft=lambda value: actions_seen.append(("draft", value)),
        clear_input_draft=lambda: actions_seen.append(("clear",)),
        set_choice_options=lambda values: actions_seen.append(("choices", values)),
        set_dialog_html=lambda value: actions_seen.append(("dialog", value)),
        mount_chat_ui_contributions=lambda values: actions_seen.append(("mount", values)),
    )
    submitted: list[str] = []
    return ChatUIContext(
        state_proxy=_StateProxy(),
        submit_user_text=submitted.append,
        ui_actions=actions,
        bridge=ChatUISignalBridge(),
    ), submitted


def test_context_singleton_helpers_raise_until_bound() -> None:
    set_chat_ui_context(None)

    assert try_get_chat_ui_context() is None
    try:
        get_chat_ui_context()
    except RuntimeError as exc:
        assert "ChatUIContext" in str(exc)
    else:
        raise AssertionError("get_chat_ui_context should fail before binding")

    seen: list[tuple[str, Any]] = []
    context, _submitted = _make_context(seen)
    set_chat_ui_context(context)

    assert try_get_chat_ui_context() is context
    assert get_chat_ui_context() is context

    set_chat_ui_context(None)


def test_context_reads_state_and_emits_ui_actions(qtbot) -> None:
    seen: list[tuple[str, Any]] = []
    context, submitted = _make_context(seen)

    assert context.notification_hint() == "ready"
    assert context.input_draft() == "draft"
    assert context.choice_options() == ["A", "B"]
    assert context.is_dialog_visible() is True
    assert context.is_choice_panel_visible() is False
    assert context.dialog_text() == "<b>Hello</b>"
    assert context.background_image_path() == "bg.png"
    assert context.base_font_size_px() == 42

    context.set_notification_hint("loading")
    context.set_busy_bar("working", 1.5)
    context.hide_busy_bar()
    context.set_input_draft("next")
    context.clear_input_draft()
    context.set_choice_options(["yes", "no"])
    context.set_dialog_html("<i>Updated</i>")
    context.apply_chat_ui_plugin_widgets([])
    context.apply_chat_ui_plugin_widgets([{"widget": "demo"}])

    qtbot.waitUntil(lambda: len(seen) == 8)
    assert seen == [
        ("hint", "loading"),
        ("busy", "working", 1.5),
        ("busy", "", 0.0),
        ("draft", "next"),
        ("clear",),
        ("choices", ["yes", "no"]),
        ("dialog", "<i>Updated</i>"),
        ("mount", [{"widget": "demo"}]),
    ]

    context.submit_user_message("hello")
    assert submitted == ["hello"]


def test_submit_user_message_requires_host_callback() -> None:
    actions = _ChatUIActions(
        set_notification_hint=lambda value: None,
        set_busy_bar=lambda text, duration: None,
        set_input_draft=lambda value: None,
        clear_input_draft=lambda: None,
        set_choice_options=lambda values: None,
        set_dialog_html=lambda value: None,
        mount_chat_ui_contributions=lambda values: None,
    )
    context = ChatUIContext(
        state_proxy=_StateProxy(),
        submit_user_text=None,
        ui_actions=actions,
        bridge=ChatUISignalBridge(),
    )

    try:
        context.submit_user_message("hello")
    except RuntimeError as exc:
        assert "submit_user_text" in str(exc)
    else:
        raise AssertionError("submit_user_message should fail without callback")


def test_event_subscription_helpers_wire_and_disconnect_signals() -> None:
    seen: list[tuple[str, tuple[Any, ...]]] = []
    context, _submitted = _make_context([])
    bridge = context._bridge
    cases = [
        ("on_message_submitted", "message_submitted", ("hello",)),
        ("on_reroll_requested", "reroll_requested", ()),
        ("on_open_chat_history_dialog", "open_chat_history_dialog", ()),
        ("on_change_voice_language", "change_voice_language", ("ja",)),
        ("on_close_window", "close_window", ()),
        ("on_clear_chat_history", "clear_chat_history", ()),
        ("on_skip_speech_signal", "skip_speech_signal", ()),
        ("on_llm_reply_finished", "llm_reply_finished", ()),
        ("on_pause_asr_signal", "pause_asr_signal", ()),
        ("on_copy_chat_history_to_clipboard", "copy_chat_history_to_clipboard", ()),
        ("on_revert_chat_history", "revert_chat_history", (3,)),
        ("on_option_selected", "option_selected", ("Choice",)),
        ("on_llm_response_received", "llm_response_received", ({"ok": True},)),
        ("on_background_image_changed", "background_image_changed", ("next.png",)),
        ("on_notification_changed", "notification_changed", ("updated",)),
        ("on_display_words_changed", "display_words_changed", ("words",)),
        ("on_numeric_info_changed", "numeric_info_changed", ("42",)),
        ("on_user_input_started", "user_input_started", ()),
        ("on_user_input_ended", "user_input_ended", ()),
        ("on_mic_transcription_update", "mic_transcription_update", ("draft", True)),
        ("on_mic_asr_state_changed", "mic_asr_state_changed", (False,)),
        ("on_mic_asr_pause_requested", "mic_asr_pause_requested", ()),
        ("on_mic_asr_resume_requested", "mic_asr_resume_requested", ()),
        ("on_mic_send_final_transcription", "mic_send_final_transcription", ()),
        ("on_cg_display_changed", "cg_display_changed", (True,)),
        ("on_dialog_typing_finished", "dialog_typing_finished", ()),
        ("on_dialog_area_clicked", "dialog_area_clicked", ()),
        ("on_sprite_frame_updated", "sprite_frame_updated", (object(),)),
    ]

    for method_name, signal_name, args in cases:
        disconnect = getattr(context, method_name)(
            lambda *values, _method=method_name: seen.append((_method, values))
        )
        getattr(bridge, signal_name).emit(*args)
        assert seen[-1] == (method_name, args)
        before = len(seen)
        disconnect()
        getattr(bridge, signal_name).emit(*args)
        _process_events()
        assert len(seen) == before
