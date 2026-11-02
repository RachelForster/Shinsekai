"""Stop the active chat process and clean up its application session."""

from __future__ import annotations

from typing import Any, Protocol
import uuid

from application.chat import composition as runtime_process
from application.chat.host.projection import _set_chat_runtime_closing
from application.chat.host.lifecycle import chat_lifecycle_lock
from application.chat.host.mobile_access import stop_mobile_access
from application.story.coordinator import clear_story_session


class ChatStopState(Protocol):
    """Narrow state surface required by the stop-chat action."""

    chat_session: dict[str, Any]
    chat_stream: Any | None


class ChatSessionChanged(RuntimeError):
    """A conditional close targeted a session that is no longer active."""


def stop_chat(
    state: ChatStopState,
    *,
    reason: str = "聊天会话已结束。",
    wait_timeout: float = 4.0,
    expected_session_id: str | None = None,
) -> dict[str, Any]:
    """Gracefully stop the runtime, transports, mobile access, and story state."""

    with chat_lifecycle_lock(state):
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        if expected_session_id is not None and expected_session_id != session_id:
            raise ChatSessionChanged(
                "The current chat has changed. Confirm the new chat before ending it."
            )
        return _stop_chat(state, reason=reason, wait_timeout=wait_timeout)


def _stop_chat(
    state: ChatStopState,
    *,
    reason: str,
    wait_timeout: float,
) -> dict[str, Any]:
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    lifecycle = runtime_process._session_lifecycle(
        state,
        stop_mobile=stop_mobile_access,
        clear_story=clear_story_session,
    )
    lifecycle.prepare_close()
    owned_launch_id = lifecycle.plan.launch_id
    _set_chat_runtime_closing(state, True)
    process_shutdown_completed = False
    closing_flag_released = False

    def capture_closed_snapshot():
        nonlocal closing_flag_released
        _set_chat_runtime_closing(state, False)
        closing_flag_released = True
        return runtime_process._chat_snapshot(state, "idle", "")

    try:
        graceful_shutdown_requested = False
        if session_id and chat_stream is not None:
            try:
                graceful_shutdown_requested = bool(
                    chat_stream.send_command(
                        session_id,
                        {"cmdId": uuid.uuid4().hex, "type": "close-session"},
                    )
                )
            except Exception:
                graceful_shutdown_requested = False
        runtime_process.shutdown_active_chat_process(
            wait_timeout=wait_timeout,
            wait_before_signal=(
                max(0.0, wait_timeout - 0.7) if graceful_shutdown_requested else 0.0
            ),
        )
        process_shutdown_completed = True
    finally:
        try:
            closed_snapshot = lifecycle.closing(
                reason,
                notify_transport=process_shutdown_completed,
                capture_snapshot=(
                    capture_closed_snapshot if process_shutdown_completed else None
                ),
            )
        except BaseException:
            if process_shutdown_completed:
                lifecycle.ended(reason, expected_launch_id=owned_launch_id)
            raise
        finally:
            if not closing_flag_released:
                _set_chat_runtime_closing(state, False)
    if closed_snapshot is None:
        closed_snapshot = runtime_process._chat_snapshot(state, "idle", "")
    lifecycle.ended(reason, expected_launch_id=owned_launch_id)
    return closed_snapshot
