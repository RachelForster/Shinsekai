"""Persistent Agent task owner. Backend code executes only in its child worker."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.agent.ipc import fault
from core.agent.storage import AgentStore, encode
from sdk.agent import (
    AgentArtifact,
    AgentArtifactContent,
    AgentBackendConfig,
    AgentBackendDescriptor,
    AgentBackendEvent,
    AgentCancellationReceipt,
    AgentEffect,
    AgentError,
    AgentEvent,
    AgentEventPage,
    AgentEventType,
    AgentHostToolCall,
    AgentHostToolResult,
    AgentInputAnswer,
    AgentInputRequest,
    AgentLimits,
    AgentOrigin,
    AgentRequestError,
    AgentResult,
    AgentSession,
    AgentSessionConfig,
    AgentSessionRequest,
    AgentTask,
    AgentTaskCompletion,
    AgentTaskExecution,
    AgentTaskRequest,
    AgentTaskReceipt,
    AgentTaskStatus,
)
from application.agent.execute_host_tool import AgentHostTool
from application.agent.supervise_worker import AgentWorkerSupervisor


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def _caller(origin: AgentOrigin) -> str:
    return encode({"kind": origin.kind, "callerId": origin.caller_id})


@dataclass(frozen=True)
class AgentProfile:
    profile_id: str = "basic"
    system_policy_ref: str = "agent:default"
    skill_refs: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    limits: AgentLimits = field(
        default_factory=lambda: AgentLimits(wall_time_ms=60000, max_tool_calls=20)
    )
    max_queued_per_caller: int = 8
    input_timeout_ms: int = 60000
    # Trusted host policy for future tasks; session permissions stay snapshotted.
    use_current_limits: bool = False

    def to_record(self) -> dict:
        return {
            "toolNames": list(self.tool_names),
            "limits": self.limits.to_wire(),
            "maxQueuedPerCaller": self.max_queued_per_caller,
            "inputTimeoutMs": self.input_timeout_ms,
        }


@dataclass
class _Execution:
    task_id: str
    attempt_id: str
    started: float
    cancel_requested: float | None = None
    cancel_sent: bool = False
    start_sent: bool = False
    abort_error: AgentError | None = None


class AgentService:
    """One application-owned queue and database, with caller-bound clients.

    Construction recovers snapshots but never executes recovered queued work.
    ``start`` enables dispatch; ``resume_queue`` is the explicit recovery action.
    Origins, profiles, resource references and callbacks are supplied by the
    trusted composition root, not chosen by a role model or worker.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        backend: AgentBackendConfig | None = None,
        profiles: Sequence[AgentProfile] = (AgentProfile(),),
        tools: Sequence[AgentHostTool] = (),
        max_queued: int = 64,
        origin_valid: Callable[[AgentOrigin], bool] | None = None,
        cancel_grace_seconds: float = 2,
        worker_command: Sequence[str] | None = None,
        worker_environment: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        if max_queued < 1 or cancel_grace_seconds <= 0:
            raise ValueError("Queue size and cancellation grace must be positive")
        self.profiles = {profile.profile_id: profile for profile in profiles}
        self.tools = {tool.definition.name: tool for tool in tools}
        if len(self.profiles) != len(profiles) or len(self.tools) != len(tools):
            raise ValueError("Duplicate Agent profile or tool")
        for profile in profiles:
            if (
                profile.max_queued_per_caller < 1
                or profile.input_timeout_ms < 1
                or any(name not in self.tools for name in profile.tool_names)
            ):
                raise ValueError("Invalid Agent profile or missing host tool")
        self.backend_config = backend or AgentBackendConfig(
            backend_id="mock", backend_version="1"
        )
        self.max_queued, self.cancel_grace_seconds = max_queued, cancel_grace_seconds
        self.origin_valid = origin_valid or (lambda origin: origin.kind != "roleplay")
        self._cv = threading.Condition(threading.RLock())
        self._active: _Execution | None = None
        self._inflight: set[tuple[str, str]] = set()
        self._pending_completion: dict[str, AgentTaskCompletion] = {}
        self._closing = False
        self._closed = False
        self._fatal_error: AgentError | None = None
        self._thread: threading.Thread | None = None
        self._worker_boot: str | None = None
        self._session_closes: set[str] = set()
        self._descriptor = AgentBackendDescriptor(
            backend_id=self.backend_config.backend_id,
            version=self.backend_config.backend_version,
            unavailable_reason="Worker has not started yet",
        )
        self._supervisor = AgentWorkerSupervisor(
            self.backend_config,
            handler=self._host_request,
            notification=self._notification,
            command=worker_command,
            environment=worker_environment,
        )
        self._store = AgentStore(database_path)
        try:
            with self._cv, self._store.transaction():
                for task in self._tasks():
                    if (
                        task.status != AgentTaskStatus.QUEUED
                        and not task.status.is_terminal
                    ):
                        self._finish(
                            task,
                            AgentTaskCompletion(
                                status="interrupted",
                                error=AgentError(
                                    code="WORKER_LOST",
                                    message="Application stopped before the task finished",
                                ),
                            ),
                        )
                self.queue_paused = any(
                    task.status == "queued" for task in self._tasks()
                )
        except BaseException:
            self._store.close()
            raise

    def bind(
        self,
        origin: AgentOrigin,
        *,
        profile_ids: Sequence[str] = ("basic",),
        administrator: bool = False,
    ):
        from application.agent.client import BoundAgentClient

        if administrator and origin.kind != "user":
            raise fault(
                "AUTH_REQUIRED",
                "Only the trusted user interface can administer Agent tasks",
            )
        if any(profile_id not in self.profiles for profile_id in profile_ids):
            raise fault("INVALID_REQUEST", "Unknown Agent profile")
        return BoundAgentClient(
            self, origin.model_copy(deep=True), tuple(profile_ids), administrator
        )

    def configure_backend(
        self,
        backend: AgentBackendConfig,
        *,
        worker_environment: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        """Finish trusted asynchronous preparation before dispatch starts."""
        with self._cv:
            self._ensure_open()
            if self._thread is not None:
                raise fault("SESSION_BUSY", "Agent dispatch has already started")
            self.backend_config = backend.model_copy(deep=True)
            self._supervisor.config = self.backend_config
            self._supervisor.environment = worker_environment
            self._descriptor = AgentBackendDescriptor(
                backend_id=backend.backend_id,
                version=backend.backend_version,
                unavailable_reason="Worker starts on the first task",
            )

    def start(self) -> None:
        with self._cv:
            self._ensure_open()
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._dispatch, name="agent-task-dispatch", daemon=True
                )
                self._thread.start()

    def resume_queue(self) -> None:
        with self._cv:
            self._ensure_open()
            self.queue_paused = False
            self._cv.notify_all()

    def _ensure_open(self) -> None:
        if self._fatal_error:
            raise AgentRequestError(self._fatal_error)
        if self._closing or self._closed:
            raise fault("BACKEND_UNAVAILABLE", "Agent service is closing or closed")

    def _tasks(self) -> list[AgentTask]:
        return [
            AgentTask.model_validate(value) for value in self._store.records("task")
        ]

    def _task(self, task_id: str) -> AgentTask:
        value = self._store.get("task", task_id)
        if value is None:
            raise fault("INVALID_REQUEST", "Agent task was not found")
        return AgentTask.model_validate(value)

    def _session_record(self, session_id: str) -> dict:
        value = self._store.get("session", session_id)
        if value is None:
            raise fault("INVALID_REQUEST", "Agent session was not found")
        return value

    def _visible(self, owner: AgentOrigin, client) -> bool:
        if client.administrator:
            return True
        if client.origin.kind == "roleplay" and not self.origin_valid(client.origin):
            return False
        if _caller(owner) != _caller(client.origin):
            return False
        if owner.kind == "roleplay":
            return all(
                getattr(owner, key) == getattr(client.origin, key)
                for key in (
                    "conversation_id",
                    "branch_id",
                    "chat_instance_id",
                    "context_epoch",
                )
            )
        return True

    def _authorize_task(self, task_id: str, client) -> AgentTask:
        task = self._task(task_id)
        if not self._visible(task.origin, client):
            raise fault("AUTH_REQUIRED", "Agent task is not accessible to this caller")
        return task

    def _append(self, task: AgentTask, kind: str, payload: dict) -> None:
        self._store.append_event(
            task.task_id,
            {
                "schemaVersion": 1,
                "taskId": task.task_id,
                "timestamp": _now().isoformat(),
                "type": kind,
                "payload": payload,
            },
        )

    def _update(self, task: AgentTask, **changes) -> AgentTask:
        value = {**task.to_wire(), **changes, "updatedAt": _now().isoformat()}
        result = AgentTask.model_validate(value)
        self._store.put("task", task.task_id, result.to_wire())
        return result

    def _status(
        self, task: AgentTask, status: AgentTaskStatus | str, message: str = ""
    ) -> AgentTask:
        task = self._update(task, status=status)
        self._append(
            task, "task.status", {"status": task.status.value, "message": message}
        )
        return task

    def _effects(self, task_id: str) -> tuple[AgentEffect, ...]:
        effects = []
        for row in self._store.tool_calls(task_id):
            if row["result"] is not None:
                effects.extend(
                    AgentHostToolResult.model_validate_json(row["result"]).effects
                )
            elif row["effect_kind"] != "read":
                effects.append(
                    AgentEffect(
                        call_id=row["call_id"],
                        tool_name=row["name"],
                        state="unknown",
                        description="The host operation did not record a final result",
                    )
                )
        return tuple(effects)

    def _finish(self, task: AgentTask, completion: AgentTaskCompletion) -> None:
        if task.status.is_terminal:
            return
        cancellation_stopped_input = (
            completion.status == "failed"
            and completion.error
            and completion.error.code in ("INPUT_EXPIRED", "TOOL_DENIED")
        )
        if task.status == "cancelling" and (
            completion.status == "succeeded" or cancellation_stopped_input
        ):
            completion = AgentTaskCompletion(
                status="cancelled", result=completion.result
            )
        effects = self._effects(task.task_id)
        result = completion.result
        artifacts = tuple(
            AgentArtifact.model_validate(record["artifact"])
            for record in self._store.records("artifact")
            if record["taskId"] == task.task_id
        )
        if result is not None:
            result = result.model_copy(
                update={"effects": effects, "artifacts": artifacts}
            )
        elif effects or artifacts:
            result = AgentResult(
                summary="Execution stopped; recorded operations are retained.",
                effects=effects,
                artifacts=artifacts,
            )
        completion = AgentTaskCompletion(
            status=completion.status, result=result, error=completion.error
        )
        task = self._update(
            task,
            status=completion.status.value,
            result=result.to_wire() if result else None,
            error=completion.error.to_wire() if completion.error else None,
        )
        self._append(task, "task.status", {"status": task.status.value})
        self._append(task, "task.completed", completion.to_wire())
        self._pending_completion.pop(task.task_id, None)
        if self._active and self._active.task_id == task.task_id:
            self._active = None
        self._cv.notify_all()

    def create_session(self, client, request: AgentSessionRequest) -> AgentSession:
        with self._cv, self._store.transaction():
            self._ensure_open()
            if request.profile_id not in client.profile_ids:
                raise fault(
                    "AUTH_REQUIRED", "Agent profile is not allowed for this caller"
                )
            if request.backend_id != self.backend_config.backend_id:
                raise fault("BACKEND_UNAVAILABLE", "Requested backend is not active")
            profile = self.profiles[request.profile_id]
            session = AgentSession(
                session_id=_id("as"),
                backend_id=request.backend_id,
                backend_version=self.backend_config.backend_version,
                profile_id=request.profile_id,
                model_ref=request.model_ref,
                system_policy_ref=profile.system_policy_ref,
                skill_refs=profile.skill_refs,
                owner=client.origin,
                created_at=_now(),
            )
            self._store.put(
                "session",
                session.session_id,
                {
                    **session.to_wire(),
                    "closed": False,
                    "profile": profile.to_record(),
                    "workerBoot": None,
                },
            )
            return session

    def submit_task(self, client, request: AgentTaskRequest) -> AgentTaskReceipt:
        # Deep snapshot before hashing and enqueueing arbitrary JSON context.
        request = AgentTaskRequest.model_validate_json(request.model_dump_json())
        with self._cv, self._store.transaction():
            self._ensure_open()
            if request.origin != client.origin:
                raise fault(
                    "AUTH_REQUIRED", "Task origin does not match the bound caller"
                )
            fingerprint = _fingerprint(request.to_wire())
            previous = self._store.find_request(
                _caller(client.origin), request.request_id
            )
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise fault(
                        "IDEMPOTENCY_CONFLICT",
                        "Request ID was reused with different content",
                    )
                task = self._authorize_task(previous["task_id"], client)
                return AgentTaskReceipt(task_id=task.task_id, status=task.status)
            record = self._session_record(request.session_id)
            session = AgentSession.model_validate(record)
            if record["closed"]:
                raise fault("INVALID_REQUEST", "Agent session is closed")
            if (
                not self._visible(session.owner, client)
                or session.profile_id not in client.profile_ids
            ):
                raise fault(
                    "AUTH_REQUIRED", "Agent session is not accessible to this caller"
                )
            if (session.backend_id, session.backend_version) != (
                self.backend_config.backend_id,
                self.backend_config.backend_version,
            ):
                raise fault(
                    "SESSION_BACKEND_MISMATCH",
                    "Session belongs to a different backend version",
                )
            if request.origin.kind == "roleplay" and (
                request.lifetime != "origin-bound"
                or not self.origin_valid(request.origin)
            ):
                raise fault(
                    "AUTH_REQUIRED",
                    "Roleplay origin is invalid or attempted to detach its task",
                )
            queued = [task for task in self._tasks() if task.status == "queued"]
            if (
                len(queued) >= self.max_queued
                or sum(
                    _caller(task.origin) == _caller(client.origin) for task in queued
                )
                >= record["profile"]["maxQueuedPerCaller"]
            ):
                raise fault("LIMIT_EXCEEDED", "Agent task queue is full")
            profile = self.profiles[session.profile_id]
            bounds = (
                profile.limits
                if profile.use_current_limits
                else AgentLimits.model_validate(record["profile"]["limits"])
            )
            limits = {}
            for name in AgentLimits.model_fields:
                values = [
                    value
                    for value in (getattr(bounds, name), getattr(request.limits, name))
                    if value is not None
                ]
                limits[name] = min(values) if values else None
            task = AgentTask(
                **{**request.model_dump(), "limits": AgentLimits(**limits)},
                task_id=_id("at"),
                status="queued",
                created_at=_now(),
                updated_at=_now(),
            )
            self._store.put("task", task.task_id, task.to_wire())
            self._store.save_request(
                _caller(client.origin), request.request_id, fingerprint, task.task_id
            )
            self._append(task, "task.status", {"status": "queued"})
            self._cv.notify_all()
            return AgentTaskReceipt(task_id=task.task_id)

    def cancel_task(
        self, client, task_id: str, reason: str
    ) -> AgentCancellationReceipt:
        with self._cv, self._store.transaction():
            task = self._authorize_task(task_id, client)
            if task.status.is_terminal:
                return AgentCancellationReceipt(task=task, accepted=False)
            if task.status == "queued":
                self._finish(task, AgentTaskCompletion(status="cancelled"))
            elif task.status != "cancelling":
                self._status(task, "cancelling", reason)
                if self._active and self._active.task_id == task_id:
                    self._active.cancel_requested = time.monotonic()
            self._cv.notify_all()
            return AgentCancellationReceipt(task=self._task(task_id), accepted=True)

    def read_events(
        self, client, task_id: str, after_seq: int, limit: int
    ) -> AgentEventPage:
        with self._cv:
            self._authorize_task(task_id, client)
            _validate_page(limit)
            if type(after_seq) is not int or after_seq < 0:
                raise fault("INVALID_REQUEST", "Invalid event cursor")
            rows = self._store.read_events(task_id, after_seq, limit)
            known = {value.value for value in AgentEventType}
            events = tuple(
                AgentEvent.model_validate(value)
                for value in rows
                if value["type"] in known
            )
            return AgentEventPage(
                task_id=task_id,
                events=events,
                next_seq=rows[-1]["eventSeq"] if rows else after_seq,
            )

    def respond_input(
        self, client, task_id: str, answer: AgentInputAnswer
    ) -> AgentTask:
        with self._cv, self._store.transaction():
            task = self._authorize_task(task_id, client)
            if client.origin.kind != "user":
                raise fault(
                    "AUTH_REQUIRED", "Only the real user can answer Agent input"
                )
            key = f"{task_id}:{answer.input_request_id}"
            record = self._store.get("input", key)
            if not record:
                raise fault("INPUT_EXPIRED", "Agent input request was not found")
            if record["answer"] is not None:
                if AgentInputAnswer.model_validate(record["answer"]) != answer:
                    raise fault(
                        "IDEMPOTENCY_CONFLICT",
                        "Agent input already has a different answer",
                    )
                return task
            request = AgentInputRequest.model_validate(record["request"])
            if task.status != "waiting_input" or request.expires_at <= _now():
                raise fault("INPUT_EXPIRED", "Agent input request has expired")
            if request.options and answer.value not in [
                option.value for option in request.options
            ]:
                raise fault(
                    "INVALID_REQUEST", "Answer is not one of the offered options"
                )
            if request.kind == "confirmation" and type(answer.value) is not bool:
                raise fault(
                    "INVALID_REQUEST",
                    "Confirmation requires an explicit boolean answer",
                )
            self._store.put("input", key, {**record, "answer": answer.to_wire()})
            self._append(task, "input.resolved", {"answer": answer.to_wire()})
            task = self._status(task, "running")
            self._cv.notify_all()
            return task

    def publish_text_artifact(
        self,
        task_id: str,
        text: str,
        *,
        title: str,
        kind: str = "report",
        mime_type: str = "text/plain",
    ) -> AgentArtifact:
        with self._cv, self._store.transaction():
            task = self._task(task_id)
            if task.status.is_terminal:
                raise fault(
                    "INVALID_REQUEST",
                    "Cannot publish an artifact after task completion",
                )
            artifact = AgentArtifact(
                artifact_id=_id("aa"),
                kind=kind,
                title=title,
                mime_type=mime_type,
                size=len(text.encode("utf-8")),
                revision=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
            self._store.put(
                "artifact",
                artifact.artifact_id,
                {
                    "taskId": task_id,
                    "artifact": artifact.to_wire(),
                    "text": text,
                },
            )
            self._append(task, "artifact.created", {"artifact": artifact.to_wire()})
            return artifact

    def _notification(self, method: str, params: dict) -> None:
        if method != "task.event":
            raise ValueError("Unknown worker notification")
        raw = params["event"]
        if (
            not isinstance(raw.get("type"), str)
            or not raw["type"].strip()
            or not isinstance(raw.get("payload"), dict)
        ):
            raise ValueError("Invalid worker event body")
        known = raw.get("type") in {value.value for value in AgentEventType}
        event = AgentBackendEvent.model_validate(
            raw if known else {**raw, "type": "usage.updated", "payload": {}}
        )
        with self._cv, self._store.transaction():
            task = self._task(params["taskId"])
            if task.status.is_terminal or task.attempt_id != event.attempt_id:
                return  # Late traffic from a finished attempt cannot change its state.
            if not self._store.record_worker_event(
                event.attempt_id, event.worker_seq, _fingerprint(raw)
            ):
                return
            if known and event.type == "task.completed":
                if any(key[0] == task.task_id for key in self._inflight):
                    self._pending_completion[task.task_id] = event.payload
                else:
                    self._finish(task, event.payload)
            elif known and event.type == "task.status":
                if task.status == "cancelling" and event.payload.status == "running":
                    return
                if (
                    event.payload.status.is_terminal
                    or event.payload.status != task.status
                ):
                    raise ValueError("Backend cannot override host task state")
                self._append(task, raw["type"], raw["payload"])
            elif known and event.type in (
                "tool.started",
                "tool.completed",
                "input.requested",
                "input.resolved",
                "artifact.created",
            ):
                raise ValueError("Host-owned event cannot be emitted by a backend")
            else:
                self._append(task, raw["type"], raw["payload"])

    def _host_request(self, method: str, params: dict) -> object:
        with self._cv:
            task = self._task(params["taskId"])
            if task.attempt_id != params["attemptId"] or task.status.is_terminal:
                raise fault(
                    "TOOL_DENIED", "Agent callback belongs to an inactive attempt"
                )
        if method == "host.tools.invoke":
            return self._invoke_tool(
                task.task_id, AgentHostToolCall.model_validate(params["call"])
            ).to_wire()
        if method == "host.input.request":
            return self._request_input(
                task.task_id, AgentInputRequest.model_validate(params["request"])
            ).to_wire()
        raise fault("INVALID_REQUEST", "Unknown Agent host method")

    def _tool_error(
        self,
        call: AgentHostToolCall,
        code: str,
        message: str,
        *,
        state: str | None = None,
    ) -> AgentHostToolResult:
        effects = (
            (AgentEffect(call_id=call.call_id, tool_name=call.name, state=state),)
            if state
            else ()
        )
        return AgentHostToolResult(
            call_id=call.call_id,
            ok=False,
            error=AgentError(code=code, message=message),
            effects=effects,
        )

    def _invoke_tool(
        self, task_id: str, call: AgentHostToolCall
    ) -> AgentHostToolResult:
        key, fingerprint = (task_id, call.call_id), _fingerprint(call.to_wire())
        with self._cv:
            previous = self._store.tool_call(*key)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    return self._tool_error(
                        call,
                        "IDEMPOTENCY_CONFLICT",
                        "Tool call ID has different arguments",
                    )
                while key in self._inflight:
                    self._cv.wait(timeout=0.1)
                previous = self._store.tool_call(*key)
                return (
                    AgentHostToolResult.model_validate_json(previous["result"])
                    if previous["result"]
                    else self._tool_error(
                        call,
                        "WORKER_LOST",
                        "Previous tool outcome is unknown; it will not be executed again",
                        state="unknown" if previous["effect_kind"] != "read" else None,
                    )
                )
            task = self._task(task_id)
            record = self._session_record(task.session_id)
            tool = self.tools.get(call.name)
            if (
                task.status != "running"
                or self._closing
                or (
                    task.origin.kind == "roleplay"
                    and task.lifetime == "origin-bound"
                    and not self.origin_valid(task.origin)
                )
            ):
                return self._tool_error(
                    call,
                    "TOOL_DENIED",
                    "Task is stopping or its origin is no longer valid",
                )
            if (
                task.limits.max_tool_calls is not None
                and len(self._store.tool_calls(task_id)) >= task.limits.max_tool_calls
            ):
                if self._active and self._active.task_id == task_id:
                    self._active.abort_error = AgentError(
                        code="LIMIT_EXCEEDED",
                        message="Agent tool call limit was reached",
                    )
                    self._cv.notify_all()
                return self._tool_error(
                    call, "LIMIT_EXCEEDED", "Agent tool call limit was reached"
                )
            denied = None
            if tool is None or call.name not in record["profile"]["toolNames"]:
                denied = self._tool_error(
                    call,
                    "TOOL_DENIED",
                    "Tool is not available to this task",
                    state="not_applied",
                )
            else:
                try:
                    tool.input_model.model_validate(call.arguments)
                except Exception:
                    denied = self._tool_error(
                        call,
                        "INVALID_REQUEST",
                        "Tool arguments do not match the registered schema",
                        state="not_applied",
                    )
            with self._store.transaction():
                self._store.begin_tool(
                    task_id,
                    call.call_id,
                    fingerprint,
                    call.name,
                    tool.definition.effect_kind if tool else "execute",
                )
                self._append(task, "tool.started", {"call": call.to_wire()})
                if denied:
                    self._store.finish_tool(task_id, call.call_id, denied.to_wire())
                    self._append(task, "tool.completed", {"result": denied.to_wire()})
                    return denied
            self._inflight.add(key)
        known_effects = ()
        try:
            result = tool.execute(task, call)
            if (
                not isinstance(result, AgentHostToolResult)
                or result.call_id != call.call_id
            ):
                raise ValueError("Invalid host tool result")
            result = AgentHostToolResult.model_validate(result.model_dump())
            if any(
                effect.call_id != call.call_id or effect.tool_name != call.name
                for effect in result.effects
            ):
                raise ValueError("Invalid host tool effect identity")
            known_effects = result.effects
            if result.ok:
                tool.output_model.model_validate(result.data)
            if tool.definition.effect_kind != "read" and not result.effects:
                # A write tool must report what actually happened, even after failure.
                raise ValueError("Write tool did not report its effect")
        except Exception:
            result = self._tool_error(
                call,
                "INVALID_REQUEST",
                "Host tool did not record a valid result",
                state=(
                    "unknown"
                    if tool.definition.effect_kind != "read" and not known_effects
                    else None
                ),
            )
            if known_effects:
                result = result.model_copy(update={"effects": known_effects})
        with self._cv, self._store.transaction():
            self._store.finish_tool(task_id, call.call_id, result.to_wire())
            self._append(
                self._task(task_id), "tool.completed", {"result": result.to_wire()}
            )
            self._inflight.discard(key)
            pending = self._pending_completion.get(task_id)
            if pending and not any(item[0] == task_id for item in self._inflight):
                self._finish(self._task(task_id), pending)
            self._cv.notify_all()
        return result

    def _request_input(
        self, task_id: str, request: AgentInputRequest
    ) -> AgentInputAnswer:
        with self._cv:
            task = self._task(task_id)
            if task.status != "running" or self._closing:
                raise fault(
                    "INPUT_EXPIRED", "Task is no longer accepting input requests"
                )
            timeout_ms = self._session_record(task.session_id)["profile"][
                "inputTimeoutMs"
            ]
            expires = min(
                request.expires_at or (_now() + timedelta(milliseconds=timeout_ms)),
                _now() + timedelta(milliseconds=timeout_ms),
            )
            request = request.model_copy(update={"expires_at": expires})
            key = f"{task_id}:{request.input_request_id}"
            if self._store.get("input", key):
                raise fault("IDEMPOTENCY_CONFLICT", "Input request ID was already used")
            with self._store.transaction():
                self._store.put(
                    "input", key, {"request": request.to_wire(), "answer": None}
                )
                self._append(task, "input.requested", request.to_wire())
                self._status(task, "waiting_input")
            while True:
                record = self._store.get("input", key)
                if record["answer"] is not None:
                    return AgentInputAnswer.model_validate(record["answer"])
                if (
                    self._task(task_id).status != "waiting_input"
                    or self._closing
                    or _now() >= expires
                ):
                    raise fault(
                        "INPUT_EXPIRED",
                        "Agent input request expired or its task stopped",
                    )
                self._cv.wait(timeout=0.1)

    def _start_execution(self, execution: _Execution) -> None:
        with self._cv:
            task = self._task(execution.task_id)
            record = self._session_record(task.session_id)
            if (record["backendId"], record["backendVersion"]) != (
                self.backend_config.backend_id,
                self.backend_config.backend_version,
            ):
                raise fault(
                    "SESSION_BACKEND_MISMATCH",
                    "Recovered task belongs to a different backend",
                )
        if self._supervisor.process is None:
            descriptor = self._supervisor.start()
            with self._cv:
                self._descriptor = descriptor
                self._worker_boot = _id("boot")
        with self._cv:
            task = self._task(execution.task_id)
            record = self._session_record(task.session_id)
            session = AgentSession.model_validate(record)
            tools = tuple(
                self.tools[name].definition
                for name in record["profile"]["toolNames"]
                if name in self.tools
            )
            if len(tools) != len(record["profile"]["toolNames"]):
                raise fault(
                    "CAPABILITY_UNSUPPORTED",
                    "A snapshotted host tool is no longer registered",
                )
            caps = self._descriptor.capabilities
            if tools and (not caps.host_tools or not caps.tool_policy_enforcement):
                raise fault(
                    "CAPABILITY_UNSUPPORTED",
                    "Backend cannot enforce the host tool policy",
                )
            if task.limits.max_tokens is not None and not caps.token_limit:
                raise fault(
                    "CAPABILITY_UNSUPPORTED", "Backend cannot enforce a token limit"
                )
            if (
                record["workerBoot"]
                and record["workerBoot"] != self._worker_boot
                and not caps.native_session_resume
            ):
                raise fault(
                    "SESSION_RESUME_UNAVAILABLE",
                    "Create a new session to continue with the previous results",
                )
        peer = self._supervisor.peer
        if task.session_id not in self._supervisor.opened_sessions:
            response = peer.request(
                "session.open",
                AgentSessionConfig.model_validate(session.to_wire()).to_wire(),
            )
            if (
                not isinstance(response, dict)
                or response.get("sessionId") != task.session_id
            ):
                raise fault("PROTOCOL_MISMATCH", "Worker opened a different session")
            with self._cv, self._store.transaction():
                self._store.put(
                    "session",
                    task.session_id,
                    {**record, "workerBoot": self._worker_boot},
                )
                self._supervisor.opened_sessions.add(task.session_id)
        with self._cv:
            task = self._task(execution.task_id)
            if task.status == "cancelling":
                with self._store.transaction():
                    self._finish(task, AgentTaskCompletion(status="cancelled"))
                return
        request = AgentTaskRequest.model_validate(
            {
                key: value
                for key, value in task.to_wire().items()
                if key
                in {
                    field.alias or name
                    for name, field in AgentTaskRequest.model_fields.items()
                }
            }
        )
        execution.start_sent = True
        response = peer.request(
            "task.start",
            AgentTaskExecution(
                task_id=task.task_id,
                attempt_id=execution.attempt_id,
                request=request,
                tools=tools,
            ).to_wire(),
        )
        if not isinstance(response, dict) or response.get("accepted") is not True:
            raise fault("PROTOCOL_MISMATCH", "Worker did not accept the task")

    def _dispatch(self) -> None:
        try:
            while True:
                action = None
                with self._cv:
                    if self._closing and self._active is None and not self._inflight:
                        return
                    active = self._active
                    if active:
                        task = self._task(active.task_id)
                        peer, process = self._supervisor.peer, self._supervisor.process
                        error = peer.failure.error if peer and peer.failure else None
                        error = error or active.abort_error
                        if (
                            task.origin.kind == "roleplay"
                            and task.lifetime == "origin-bound"
                            and not self.origin_valid(task.origin)
                            and task.status != "cancelling"
                        ):
                            with self._store.transaction():
                                task = self._status(
                                    task,
                                    "cancelling",
                                    "Roleplay origin is no longer valid",
                                )
                            active.cancel_requested = time.monotonic()
                        if process and process.poll() is not None:
                            error = error or AgentError(
                                code="WORKER_LOST", message="Agent worker exited"
                            )
                        elapsed = (time.monotonic() - active.started) * 1000
                        if (
                            task.limits.wall_time_ms is not None
                            and elapsed >= task.limits.wall_time_ms
                        ):
                            error = AgentError(
                                code="LIMIT_EXCEEDED",
                                message="Agent wall time limit was reached",
                                details={
                                    "limit": "wallTimeMs",
                                    "limitMs": task.limits.wall_time_ms,
                                    "elapsedMs": int(elapsed),
                                },
                            )
                        if error:
                            action = ("interrupt", active, error)
                        elif task.status == "cancelling":
                            if not active.cancel_sent:
                                active.cancel_sent = True
                                active.cancel_requested = (
                                    active.cancel_requested or time.monotonic()
                                )
                                action = ("cancel", active, None)
                            elif (
                                time.monotonic() - active.cancel_requested
                                >= self.cancel_grace_seconds
                            ):
                                action = ("cancel_timeout", active, None)
                    elif self._supervisor.process and (
                        self._supervisor.process.poll() is not None
                        or self._supervisor.peer.failure
                    ):
                        action = ("stop_idle", None, None)
                    elif self._session_closes and self._supervisor.peer:
                        action = ("close_session", self._session_closes.pop(), None)
                    elif (
                        not self._inflight
                        and not self._closing
                        and not self.queue_paused
                    ):
                        queued = next(
                            (task for task in self._tasks() if task.status == "queued"),
                            None,
                        )
                        if queued:
                            with self._store.transaction():
                                if (
                                    queued.origin.kind == "roleplay"
                                    and queued.lifetime == "origin-bound"
                                    and not self.origin_valid(queued.origin)
                                ):
                                    self._finish(
                                        queued, AgentTaskCompletion(status="cancelled")
                                    )
                                    continue
                                active = _Execution(
                                    queued.task_id, _id("attempt"), time.monotonic()
                                )
                                self._active = active
                                queued = self._update(
                                    queued, attemptId=active.attempt_id
                                )
                                self._status(queued, "running")
                            action = ("start", active, None)
                    if action is None:
                        self._cv.wait(timeout=0.03)
                        continue
                kind, active, error = action
                try:
                    if kind == "stop_idle":
                        self._supervisor.stop(force=True)
                        continue
                    if kind == "close_session":
                        self._supervisor.peer.request(
                            "session.close", {"sessionId": active}
                        )
                        self._supervisor.opened_sessions.discard(active)
                        continue
                    if kind == "start":
                        self._start_execution(active)
                    elif kind == "cancel":
                        self._supervisor.peer.request(
                            "task.cancel", {"attemptId": active.attempt_id}, timeout=1
                        )
                    else:
                        self._supervisor.stop(force=True)
                        with self._cv, self._store.transaction():
                            task = self._task(active.task_id)
                            unsettled = any(
                                key[0] == active.task_id for key in self._inflight
                            )
                            if kind == "cancel_timeout" and not unsettled:
                                self._finish(
                                    task, AgentTaskCompletion(status="cancelled")
                                )
                            else:
                                self._finish(
                                    task,
                                    AgentTaskCompletion(
                                        status="interrupted",
                                        error=error
                                        or AgentError(
                                            code="WORKER_LOST",
                                            message="Host operation did not settle before cancellation",
                                        ),
                                    ),
                                )
                except Exception as exc:
                    error = (
                        exc.error
                        if isinstance(exc, AgentRequestError)
                        else AgentError(
                            code="BACKEND_UNAVAILABLE",
                            message="Unable to execute the Agent task",
                        )
                    )
                    if kind in ("stop_idle", "close_session"):
                        self._supervisor.stop(force=True)
                        continue
                    if error.code in ("WORKER_LOST", "PROTOCOL_MISMATCH") or (
                        self._supervisor.peer and self._supervisor.peer.failure
                    ):
                        self._supervisor.stop(force=True)
                    with self._cv, self._store.transaction():
                        task = self._task(active.task_id)
                        unsettled = any(
                            key[0] == active.task_id for key in self._inflight
                        )
                        uncertain_start = active.start_sent and error.code in (
                            "WORKER_LOST",
                            "PROTOCOL_MISMATCH",
                        )
                        self._finish(
                            task,
                            AgentTaskCompletion(
                                status=(
                                    "interrupted"
                                    if kind != "start" or unsettled or uncertain_start
                                    else "failed"
                                ),
                                error=error,
                            ),
                        )
        except Exception:
            with self._cv:
                self._fatal_error = AgentError(
                    code="BACKEND_UNAVAILABLE",
                    message="Agent task dispatcher stopped unexpectedly",
                )
                if self._active:
                    with self._store.transaction():
                        self._finish(
                            self._task(self._active.task_id),
                            AgentTaskCompletion(
                                status="interrupted", error=self._fatal_error
                            ),
                        )
                self._cv.notify_all()
        finally:
            self._supervisor.stop()

    def close(self, *, timeout: float = 5) -> None:
        with self._cv:
            if self._closed:
                return
            self._closing = True
            if self._active:
                with self._store.transaction():
                    task = self._task(self._active.task_id)
                    if task.status != "cancelling":
                        self._status(task, "cancelling", "Application shutdown")
                    if self._active.cancel_requested is None:
                        self._active.cancel_requested = time.monotonic()
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise fault(
                    "SESSION_BUSY",
                    "Host operation is still settling; Agent database ownership was retained",
                )
        with self._cv:
            if not self._closed:
                self._store.close()
                self._closed = True

    def __enter__(self) -> AgentService:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _validate_page(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise fault("INVALID_REQUEST", "Page size must be between 1 and 1000")
