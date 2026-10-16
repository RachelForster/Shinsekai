"""Immutable observations of child-process transitions and session milestones."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChatProcessEvent(str, Enum):
    STARTING = "chat_process_starting"
    STARTED = "chat_process_started"
    STOPPING = "chat_process_stopping"
    STOPPED = "chat_process_stopped"
    FAILED = "chat_process_failed"


class ChatSessionEvent(str, Enum):
    CONNECTED = "chat_session_connected"
    READY = "chat_session_ready"
    CLOSING = "chat_session_closing"
    ENDED = "chat_session_ended"
    FAILED = "chat_session_failed"


@dataclass(frozen=True)
class ChatProcessContext:
    """Process metadata without mutable host state, launch options or secrets.

    STARTED means the child survived the initial process-exit check. Model and
    plugin initialization readiness remains the responsibility of ``init_chat``.
    These are observation hooks; they cannot veto launch or shutdown.
    """

    event: ChatProcessEvent
    session_id: str = ""
    pid: int | None = None
    exit_code: int | None = None
    reason: str = ""
    error: BaseException | None = None
    launch_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", ChatProcessEvent(self.event))


@dataclass(frozen=True)
class ChatSessionContext:
    """Session milestones; READY is distinct from a child process being STARTED."""

    event: ChatSessionEvent
    session_id: str = ""
    launch_id: str = ""
    reason: str = ""
    error: BaseException | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", ChatSessionEvent(self.event))
