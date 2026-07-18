"""Bind :class:`~sdk.chat_ui_context.ChatUIContext` and wire the signal bridge for the desktop chat entry (main)."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from config.config_manager import ConfigManager
from core.messaging.dialog_tokens import is_option_history_name
from core.sprite.chat_history import (
    clear_chat_history,
    copy_chat_history_to_clipboard,
    extract_valid_dialog_from_messages,
    revert_chat_history,
)
from sdk.messages import TTSOutputMessage
from core.plugins.plugin_host import collect_chat_ui_contributions
from llm.llm_manager import LLMManager
from sdk.chat_ui_context import ChatUIContext, set_chat_ui_context


def install_chat_ui_context(
    window: Any,
    *,
    emit_user_text: Callable[[str], None] | None,
) -> ChatUIContext:
    """Create context from window factories, register globals, apply desktop plugin widgets."""
    state_proxy = window._make_state_proxy()
    ui_actions = window._make_ui_actions()
    ctx = ChatUIContext.bind(
        state_proxy=state_proxy,
        ui_actions=ui_actions,
        submit_user_text=emit_user_text,
    )
    set_chat_ui_context(ctx)
    ctx.apply_chat_ui_plugin_widgets(collect_chat_ui_contributions())
    return ctx


def _on_voice_language_changed(
    window: Any, tts_manager: Any, voice_ui_lang: str
) -> None:
    """菜单「语音语言」仅驱动 TTS；默认识别语言跟随界面语言（见 system_config / API 页）。"""
    if tts_manager is not None:
        tts_manager.set_language(voice_ui_lang)


def wire_chat_ui_bridge(
    ctx: ChatUIContext,
    *,
    window: Any,
    app: Any,
    emit_user_text: Callable[[str], None] | None,
    chat_history: list,
    history_file: str,
    llm_manager: LLMManager,
    audio_path_queue: Any,
    tts_manager: Any,
    ui_worker: Any,
    tr_i18n: Callable[..., str],
) -> None:
    """Connect bridge slots to queues, LLM, and history actions."""

    def _tr(key: str, **kwargs: Any) -> str:
        if kwargs:
            return tr_i18n(key, **kwargs)
        return tr_i18n(key)

    def on_message_submitted(message: str) -> None:
        print(_tr("main.print_submitted", message=message))
        if emit_user_text is None:
            ctx.set_notification_hint(_tr("main.notify_chat"))
            return

        emit_user_text(message)
        ctx.set_notification_hint(_tr("main.notify_submitted"))

    def on_reroll() -> None:
        from core.sprite.chat_history import pop_last_assistant_turn
        messages = llm_manager.get_messages()
        # 先清理中断的 tool_calls，再 pop 最近一次问答
        llm_manager._strip_orphaned_tool_calls()
        pop_last_assistant_turn(chat_history, messages)
        last_msg = getattr(window, "_last_user_message", "")
        if last_msg and emit_user_text is not None:
            emit_user_text(last_msg)
        ctx.set_notification_hint(_tr("main.notify_reroll"))

    ctx.on_message_submitted(on_message_submitted)
    ctx.on_reroll_requested(on_reroll)
    ctx.on_open_chat_history_dialog(
        lambda: window.open_history_dialog(chat_history)
    )
    ctx.on_change_voice_language(
        lambda lang: _on_voice_language_changed(window, tts_manager, lang)
    )
    def _on_chat_ui_close() -> None:
        try:
            window.hide()
        except Exception:
            pass
        # 如果最后一条消息是 assistant 带 tool_calls 但无 tool 回执，补上「用户中断」
        msgs = llm_manager.get_messages()
        if msgs:
            last = msgs[-1]
            if last.get("role") == "assistant" and last.get("tool_calls"):
                import json as _json
                for tc in last["tool_calls"]:
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "content": _json.dumps({"error": "用户中断"}),
                    })
        app.quit()

    ctx.on_close_window(_on_chat_ui_close)
    if audio_path_queue is not None:
        ctx.on_clear_chat_history(
            lambda: clear_chat_history(
                history_file=history_file,
                ui_queue=audio_path_queue,
                llm_manager=llm_manager,
            )
        )
    if ui_worker is not None and hasattr(ui_worker, "skip_speech"):
        ctx.on_skip_speech_signal(lambda: ui_worker.skip_speech())

    ctx.on_copy_chat_history_to_clipboard(copy_chat_history_to_clipboard)
    ctx.on_revert_chat_history(
        lambda index: revert_chat_history(
            user_index=index,
            llm_manager=llm_manager,
            hist=chat_history,
            window=window,
        )
    )


def restore_session_ui(
    messages: list,
    *,
    audio_path_queue: Any,
    window: Any,
    config: ConfigManager,
    tr_i18n: Callable[..., str],
) -> bool:
    """Re-queue last dialog / bgm / background after loading a history file."""
    def _tr(key: str, **kwargs: Any) -> str:
        if kwargs:
            return tr_i18n(key, **kwargs)
        return tr_i18n(key)

    try:
        bgm_path = config.config.system_config.bgm_path
        bg_path = config.config.system_config.background_path
        if bgm_path:
            audio_path_queue.put(
                TTSOutputMessage(
                    audio_path=bgm_path,
                    character_name="bgm",
                    sprite="-1",
                    is_system_message=True,
                )
            )
        if bg_path:
            window.setBackgroundImage(bg_path)
    except Exception as e:
        print(_tr("main.print_bg_fail", e=str(e)))
        traceback.print_exc()

    if not messages:
        return False

    restored_character_sprite = False
    try:
        dialog = extract_valid_dialog_from_messages(messages)
        if not dialog:
            raise ValueError(_tr("main.err_no_valid_dialog"))

        # pop trailing choice/options so we can re-queue it with the right flags
        last_choice: dict | None = None
        if dialog and is_option_history_name(
            dialog[-1].get("character_name", "")
        ):
            last_choice = dialog.pop()

        # strip trailing narration (sprite "-1") that trails after the last
        # character sprite line
        trailing_system: list = []
        while dialog and (
            dialog[-1].get("sprite", "-1") == "-1"
            or dialog[-1].get("sprite", "-1") == -1
        ):
            name = dialog[-1].get("character_name", "")
            if is_option_history_name(name):
                break
            trailing_system.append(dialog.pop())

        # replay trailing narration as system messages (e.g. 旁白)
        for item in reversed(trailing_system):
            audio_path_queue.put(
                TTSOutputMessage(
                    audio_path="",
                    character_name=item.get("character_name", ""),
                    speech=item.get("speech"),
                    sprite="-1",
                    is_system_message=True,
                )
            )

        # put the last character-sprite line as the current display state
        if dialog:
            _last = dialog[-1]
            audio_path_queue.put(
                TTSOutputMessage(
                    audio_path="",
                    character_name=_last.get("character_name", ""),
                    speech=_last.get("speech", ""),
                    sprite=_last.get("sprite", "-1"),
                    is_system_message=False,
                    timeout=0,
                )
            )
            restored_character_sprite = True

        # finally, re-queue the choice so that OptionsUiHandler picks it up
        if last_choice is not None:
            audio_path_queue.put(
                TTSOutputMessage(
                    audio_path="",
                    name=last_choice.get("character_name", "CHOICE"),
                    text=last_choice.get("speech", ""),
                    sprite="-1",
                    is_system_message=True,
                )
            )
    except Exception as e:
        traceback.print_exc()
        print(_tr("main.print_restore_fail", e=str(e)))
        return False

    return restored_character_sprite
