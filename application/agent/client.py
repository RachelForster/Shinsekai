"""Caller-bound implementation of the public AgentClient contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING

from core.agent.ipc import fault
from sdk.agent import (
    AgentArtifact,
    AgentArtifactContent,
    AgentBackendDescriptor,
    AgentCancellationReceipt,
    AgentEventPage,
    AgentInputAnswer,
    AgentOrigin,
    AgentSession,
    AgentSessionPage,
    AgentSessionRequest,
    AgentTask,
    AgentTaskPage,
    AgentTaskReceipt,
    AgentTaskRequest,
    AgentTaskStatus,
)

if TYPE_CHECKING:
    from application.agent.management import AgentService


def _available(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self.service._cv:
            self.service._ensure_open()
            return method(self, *args, **kwargs)

    return invoke


def _page(
    items: list, cursor: str | None, limit: int, key: str
) -> tuple[list, str | None]:
    from application.agent.management import _validate_page

    _validate_page(limit)
    start = 0
    if cursor is not None:
        index = next(
            (i for i, item in enumerate(items) if getattr(item, key) == cursor), None
        )
        if index is None:
            raise fault("INVALID_REQUEST", "Invalid Agent page cursor")
        start = index + 1
    selected = items[start : start + limit]
    next_cursor = getattr(selected[-1], key) if start + limit < len(items) else None
    return selected, next_cursor


@dataclass(frozen=True)
class BoundAgentClient:
    service: AgentService
    origin: AgentOrigin
    profile_ids: tuple[str, ...]
    administrator: bool = False

    @_available
    def list_backends(self) -> tuple[AgentBackendDescriptor, ...]:
        with self.service._cv:
            return (self.service._descriptor,)

    @_available
    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> AgentSessionPage:
        with self.service._cv:
            items = [
                AgentSession.model_validate(record)
                for record in self.service._store.records("session")
                if not record["closed"]
                and self.service._visible(
                    AgentOrigin.model_validate(record["owner"]), self
                )
            ]
            selected, next_cursor = _page(items, cursor, limit, "session_id")
            return AgentSessionPage(sessions=selected, next_cursor=next_cursor)

    @_available
    def create_session(self, request: AgentSessionRequest) -> AgentSession:
        return self.service.create_session(self, request)

    @_available
    def submit_task(self, request: AgentTaskRequest) -> AgentTaskReceipt:
        return self.service.submit_task(self, request)

    @_available
    def list_tasks(
        self,
        *,
        session_id: str | None = None,
        statuses: Sequence[AgentTaskStatus] = (),
        cursor: str | None = None,
        limit: int = 100,
    ) -> AgentTaskPage:
        with self.service._cv:
            items = [
                task
                for task in self.service._tasks()
                if self.service._visible(task.origin, self)
                and (session_id is None or task.session_id == session_id)
                and (not statuses or task.status in statuses)
            ]
            selected, next_cursor = _page(items, cursor, limit, "task_id")
            return AgentTaskPage(tasks=selected, next_cursor=next_cursor)

    @_available
    def get_task(self, task_id: str) -> AgentTask:
        with self.service._cv:
            return self.service._authorize_task(task_id, self)

    @_available
    def read_events(
        self, task_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> AgentEventPage:
        return self.service.read_events(self, task_id, after_seq, limit)

    @_available
    def cancel_task(
        self, task_id: str, *, reason: str = ""
    ) -> AgentCancellationReceipt:
        return self.service.cancel_task(self, task_id, reason)

    @_available
    def respond_input(self, task_id: str, answer: AgentInputAnswer) -> AgentTask:
        return self.service.respond_input(self, task_id, answer)

    @_available
    def read_artifact(self, artifact_id: str, *, revision: str) -> AgentArtifactContent:
        with self.service._cv:
            record = self.service._store.get("artifact", artifact_id)
            if record is None:
                raise fault("INVALID_REQUEST", "Agent artifact was not found")
            self.service._authorize_task(record["taskId"], self)
            artifact = AgentArtifact.model_validate(record["artifact"])
            if artifact.revision != revision:
                raise fault("INVALID_REQUEST", "Agent artifact revision does not match")
            return AgentArtifactContent(artifact=artifact, text=record["text"])

    @_available
    def detach_task(self, task_id: str) -> AgentTask:
        with self.service._cv, self.service._store.transaction():
            task = self.service._authorize_task(task_id, self)
            if self.origin.kind != "user":
                raise fault(
                    "AUTH_REQUIRED", "Only the real user can detach Agent tasks"
                )
            return self.service._update(task, lifetime="detached")

    @_available
    def close_session(self, session_id: str) -> None:
        with self.service._cv, self.service._store.transaction():
            record = self.service._session_record(session_id)
            if not self.service._visible(
                AgentOrigin.model_validate(record["owner"]), self
            ):
                raise fault(
                    "AUTH_REQUIRED", "Agent session is not accessible to this caller"
                )
            if any(
                task.session_id == session_id and not task.status.is_terminal
                for task in self.service._tasks()
            ):
                raise fault(
                    "SESSION_BUSY", "Agent session still has active or queued tasks"
                )
            self.service._store.put("session", session_id, {**record, "closed": True})
            self.service._session_closes.add(session_id)
            self.service._cv.notify_all()
