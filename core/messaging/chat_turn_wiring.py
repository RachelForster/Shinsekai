"""Host-runtime composition for the framework-neutral chat turn service."""

from __future__ import annotations

from collections.abc import Callable

from core.messaging.chat_turn_service import BatchState, ChatTurnOptions, ChatTurnService


def create_chat_turn_service(
    *,
    config: object,
    user_input_queue: object | None,
    tts_queue: object | None,
    audio_queue: object | None,
    llm_manager: object | None,
    ui_worker: object | None,
    ui_updates: object | None,
    on_state_change: Callable[[BatchState], None] | None = None,
) -> ChatTurnService:
    """Adapt host managers and queues to the service's callback ports."""
    api_config = getattr(getattr(config, "config", None), "api_config", None)
    options = ChatTurnOptions(
        interrupt_enabled=bool(getattr(api_config, "interrupt_enabled", True)),
        batch_enabled=bool(getattr(api_config, "is_batch_input_enabled", False)),
        batch_idle_seconds=float(getattr(api_config, "batch_input_timeout", 5.0)),
        batch_separator=str(getattr(api_config, "batch_input_separator", "\n---\n")),
    )

    def deliver(text: str) -> None:
        if user_input_queue is None:
            return
        from sdk.messages import UserInputMessage

        user_input_queue.put(UserInputMessage(text=text))

    def clear_queue(queue: object | None) -> Callable[[], None]:
        def clear() -> None:
            if queue is None:
                return
            method = getattr(queue, "clear", None)
            if callable(method):
                method()

        return clear

    def has_pending_work() -> bool:
        return any(queue is not None and not queue.empty() for queue in (tts_queue, audio_queue))

    return ChatTurnService(
        sink=deliver,
        options=options,
        on_state_change=on_state_change,
        cancel_current=getattr(llm_manager, "cancel_current_chat", None),
        clear_pending=(clear_queue(tts_queue), clear_queue(audio_queue)),
        stop_playback=getattr(ui_worker, "skip_speech", None),
        hide_status=getattr(ui_updates, "hide_busy_bar", None),
        has_pending_work=has_pending_work,
    )
