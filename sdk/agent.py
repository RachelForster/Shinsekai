"""Backend-neutral contracts for Shinsekai's separate Agent process.

This module defines values and ports only. It does not start a process, load a
backend, store a task, or import the application. Public DTOs use snake_case in
Python and camelCase on the wire via ``to_wire()`` / ``model_validate()``.
Caller-facing ports are synchronous and return after a short request; the
backend execution port streams asynchronously inside the Agent worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, NewType, Protocol, Union, runtime_checkable

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StringConstraints,
    model_validator,
)

AGENT_PROTOCOL_VERSION = "1.0"
AGENT_EVENT_SCHEMA_VERSION = 1


def _camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


_Identifier = Annotated[
    str, StringConstraints(strict=True, min_length=1), AfterValidator(_not_blank)
]
_Text = Annotated[str, StringConstraints(strict=True), AfterValidator(_not_blank)]
_NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
_PositiveInt = Annotated[int, Field(strict=True, gt=0)]
_Timestamp = Annotated[
    AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))
]
AgentJsonObject = dict[str, JsonValue]


class AgentContract(BaseModel):
    """JSON DTO; unknown response fields are ignored for minor-version growth.

    Freezing prevents field reassignment, not mutation inside arbitrary JSON
    data. Hosts must take a deep snapshot before enqueueing a request.
    """

    model_config = ConfigDict(
        alias_generator=_camel_case,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        allow_inf_nan=False,
    )

    def to_wire(self) -> dict[str, JsonValue]:
        """Return JSON-compatible camelCase data, preserving unknown/null usage."""
        return self.model_dump(mode="json", by_alias=True)


class AgentTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.SUCCEEDED, self.FAILED, self.CANCELLED, self.INTERRUPTED
        }


class AgentErrorCode(str, Enum):
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INVALID_REQUEST = "INVALID_REQUEST"
    SESSION_BUSY = "SESSION_BUSY"
    SESSION_BACKEND_MISMATCH = "SESSION_BACKEND_MISMATCH"
    SESSION_RESUME_UNAVAILABLE = "SESSION_RESUME_UNAVAILABLE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    TOOL_DENIED = "TOOL_DENIED"
    INPUT_EXPIRED = "INPUT_EXPIRED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    WORKER_LOST = "WORKER_LOST"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"


class AgentError(AgentContract):
    """Portable error. Unknown future error codes remain readable strings."""

    code: _Identifier
    message: _Text
    retryable: StrictBool = False
    details: AgentJsonObject = Field(default_factory=dict)


class AgentRequestError(RuntimeError):
    """Short API request failed; an accepted task fails through its snapshot."""

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


class AgentBackendCapabilities(AgentContract):
    host_tools: StrictBool = False
    tool_policy_enforcement: StrictBool = False
    streaming_text: StrictBool = False
    native_session_resume: StrictBool = False
    interactive_input: StrictBool = False
    structured_output: StrictBool = False
    usage_reporting: StrictBool = False
    activity_reporting: StrictBool = False
    token_limit: StrictBool = False


class AgentBackendDescriptor(AgentContract):
    """Backend IDs are open identifiers, not a closed list of provider names."""

    backend_id: _Identifier
    version: _Identifier
    capabilities: AgentBackendCapabilities = Field(default_factory=AgentBackendCapabilities)
    availability: Literal["ready", "not_installed", "unavailable"] = "unavailable"
    unavailable_reason: str = ""


class AgentOrigin(AgentContract):
    """Trusted provenance assembled by the host, never role-model arguments."""

    kind: Literal["user", "roleplay", "plugin"]
    caller_id: _Identifier
    conversation_id: _Identifier | None = None
    branch_id: _Identifier | None = None
    chat_instance_id: _Identifier | None = None
    source_turn_id: _Identifier | None = None
    context_epoch: _NonNegativeInt | None = None

    @model_validator(mode="after")
    def _require_roleplay_origin(self) -> AgentOrigin:
        if self.kind == "roleplay" and any(
            value is None
            for value in (
                self.conversation_id, self.branch_id, self.chat_instance_id,
                self.source_turn_id, self.context_epoch,
            )
        ):
            raise ValueError("roleplay origin requires the complete chat/branch/turn binding")
        return self


class AgentTextContext(AgentContract):
    kind: Literal["text"] = "text"
    text: _Text
    source: _Identifier
    purpose: str = ""


class AgentResourceContext(AgentContract):
    kind: Literal["resourceRef"] = "resourceRef"
    ref: _Identifier
    source: _Identifier
    purpose: str = ""


class AgentArtifactContext(AgentContract):
    kind: Literal["artifactRef"] = "artifactRef"
    ref: _Identifier
    source: _Identifier
    purpose: str = ""


AgentContext = Annotated[
    Union[AgentTextContext, AgentResourceContext, AgentArtifactContext],
    Field(discriminator="kind"),
]


class AgentLimits(AgentContract):
    """Host-selected bounds; None means no bound of that kind was requested."""

    wall_time_ms: _PositiveInt | None = None
    max_tool_calls: _PositiveInt | None = None
    max_tokens: _PositiveInt | None = None


class AgentInput(AgentContract):
    text: _Text


class AgentSessionRequest(AgentContract):
    model_config = ConfigDict(extra="forbid")

    backend_id: _Identifier
    profile_id: _Identifier
    model_ref: _Identifier


class AgentSessionConfig(AgentContract):
    """Resolved configuration snapshot supplied to the worker by the host."""

    session_id: _Identifier
    backend_id: _Identifier
    backend_version: _Identifier
    profile_id: _Identifier
    model_ref: _Identifier
    system_policy_ref: _Identifier
    skill_refs: tuple[_Identifier, ...] = ()


class AgentSession(AgentSessionConfig):
    owner: AgentOrigin
    created_at: _Timestamp


class AgentTaskRequest(AgentContract):
    """Host-enriched submission, including provenance and execution policy."""

    model_config = ConfigDict(extra="forbid")

    request_id: _Identifier
    session_id: _Identifier
    origin: AgentOrigin
    input: AgentInput
    context: tuple[AgentContext, ...] = ()
    limits: AgentLimits = Field(default_factory=AgentLimits)
    lifetime: Literal["origin-bound", "detached"]


class AgentTaskReceipt(AgentContract):
    """Acceptance only; status may reflect an existing task on request replay."""

    task_id: _Identifier
    status: AgentTaskStatus = AgentTaskStatus.QUEUED
    message: str = ""


class AgentArtifact(AgentContract):
    artifact_id: _Identifier
    kind: _Identifier
    title: _Text
    mime_type: _Identifier
    size: _NonNegativeInt
    revision: _Identifier


class AgentEvidence(AgentContract):
    source_ref: _Identifier
    description: _Text


class AgentEffect(AgentContract):
    """Host-recorded effect; cancellation does not undo an applied operation."""

    call_id: _Identifier
    tool_name: _Identifier
    state: Literal["applied", "not_applied", "unknown"]
    resource_ref: _Identifier | None = None
    revision: _Identifier | None = None
    description: str = ""


class AgentResult(AgentContract):
    summary: str
    data: JsonValue = None
    artifacts: tuple[AgentArtifact, ...] = ()
    evidence: tuple[AgentEvidence, ...] = ()
    effects: tuple[AgentEffect, ...] = ()
    warnings: tuple[str, ...] = ()


def _validate_outcome(
    status: AgentTaskStatus, result: AgentResult | None, error: AgentError | None
) -> None:
    if status == AgentTaskStatus.SUCCEEDED and (result is None or error is not None):
        raise ValueError("succeeded requires a result and must not contain an error")
    if status in {AgentTaskStatus.FAILED, AgentTaskStatus.INTERRUPTED} and error is None:
        raise ValueError("failed/interrupted requires a structured error")
    if not status.is_terminal and (result is not None or error is not None):
        raise ValueError("nonterminal tasks cannot contain a final result/error")


class AgentTask(AgentTaskRequest):
    """Authoritative task snapshot, including partial results in a failed task."""

    model_config = ConfigDict(extra="ignore")

    task_id: _Identifier
    status: AgentTaskStatus
    attempt_id: _Identifier | None = None
    created_at: _Timestamp
    updated_at: _Timestamp
    result: AgentResult | None = None
    error: AgentError | None = None

    @model_validator(mode="after")
    def _check_outcome(self) -> AgentTask:
        _validate_outcome(self.status, self.result, self.error)
        return self


class AgentTaskCompletion(AgentContract):
    status: AgentTaskStatus
    result: AgentResult | None = None
    error: AgentError | None = None

    @model_validator(mode="after")
    def _check_completion(self) -> AgentTaskCompletion:
        if not self.status.is_terminal:
            raise ValueError("task.completed requires a terminal status")
        _validate_outcome(self.status, self.result, self.error)
        return self


class AgentCancellationReceipt(AgentContract):
    """Accepted cancellation can still be cancelling rather than cancelled."""

    task: AgentTask
    accepted: StrictBool


class AgentInputOption(AgentContract):
    value: _Identifier
    label: _Text


class AgentInputRequest(AgentContract):
    input_request_id: _Identifier
    kind: Literal["question", "confirmation"]
    question: _Text
    options: tuple[AgentInputOption, ...] = ()
    expires_at: _Timestamp | None = None


class AgentInputAnswer(AgentContract):
    model_config = ConfigDict(extra="forbid")

    input_request_id: _Identifier
    value: JsonValue


class AgentToolDefinition(AgentContract):
    name: _Identifier
    description: _Text
    input_schema: AgentJsonObject
    output_schema: AgentJsonObject
    effect_kind: Literal["read", "write", "execute"]
    required_capabilities: tuple[_Identifier, ...] = ()


class AgentHostToolCall(AgentContract):
    """Executed through a task-bound host port, without model-selected identity."""

    model_config = ConfigDict(extra="forbid")

    call_id: _Identifier
    name: _Identifier
    arguments: AgentJsonObject = Field(default_factory=dict)


class AgentHostToolResult(AgentContract):
    call_id: _Identifier
    ok: StrictBool
    data: JsonValue = None
    error: AgentError | None = None
    artifact_refs: tuple[_Identifier, ...] = ()
    effects: tuple[AgentEffect, ...] = ()

    @model_validator(mode="after")
    def _check_error(self) -> AgentHostToolResult:
        if self.ok == (self.error is not None):
            raise ValueError("failed tools require an error; successful tools must not have one")
        return self


class AgentUsage(AgentContract):
    input_tokens: _NonNegativeInt | None = None
    output_tokens: _NonNegativeInt | None = None
    total_tokens: _NonNegativeInt | None = None
    cost: Annotated[float, Field(ge=0)] | None = None
    currency: _Identifier | None = None

    @model_validator(mode="after")
    def _check_currency(self) -> AgentUsage:
        if self.cost is not None and self.currency is None:
            raise ValueError("reported cost requires a currency")
        return self


class AgentStatusPayload(AgentContract):
    status: AgentTaskStatus
    message: str = ""


class AgentMessageDelta(AgentContract):
    message_id: _Identifier
    delta: str


class AgentMessageCompleted(AgentContract):
    message_id: _Identifier
    text: str


class AgentToolStarted(AgentContract):
    call: AgentHostToolCall


class AgentToolCompleted(AgentContract):
    result: AgentHostToolResult


class AgentActivityUpdated(AgentContract):
    """Observable backend progress, separate from host tool authorization/effects."""

    activity_id: _Identifier
    kind: Literal["runtime", "model", "tool"]
    name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    status: Literal["running", "succeeded", "failed"]
    target: Annotated[str, StringConstraints(strict=True, max_length=512)] = ""


class AgentInputResolved(AgentContract):
    answer: AgentInputAnswer


class AgentArtifactCreated(AgentContract):
    artifact: AgentArtifact


class AgentEventType(str, Enum):
    TASK_STATUS = "task.status"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    ACTIVITY_UPDATED = "activity.updated"
    INPUT_REQUESTED = "input.requested"
    INPUT_RESOLVED = "input.resolved"
    ARTIFACT_CREATED = "artifact.created"
    USAGE_UPDATED = "usage.updated"
    TASK_COMPLETED = "task.completed"


AgentEventPayload = Union[
    AgentStatusPayload,
    AgentMessageDelta,
    AgentMessageCompleted,
    AgentToolStarted,
    AgentToolCompleted,
    AgentActivityUpdated,
    AgentInputRequest,
    AgentInputResolved,
    AgentArtifactCreated,
    AgentUsage,
    AgentTaskCompletion,
]

_EVENT_PAYLOAD_TYPES: dict[AgentEventType, type[AgentContract]] = {
    AgentEventType.TASK_STATUS: AgentStatusPayload,
    AgentEventType.MESSAGE_DELTA: AgentMessageDelta,
    AgentEventType.MESSAGE_COMPLETED: AgentMessageCompleted,
    AgentEventType.TOOL_STARTED: AgentToolStarted,
    AgentEventType.TOOL_COMPLETED: AgentToolCompleted,
    AgentEventType.ACTIVITY_UPDATED: AgentActivityUpdated,
    AgentEventType.INPUT_REQUESTED: AgentInputRequest,
    AgentEventType.INPUT_RESOLVED: AgentInputResolved,
    AgentEventType.ARTIFACT_CREATED: AgentArtifactCreated,
    AgentEventType.USAGE_UPDATED: AgentUsage,
    AgentEventType.TASK_COMPLETED: AgentTaskCompletion,
}


class _AgentEventBody(AgentContract):
    type: AgentEventType
    payload: AgentEventPayload

    @model_validator(mode="before")
    @classmethod
    def _parse_typed_payload(cls, value: object) -> object:
        if isinstance(value, Mapping):
            try:
                event_type = AgentEventType(value.get("type"))
            except (ValueError, TypeError):
                # A transport can skip an unknown type while advancing its
                # cursor; known-event validation must not silently accept it.
                return value
            payload = value.get("payload")
            payload_type = _EVENT_PAYLOAD_TYPES[event_type]
            if isinstance(payload, Mapping):
                return {**value, "payload": payload_type.model_validate(payload)}
            if not isinstance(payload, payload_type):
                raise ValueError(f"payload does not match {event_type.value}")
        return value


class AgentEvent(_AgentEventBody):
    """Persisted public event; event_seq is assigned by the host after commit."""

    schema_version: _PositiveInt = AGENT_EVENT_SCHEMA_VERSION
    task_id: _Identifier
    event_seq: _PositiveInt
    timestamp: _Timestamp


class AgentBackendEvent(_AgentEventBody):
    """Worker event; attempt_id/worker_seq are used for host-side deduplication."""

    attempt_id: _Identifier
    worker_seq: _PositiveInt
    timestamp: _Timestamp


class AgentEventPage(AgentContract):
    task_id: _Identifier
    events: tuple[AgentEvent, ...] = ()
    next_seq: _NonNegativeInt

    @model_validator(mode="after")
    def _check_cursor(self) -> AgentEventPage:
        previous = 0
        for event in self.events:
            if event.task_id != self.task_id or event.event_seq <= previous:
                raise ValueError("event page must contain one task in strictly increasing order")
            previous = event.event_seq
        if self.next_seq < previous:
            raise ValueError("event cursor cannot precede the last returned event")
        return self


class AgentTaskPage(AgentContract):
    tasks: tuple[AgentTask, ...] = ()
    next_cursor: str | None = None


class AgentSessionPage(AgentContract):
    sessions: tuple[AgentSession, ...] = ()
    next_cursor: str | None = None


class AgentArtifactContent(AgentContract):
    artifact: AgentArtifact
    text: str | None = None
    download_ref: _Identifier | None = None

    @model_validator(mode="after")
    def _require_content(self) -> AgentArtifactContent:
        if (self.text is None) == (self.download_ref is None):
            raise ValueError("artifact content requires exactly one text or download reference")
        return self


class AgentDelivery(AgentContract):
    delivery_id: _Identifier
    task_id: _Identifier
    origin: AgentOrigin
    completion: AgentTaskCompletion

    @model_validator(mode="after")
    def _require_roleplay(self) -> AgentDelivery:
        if self.origin.kind != "roleplay":
            raise ValueError("roleplay deliveries require a roleplay origin")
        return self


class AgentDelegationRequest(AgentContract):
    """Role-model arguments only. All identity/policy is supplied out of band."""

    model_config = ConfigDict(extra="forbid")

    task: _Text
    context_refs: tuple[_Identifier, ...] = ()


class AgentBackendConfig(AgentContract):
    backend_id: _Identifier
    backend_version: _Identifier
    runtime_ref: _Identifier | None = None
    state_ref: _Identifier | None = None
    credential_ref: _Identifier | None = None
    options: AgentJsonObject = Field(default_factory=dict)


class AgentTaskExecution(AgentContract):
    task_id: _Identifier
    attempt_id: _Identifier
    request: AgentTaskRequest
    tools: tuple[AgentToolDefinition, ...] = ()
    workspace_ref: _Identifier | None = None


# Adapter-private in-process value. It must never enter a public DTO or IPC frame.
AgentBackendSessionHandle = NewType("AgentBackendSessionHandle", object)


@runtime_checkable
class AgentClient(Protocol):
    """Task API bound to a trusted caller; short failures raise AgentRequestError.

    Implementations own authorization, idempotency, storage and lifecycle.
    Returning a receipt must not wait for model generation to finish.
    """

    def list_backends(self) -> tuple[AgentBackendDescriptor, ...]: ...
    def list_sessions(self, *, cursor: str | None = None, limit: int = 100) -> AgentSessionPage: ...
    def create_session(self, request: AgentSessionRequest) -> AgentSession: ...
    def submit_task(self, request: AgentTaskRequest) -> AgentTaskReceipt: ...
    def list_tasks(
        self, *, session_id: str | None = None, statuses: Sequence[AgentTaskStatus] = (),
        cursor: str | None = None, limit: int = 100,
    ) -> AgentTaskPage: ...
    def get_task(self, task_id: str) -> AgentTask: ...
    def read_events(self, task_id: str, *, after_seq: int = 0, limit: int = 100) -> AgentEventPage: ...
    def cancel_task(self, task_id: str, *, reason: str = "") -> AgentCancellationReceipt: ...
    def respond_input(self, task_id: str, answer: AgentInputAnswer) -> AgentTask: ...
    def read_artifact(self, artifact_id: str, *, revision: str) -> AgentArtifactContent: ...
    def detach_task(self, task_id: str) -> AgentTask: ...
    def close_session(self, session_id: str) -> None: ...


@runtime_checkable
class AgentRequester(Protocol):
    """Narrow, chat-bound delegation port; no backend or caller selection."""

    def request_agent(self, request: AgentDelegationRequest) -> AgentTaskReceipt: ...
    def get_agent_task(self, task_id: str) -> AgentTask: ...
    def cancel_agent_task(self, task_id: str) -> AgentTask: ...


@runtime_checkable
class AgentDelegationInbox(Protocol):
    """Chat lifecycle port, separate from tools visible to the role model."""

    def read_deliveries(self, *, limit: int = 100) -> tuple[AgentDelivery, ...]: ...
    def ack_delivery(self, delivery_id: str) -> None: ...
    def invalidate_origin(self, origin: AgentOrigin, *, reason: str) -> None: ...


@runtime_checkable
class AgentHostPort(Protocol):
    """Task-bound worker callbacks. The host executes and authorizes tools."""

    async def invoke_tool(self, request: AgentHostToolCall) -> AgentHostToolResult: ...
    async def request_input(self, request: AgentInputRequest) -> AgentInputAnswer: ...


@runtime_checkable
class AgentBackend(Protocol):
    """Backend adapter used exclusively inside the independent Agent worker.

    ``run`` returns an async iterator, not an awaitable returning an iterator.
    It emits exactly one task.completed after all automatic work settles.
    ``cancel`` requests stopping; completion still reports the actual outcome.
    The worker reader must remain responsive while these operations execute.
    """

    async def initialize(self, config: AgentBackendConfig) -> AgentBackendDescriptor: ...
    async def open_session(self, config: AgentSessionConfig) -> AgentBackendSessionHandle: ...
    def run(
        self, session: AgentBackendSessionHandle, task: AgentTaskExecution, host: AgentHostPort,
    ) -> AsyncIterator[AgentBackendEvent]: ...
    async def cancel(self, attempt_id: str) -> None: ...
    async def respond(self, input_request_id: str, answer: AgentInputAnswer) -> None: ...
    async def close_session(self, session: AgentBackendSessionHandle) -> None: ...
    async def shutdown(self) -> None: ...


class NullAgentRequester:
    """Unavailable default. Never invents a task ID or a successful receipt."""

    @staticmethod
    def _unavailable() -> AgentRequestError:
        return AgentRequestError(AgentError(
            code=AgentErrorCode.BACKEND_UNAVAILABLE,
            message="Agent is not enabled or its backend is unavailable.",
        ))

    def request_agent(self, request: AgentDelegationRequest) -> AgentTaskReceipt:
        raise self._unavailable()

    def get_agent_task(self, task_id: str) -> AgentTask:
        raise self._unavailable()

    def cancel_agent_task(self, task_id: str) -> AgentTask:
        raise self._unavailable()


__all__ = [
    "AGENT_PROTOCOL_VERSION", "AGENT_EVENT_SCHEMA_VERSION", "AgentJsonObject",
    "AgentContract", "AgentTaskStatus", "AgentErrorCode", "AgentError", "AgentRequestError",
    "AgentBackendCapabilities", "AgentBackendDescriptor", "AgentOrigin", "AgentContext",
    "AgentTextContext", "AgentResourceContext", "AgentArtifactContext", "AgentLimits", "AgentInput",
    "AgentSessionRequest", "AgentSessionConfig", "AgentSession", "AgentTaskRequest", "AgentTaskReceipt",
    "AgentArtifact", "AgentArtifactContent", "AgentEvidence", "AgentEffect", "AgentResult",
    "AgentTask", "AgentTaskCompletion", "AgentCancellationReceipt", "AgentInputOption",
    "AgentInputRequest", "AgentInputAnswer", "AgentToolDefinition", "AgentHostToolCall",
    "AgentHostToolResult", "AgentUsage", "AgentEventType", "AgentEventPayload", "AgentEvent",
    "AgentBackendEvent", "AgentEventPage", "AgentTaskPage", "AgentSessionPage", "AgentStatusPayload",
    "AgentMessageDelta", "AgentMessageCompleted", "AgentToolStarted", "AgentToolCompleted",
    "AgentInputResolved", "AgentArtifactCreated", "AgentDelivery", "AgentDelegationRequest",
    "AgentBackendConfig", "AgentTaskExecution", "AgentBackendSessionHandle", "AgentClient",
    "AgentRequester", "AgentDelegationInbox", "AgentHostPort", "AgentBackend", "NullAgentRequester",
]
