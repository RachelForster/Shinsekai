"""Wire realtime input, branches, ASR, and commands into a chat session."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from application.chat.commands import (
    ChatCommandBindings,
    ChatCommandDispatcher,
    ChatCommandUiBindings,
)
from application.chat.history_state import chat_history, replay_history_entry
from application.chat.manage_branches import (
    ConversationBranchBindings,
    ConversationBranchManager,
)
from application.chat.presentation import StreamingHistoryPresenter
from application.chat.session_restore import replay_latest_dialog_sprite
from application.chat.startup import chat_history_is_present
from application.runtime.context import get_app_runtime, resolve_pending_tool_confirmation
from core.media.chat_attachments import resolve_chat_attachments


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StreamingSessionBindings:
    """Runtime collaborators created for one streaming chat session."""

    branch_manager: Any
    runtime_asr: Any
    submit_text: Any
    last_user_message: dict[str, object]


def wire_streaming_session(
    *,
    args: Any,
    config: Any,
    startup: Any,
    transport: Any,
    runtime: Any,
    ui_updates: Any,
    chat_turn_service: Any,
    shutdown_session: Any,
    translate: Any,
    create_asr_adapter: Any,
    save_history: Any,
) -> StreamingSessionBindings:
    """Connect realtime adapters to transport-neutral chat use cases."""

    wiring = _StreamingSessionWiring(
        args=args,
        config=config,
        startup=startup,
        transport=transport,
        runtime=runtime,
        ui_updates=ui_updates,
        chat_turn_service=chat_turn_service,
        shutdown_session=shutdown_session,
        translate=translate,
        create_asr_adapter=create_asr_adapter,
        save_history=save_history,
    )
    return wiring.wire()


class _StreamingSessionWiring:
    def __init__(
        self,
        *,
        args: Any,
        config: Any,
        startup: Any,
        transport: Any,
        runtime: Any,
        ui_updates: Any,
        chat_turn_service: Any,
        shutdown_session: Any,
        translate: Any,
        create_asr_adapter: Any,
        save_history: Any,
    ) -> None:
        self.args = args
        self.config = config
        self.startup = startup
        self.transport = transport
        self.runtime = runtime
        self.ui_updates = ui_updates
        self.chat_turn_service = chat_turn_service
        self.shutdown_session = shutdown_session
        self.translate = translate
        self.create_asr_adapter = create_asr_adapter
        self.save_history = save_history
        self.last_user_message: dict[str, object] = {
            "attachments": [],
            "text": "",
        }
        self.emit_user_text: Any | None = None
        self.branch_manager: Any | None = None
        self.runtime_asr: Any | None = None

    def wire(self) -> StreamingSessionBindings:
        from plugin_system.host import wire_user_input_plugins

        self.emit_user_text = (
            wire_user_input_plugins(
                self.runtime.input_queue,
                sink=self.chat_turn_service.submit,
            )
            if self.runtime.input_queue is not None
            else None
        )
        self.branch_manager = self._create_branch_manager()
        self.runtime_asr = self._create_streaming_asr()
        self._bind_asr_presentation_hooks()
        self.transport.bind_command_dispatcher(self._create_command_dispatcher())
        return StreamingSessionBindings(
            branch_manager=self.branch_manager,
            runtime_asr=self.runtime_asr,
            submit_text=self.submit_runtime_text,
            last_user_message=self.last_user_message,
        )

    def submit_runtime_text(
        self,
        text: str,
        *,
        attachments: list[dict[str, object]] | None = None,
        ignore_unavailable_attachments: bool = False,
        notify_key: str | None = "main.notify_submitted",
    ) -> bool:
        value = str(text or "").strip()
        try:
            resolved = resolve_chat_attachments(attachments)
        except (OSError, ValueError):
            if not ignore_unavailable_attachments:
                raise
            resolved = []
            for attachment in attachments or []:
                try:
                    resolved.extend(resolve_chat_attachments([attachment]))
                except (OSError, ValueError):
                    continue
        if not value and not resolved:
            return False
        payloads = [attachment.to_payload() for attachment in resolved]
        self.last_user_message["text"] = value
        self.last_user_message["attachments"] = payloads
        if self.emit_user_text is None:
            if notify_key:
                self.ui_updates.post_notification(self.translate("main.notify_chat"))
            return False
        accepted = self.emit_user_text(value, attachments=payloads)
        if accepted is False:
            return False
        if notify_key:
            self.ui_updates.post_notification(self.translate(notify_key))
        return True

    def _create_branch_manager(self) -> ConversationBranchManager:
        def replay_sprite(messages: list[Any]) -> None:
            runtime = get_app_runtime()
            replay_latest_dialog_sprite(
                messages,
                presentation_queue=runtime.presentation_queue,
                config=runtime.config,
                sprite_lookup_strategy=runtime.sprite_lookup_strategy,
                character_name_converter=runtime.opencc.convert,
            )

        manager = ConversationBranchManager(
            history_path=self.args.history,
            chat_history=chat_history,
            bindings=ConversationBranchBindings(
                get_messages=self.startup.llm_manager.get_messages,
                set_messages=self.startup.llm_manager.set_messages,
                cancel_pending_batch=self.chat_turn_service.cancel_pending_batch,
                persist_messages=lambda messages: self.save_history(
                    self.args.history,
                    messages,
                ),
                publish_tree=lambda tree: self.transport.emit(
                    {"type": "conversation.tree", "tree": tree}
                ),
                clear_options=lambda: self.transport.emit({"type": "options.clear"}),
                sync_history=self._sync_stream_history,
                replay_history=lambda entry: replay_history_entry(
                    StreamingHistoryPresenter(self.ui_updates),
                    str(entry),
                ),
                replay_sprite=replay_sprite,
                submit_text=self.submit_runtime_text,
            ),
        )
        manager.load(
            self.startup.messages,
            active_history_present=chat_history_is_present(self.args.history),
        )
        return manager

    def _create_streaming_asr(self) -> Any:
        from ai.asr.streaming_controller import StreamingASRController

        return StreamingASRController(
            adapter_factory=self.create_asr_adapter,
            emit_event=self.transport.emit,
            submit_final=self._submit_asr_text,
            on_loading_changed=self._set_asr_loading,
            on_error=self._report_asr_error,
            resume_delay_seconds=0.5,
        )

    def _submit_asr_text(self, text: str) -> bool:
        accepted = self.submit_runtime_text(text, notify_key=None)
        if not accepted:
            return False
        if self.chat_turn_service.options.batch_enabled:
            self.chat_turn_service.flush()
        self.transport.emit({"type": "status.change", "status": "generating"})
        return True

    def _set_asr_loading(self, loading: bool) -> None:
        if loading:
            self.ui_updates.post_busy_bar(
                self.translate("desktop.mic_loading_model"),
                0.0,
            )
        else:
            self.ui_updates.hide_busy_bar()

    def _report_asr_error(self, operation: str, exc: BaseException) -> None:
        logger.error(
            "Streaming ASR %s failed",
            operation,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"event": "asr.streaming.failed", "operation": operation},
        )
        self.ui_updates.post_notification(str(exc))

    def _bind_asr_presentation_hooks(self) -> None:
        original_finished = self.ui_updates.post_llm_reply_finished
        self.ui_updates.post_pause_asr = self.runtime_asr.pause_for_turn

        def finish_and_resume() -> None:
            original_finished()
            self.runtime_asr.reply_finished()

        self.ui_updates.post_llm_reply_finished = finish_and_resume

    def _create_command_dispatcher(self) -> ChatCommandDispatcher:
        ui_worker = self.runtime.ui_worker

        def handle_playback_signal(
            playback_id: str,
            playback_state: str,
            error: str,
            renderer_id: str,
        ) -> None:
            ui_worker.handle_playback_signal(
                playback_id,
                playback_state,
                error,
                renderer_id=renderer_id,
            )

        return ChatCommandDispatcher(
            bindings=ChatCommandBindings(
                submit_text=self.submit_runtime_text,
                can_submit_text=lambda: self.emit_user_text is not None,
                shutdown_session=self.shutdown_session,
                resolve_tool_confirmation=resolve_pending_tool_confirmation,
                ui=ChatCommandUiBindings(
                    clear_options=lambda: self.transport.emit(
                        {"type": "options.clear"}
                    ),
                    sync_history=self._sync_stream_history,
                    notify=self.ui_updates.post_notification,
                    clear_tool_confirmation=self._clear_tool_confirmation,
                    handle_playback_signal=(
                        handle_playback_signal
                        if ui_worker is not None
                        and hasattr(ui_worker, "handle_playback_signal")
                        else None
                    ),
                    skip_speech=(
                        ui_worker.skip_speech
                        if ui_worker is not None and hasattr(ui_worker, "skip_speech")
                        else None
                    ),
                ),
                translate=self.translate,
            ),
            config=self.config,
            llm_manager=self.startup.llm_manager,
            runtime_asr=self.runtime_asr,
            chat_turn_service=self.chat_turn_service,
            branch_manager=self.branch_manager,
            chat_history=chat_history,
            last_user_message=self.last_user_message,
            presentation_queue=self.runtime.presentation_queue,
            history_argument=self.args.history,
            history_presenter=StreamingHistoryPresenter(self.ui_updates),
            tts_manager=self.startup.tts_manager,
        )

    def _sync_stream_history(self) -> None:
        if hasattr(self.ui_updates, "sync_history_entries"):
            self.ui_updates.sync_history_entries()

    def _clear_tool_confirmation(self, confirmation_id: str) -> None:
        if hasattr(self.ui_updates, "clear_tool_confirmation"):
            self.ui_updates.clear_tool_confirmation(confirmation_id)
