"""Dispatch transport-neutral commands for an active chat session."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from application.chat.history_state import (
    clear_chat_history,
    pop_last_assistant_turn_payload,
    revert_chat_history,
)
from application.chat.manage_branches import (
    ConversationBranchManager,
    SubmitRuntimeText,
)
from core.chat_history.storage import (
    chat_history_active_path,
    remove_chat_history_storage,
)


class TranslateText(Protocol):
    def __call__(self, key: str, **kwargs: object) -> str: ...


@dataclass(frozen=True, slots=True)
class ChatCommandRequest:
    """A command after its transport envelope has been parsed."""

    type: str
    payload: object = None
    command_id: str = ""


@dataclass(frozen=True, slots=True)
class ChatCommandResult:
    """Transport-neutral execution result used to build an acknowledgement."""

    ok: bool
    error: str = ""


@dataclass(frozen=True, slots=True)
class ChatCommandUiBindings:
    """Presentation ports needed by command use cases."""

    clear_options: Callable[[], None]
    sync_history: Callable[[], None]
    notify: Callable[[str], None]
    clear_tool_confirmation: Callable[[str], None]
    handle_playback_signal: Callable[[str, str, str, str], None] | None = None
    skip_speech: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class ChatCommandBindings:
    """Session ports and state composed by the process entry point."""

    submit_text: SubmitRuntimeText
    can_submit_text: Callable[[], bool]
    shutdown_session: Callable[[], None]
    resolve_tool_confirmation: Callable[[str, str], bool]
    ui: ChatCommandUiBindings
    translate: TranslateText


class ChatCommandDispatcher:
    """Execute all realtime chat commands without knowing WebSocket details."""

    def __init__(
        self,
        *,
        bindings: ChatCommandBindings,
        config: Any,
        llm_manager: Any,
        runtime_asr: Any,
        chat_turn_service: Any,
        branch_manager: ConversationBranchManager,
        chat_history: MutableSequence[Any],
        last_user_message: Mapping[str, object],
        presentation_queue: Any,
        history_argument: str = "",
        history_presenter: Any = None,
        tts_manager: Any = None,
    ) -> None:
        self.bindings = bindings
        self.config = config
        self.llm_manager = llm_manager
        self.runtime_asr = runtime_asr
        self.chat_turn_service = chat_turn_service
        self.branch_manager = branch_manager
        self.chat_history = chat_history
        self.last_user_message = last_user_message
        self.presentation_queue = presentation_queue
        self.history_argument = str(history_argument or "")
        self.history_presenter = history_presenter
        self.tts_manager = tts_manager

        self._handlers: dict[str, Callable[[object], None]] = {
            "close-session": self._close_session,
            "send-message": self._send_message,
            "submit-option": self._submit_option,
            "update-turn-options": self._update_turn_options,
            "chat-input-state": self._update_input_state,
            "flush-input-batch": self._flush_input_batch,
            "cancel-input-batch": self._cancel_input_batch,
            "audio-playback-signal": self._handle_playback_signal,
            "skip-speech": self._skip_speech,
            "dialog-advance": self._skip_speech,
            "pause-asr": self._pause_asr,
            "resume-asr": self._resume_asr,
            "reroll": self._reroll,
            "clear-history": self._clear_history,
            "change-voice-language": self._change_voice_language,
            "revert-history": self._revert_history,
            "fork-history": self._fork_history,
            "switch-branch": self._switch_branch,
            "rename-branch": self._rename_branch,
        }

    def execute(self, request: ChatCommandRequest) -> ChatCommandResult:
        """Execute one request and convert failures into an ack-ready result."""

        try:
            handler = self._handlers.get(request.type)
            if handler is None:
                raise ValueError(f"未知实时聊天命令：{request.type}")
            handler(request.payload)
            return ChatCommandResult(ok=True)
        except Exception as exc:
            error = str(exc)
            self.bindings.ui.notify(error)
            return ChatCommandResult(ok=False, error=error)

    def _close_session(self, _payload: object) -> None:
        self.bindings.shutdown_session()

    def _send_message(self, payload: object) -> None:
        self.runtime_asr.pause_for_turn()
        if isinstance(payload, Mapping):
            raw_attachments = payload.get("attachments")
            self.bindings.submit_text(
                str(payload.get("text") or ""),
                attachments=(
                    list(raw_attachments) if isinstance(raw_attachments, list) else []
                ),
                notify_key=None,
            )
            return
        self.bindings.submit_text(str(payload or ""), notify_key=None)

    def _submit_option(self, payload: object) -> None:
        if isinstance(payload, Mapping) and payload.get("kind") == "tool-confirmation":
            confirmation_id = str(payload.get("confirmationId") or "").strip()
            action = str(payload.get("action") or "").strip().casefold()
            if (
                not confirmation_id
                or len(confirmation_id) > 128
                or action not in {"confirm", "cancel"}
            ):
                raise ValueError("Tool confirmation response is invalid.")
            if not self.bindings.resolve_tool_confirmation(confirmation_id, action):
                raise ValueError(
                    "Tool confirmation is stale or does not match the active prompt."
                )
            self.bindings.ui.clear_tool_confirmation(confirmation_id)
            return
        if isinstance(payload, Mapping):
            raise ValueError("Option selection must be a string.")
        self.runtime_asr.pause_for_turn()
        self.bindings.submit_text(str(payload or ""))

    def _update_turn_options(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("Chat turn options must be an object.")
        interrupt_enabled = payload.get("interruptEnabled")
        batch_enabled = payload.get("batchEnabled")
        batch_idle_seconds = payload.get("batchIdleSeconds")
        if not isinstance(interrupt_enabled, bool) or not isinstance(
            batch_enabled, bool
        ):
            raise ValueError("Chat turn switches must be boolean values.")
        if isinstance(batch_idle_seconds, bool) or not isinstance(
            batch_idle_seconds, (int, float)
        ):
            raise ValueError("Batch input timeout must be numeric.")
        timeout = float(batch_idle_seconds)
        if not 0.3 <= timeout <= 120.0:
            raise ValueError("Batch input timeout must be between 0.3 and 120 seconds.")

        self.chat_turn_service.update_options(
            replace(
                self.chat_turn_service.options,
                interrupt_enabled=interrupt_enabled,
                batch_enabled=batch_enabled,
                batch_idle_seconds=timeout,
            )
        )
        api_config = self.config.config.api_config.model_copy(deep=True)
        api_config.interrupt_enabled = interrupt_enabled
        api_config.is_batch_input_enabled = batch_enabled
        api_config.batch_input_timeout = timeout
        self.config.config.api_config = api_config

    def _update_input_state(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("Chat input state must be an object.")
        self.chat_turn_service.input_changed(
            has_text=bool(payload.get("hasText")),
            composing=bool(payload.get("composing")),
        )

    def _flush_input_batch(self, _payload: object) -> None:
        self.chat_turn_service.flush()

    def _cancel_input_batch(self, _payload: object) -> None:
        self.chat_turn_service.cancel_pending_batch()

    def _handle_playback_signal(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("Audio playback signal must be an object.")
        playback_id = str(payload.get("playbackId") or "").strip()
        renderer_id = str(payload.get("rendererId") or "").strip()
        playback_state = str(payload.get("state") or "").strip()
        error = str(payload.get("error") or "")
        if (
            not playback_id
            or not renderer_id
            or playback_state
            not in {
                "started",
                "finished",
                "interrupted",
                "failed",
            }
        ):
            raise ValueError("Audio playback signal is invalid.")
        if self.bindings.ui.handle_playback_signal is None:
            raise RuntimeError("Audio playback controller is unavailable.")
        self.bindings.ui.handle_playback_signal(
            playback_id,
            playback_state,
            error,
            renderer_id,
        )

    def _skip_speech(self, _payload: object) -> None:
        if self.bindings.ui.skip_speech is not None:
            self.bindings.ui.skip_speech()

    def _pause_asr(self, _payload: object) -> None:
        self.runtime_asr.user_pause()

    def _resume_asr(self, _payload: object) -> None:
        self.runtime_asr.user_resume()

    def _reroll(self, _payload: object) -> None:
        messages = self.llm_manager.get_messages()
        strip_orphaned = getattr(self.llm_manager, "_strip_orphaned_tool_calls", None)
        if callable(strip_orphaned):
            strip_orphaned()
        reroll_payload = pop_last_assistant_turn_payload(self.chat_history, messages)
        reroll_text = str(reroll_payload.get("text") or "")
        reroll_attachments = list(reroll_payload.get("attachments") or [])
        if not reroll_text and not reroll_attachments:
            reroll_text = str(self.last_user_message.get("text") or "")
            reroll_attachments = list(self.last_user_message.get("attachments") or [])
        self.bindings.ui.clear_options()
        self.bindings.ui.sync_history()
        if (reroll_text or reroll_attachments) and self.bindings.can_submit_text():
            self.bindings.submit_text(
                reroll_text,
                attachments=reroll_attachments,
                ignore_unavailable_attachments=True,
                notify_key=None,
            )
            self.bindings.ui.notify(self.bindings.translate("main.notify_reroll"))

    def _clear_history(self, _payload: object) -> None:
        if self.presentation_queue is None:
            raise RuntimeError("聊天历史清理队列未就绪。")
        self.chat_turn_service.cancel_pending_batch()
        if self.history_argument:
            history_target = str(chat_history_active_path(self.history_argument))
            remove_chat_history_storage(self.history_argument)
        else:
            history_target = str(Path("data/chat_history") / "_temp.json")
        clear_chat_history(history_target, self.presentation_queue, self.llm_manager)
        self.branch_manager.reset()
        self.branch_manager.persist()
        self.bindings.ui.clear_options()
        self.bindings.ui.sync_history()
        self.branch_manager.publish_tree()

    def _change_voice_language(self, payload: object) -> None:
        voice_language = str(payload or "").strip().lower()
        if not voice_language:
            raise ValueError("语音语言不能为空。")
        if self.tts_manager is not None:
            self.tts_manager.set_language(voice_language)
        voice_labels = {
            "en": "template.voice_lang_en",
            "zh": "template.voice_lang_zh",
            "ja": "template.voice_lang_ja",
            "yue": "template.voice_lang_yue",
        }
        system_config = self.config.config.system_config.model_copy(deep=True)
        system_config.voice_language = voice_language
        self.config.config.system_config = system_config
        self.config.save_system_config()
        language_label = self.bindings.translate(
            voice_labels.get(voice_language, "template.voice_lang_en")
        )
        self.bindings.ui.notify(
            self.bindings.translate(
                "desktop.menu.notify_voice_language",
                lang=language_label,
            )
        )

    def _revert_history(self, payload: object) -> None:
        index = int(payload)
        self.chat_turn_service.cancel_pending_batch()
        revert_chat_history(
            index,
            llm_manager=self.llm_manager,
            hist=self.chat_history,
            window=self.history_presenter,
        )
        self.bindings.ui.clear_options()
        self.bindings.ui.sync_history()

    def _fork_history(self, payload: object) -> None:
        raw_payload = (
            payload if isinstance(payload, Mapping) else {"userIndex": payload}
        )
        self.branch_manager.fork(
            int(raw_payload.get("userIndex")),
            branch_id=str(raw_payload.get("branchId") or "").strip(),
        )

    def _switch_branch(self, payload: object) -> None:
        self.branch_manager.switch(str(payload or ""))
        self.bindings.ui.notify("已切换对话分支。")

    def _rename_branch(self, payload: object) -> None:
        raw_payload = payload if isinstance(payload, Mapping) else {}
        self.branch_manager.rename(
            str(raw_payload.get("branchId") or ""),
            str(raw_payload.get("label") or ""),
        )
        self.bindings.ui.notify("已重命名对话分支。")
