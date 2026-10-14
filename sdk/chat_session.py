"""Read-only application session milestones, separate from child process events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChatSessionEvent(str, Enum):
    CONNECTED = "chat_session_connected"
    READY = "chat_session_ready"
    CLOSING = "chat_session_closing"
    ENDED = "chat_session_ended"
    FAILED = "chat_session_failed"


@dataclass(frozen=True)
class ChatSessionContext:
    event: ChatSessionEvent
    session_id: str = ""
    launch_id: str = ""
    reason: str = ""
    error: BaseException | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", ChatSessionEvent(self.event))
