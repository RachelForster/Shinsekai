"""Stop the active chat process and clean up its application session."""

from __future__ import annotations

from typing import Any, Protocol
import uuid

from application.chat import runtime_process
from application.chat.mobile_access import stop_mobile_access
from application.story.coordinator import clear_story_session


class ChatStopState(Protocol):
    """Narrow state surface required by the stop-chat action."""

    chat_session: dict[str, Any]
    chat_stream: Any | None


def stop_chat(
    state: ChatStopState,
    *,
    reason: str = "聊天会话已结束。",
    wait_timeout: float = 4.0,
) -> dict[str, Any]:
    """Gracefully stop the runtime, transports, mobile access, and story state."""

    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    runtime_process._set_chat_runtime_closing(state, True)
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
        if session_id and chat_stream is not None:
            snapshot = chat_stream.get_snapshot(session_id)
            if (
                not isinstance(snapshot, dict)
                or not str(snapshot.get("sessionClosedReason") or "").strip()
            ):
                chat_stream.close_session(session_id, reason=reason)
    finally:
        try:
            stop_mobile_access(state)
        finally:
            runtime_process._set_chat_runtime_closing(state, False)
    closed_snapshot = runtime_process._chat_snapshot(state, "idle", "")
    if session_id:
        if chat_stream is not None:
            delete_session = getattr(chat_stream, "delete_session", None)
            if callable(delete_session):
                delete_session(session_id)
        if str(state.chat_session.get("sessionId") or "").strip() == session_id:
            state.chat_session = {**state.chat_session, "sessionId": ""}
    clear_story_session(state)
    return closed_snapshot
