"""Authenticated UI transport; caller identity and policy stay in the host."""

from __future__ import annotations

from functools import wraps
from http import HTTPStatus

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from application.agent.runtime import UI_ORIGIN
from sdk.agent import (
    AgentError,
    AgentInputAnswer,
    AgentRequestError,
    AgentTaskRequest,
    AgentTaskStatus,
)
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, JsonResponse, Route


class _SubmitTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: StrictStr = Field(min_length=1, max_length=200)
    text: StrictStr = Field(min_length=1, max_length=64000)


class _CancelTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: StrictStr = Field(default="", max_length=1000)


def _invalid(message="Invalid Agent request"):
    return AgentRequestError(AgentError(code="INVALID_REQUEST", message=message))


def _runtime(request: ApiRequest):
    services = getattr(request.state, "services", None)
    runtime = getattr(services, "agent", None)
    if runtime is None:
        raise AgentRequestError(
            AgentError(
                code="BACKEND_UNAVAILABLE",
                message="Agent runtime is unavailable",
                retryable=True,
            )
        )
    return runtime


def _number(request, name, default, *, minimum=0, maximum=None):
    value = (request.query.get(name) or [str(default)])[0]
    if not value.isascii() or not value.isdecimal():
        raise _invalid("Invalid Agent pagination")
    value = int(value)
    if value < minimum or (maximum is not None and value > maximum):
        raise _invalid("Invalid Agent pagination")
    return value


def _cursor(request):
    return (request.query.get("cursor") or [None])[0]


def _endpoint(handler):
    @wraps(handler)
    def invoke(request):
        try:
            return handler(request, _runtime(request))
        except (ValidationError, ValueError, TypeError) as exc:
            raise _invalid() from exc

    return invoke


@_endpoint
def _status(request, runtime):
    return JsonResponse(runtime.snapshot())


@_endpoint
def _start(request, runtime):
    if request.body:
        raise _invalid()
    runtime.start()
    return JsonResponse(runtime.snapshot(), HTTPStatus.ACCEPTED)


@_endpoint
def _stop(request, runtime):
    if request.body:
        raise _invalid()
    runtime.close()
    return JsonResponse(runtime.snapshot())


@_endpoint
def _resume(request, runtime):
    if request.body:
        raise _invalid()
    runtime.resume_queue()
    return JsonResponse(runtime.snapshot())


@_endpoint
def _backends(request, runtime):
    with runtime.access() as client:
        return JsonResponse(
            {"backends": [item.to_wire() for item in client.list_backends()]}
        )


@_endpoint
def _sessions(request, runtime):
    if request.method == "POST":
        if request.body:
            raise _invalid("Session model and profile are selected by the application")
        return JsonResponse(runtime.create_session().to_wire(), HTTPStatus.CREATED)
    with runtime.access() as client:
        return JsonResponse(
            client.list_sessions(
                cursor=_cursor(request),
                limit=_number(request, "limit", 100, minimum=1, maximum=1000),
            ).to_wire()
        )


@_endpoint
def _close_session(request, runtime):
    if request.body:
        raise _invalid()
    with runtime.access() as client:
        client.close_session(request.params["sessionId"])
    return JsonResponse({"closed": True})


@_endpoint
def _submit(request, runtime):
    body = _SubmitTask.model_validate(request.body)
    task = AgentTaskRequest(
        request_id=body.requestId,
        session_id=request.params["sessionId"],
        origin=UI_ORIGIN,
        input={"text": body.text},
        lifetime="detached",
    )
    with runtime.access(ready=True) as client:
        snapshot = runtime.snapshot()
        if snapshot["queuePaused"]:
            raise AgentRequestError(
                AgentError(
                    code="SESSION_BUSY",
                    message="Resume or cancel the recovered Agent queue first",
                )
            )
        cursor, session = None, None
        while session is None:
            page = client.list_sessions(cursor=cursor, limit=1000)
            session = next(
                (item for item in page.sessions if item.session_id == task.session_id),
                None,
            )
            cursor = page.next_cursor
            if cursor is None:
                break
        if (
            session is None
            or session.model_ref != snapshot["modelRef"]
            or snapshot["configurationChanged"]
        ):
            raise AgentRequestError(
                AgentError(
                    code="SESSION_BACKEND_MISMATCH",
                    message="Create a session for the current model configuration",
                )
            )
        return JsonResponse(client.submit_task(task).to_wire(), HTTPStatus.ACCEPTED)


@_endpoint
def _tasks(request, runtime):
    statuses = tuple(
        AgentTaskStatus(value) for value in request.query.get("status", [])
    )
    with runtime.access() as client:
        return JsonResponse(
            client.list_tasks(
                session_id=(request.query.get("sessionId") or [None])[0],
                statuses=statuses,
                cursor=_cursor(request),
                limit=_number(request, "limit", 100, minimum=1, maximum=1000),
            ).to_wire()
        )


@_endpoint
def _task(request, runtime):
    with runtime.access() as client:
        return JsonResponse(client.get_task(request.params["taskId"]).to_wire())


@_endpoint
def _events(request, runtime):
    with runtime.access() as client:
        return JsonResponse(
            client.read_events(
                request.params["taskId"],
                after_seq=_number(request, "afterSeq", 0),
                limit=_number(request, "limit", 100, minimum=1, maximum=1000),
            ).to_wire()
        )


@_endpoint
def _cancel(request, runtime):
    body = _CancelTask.model_validate(request.body)
    with runtime.access() as client:
        return JsonResponse(
            client.cancel_task(request.params["taskId"], reason=body.reason).to_wire()
        )


@_endpoint
def _input(request, runtime):
    answer = AgentInputAnswer.model_validate(request.body)
    with runtime.access() as client:
        return JsonResponse(
            client.respond_input(request.params["taskId"], answer).to_wire()
        )


@_endpoint
def _detach(request, runtime):
    if request.body:
        raise _invalid()
    with runtime.access() as client:
        return JsonResponse(client.detach_task(request.params["taskId"]).to_wire())


@_endpoint
def _artifact(request, runtime):
    revision = (request.query.get("revision") or [""])[0]
    if not revision:
        raise _invalid("Artifact revision is required")
    with runtime.access() as client:
        return JsonResponse(
            client.read_artifact(
                request.params["artifactId"], revision=revision
            ).to_wire()
        )


AGENT_ROUTES = tuple(
    Route(
        methods=frozenset(methods),
        pattern="/api/agent" + path,
        handler=handler,
        body_kind=BodyKind.NONE if methods == ("GET",) else BodyKind.JSON,
        name="agent." + name,
    )
    for methods, path, handler, name in (
        (("GET",), "/runtime", _status, "runtime"),
        (("POST",), "/runtime/start", _start, "start"),
        (("POST",), "/runtime/stop", _stop, "stop"),
        (("POST",), "/queue/resume", _resume, "resume"),
        (("GET",), "/backends", _backends, "backends"),
        (("GET", "POST"), "/sessions", _sessions, "sessions"),
        (("POST",), "/sessions/{sessionId}/tasks", _submit, "submit"),
        (("POST",), "/sessions/{sessionId}/close", _close_session, "close_session"),
        (("GET",), "/tasks", _tasks, "tasks"),
        (("GET",), "/tasks/{taskId}", _task, "task"),
        (("GET",), "/tasks/{taskId}/events", _events, "events"),
        (("POST",), "/tasks/{taskId}/cancel", _cancel, "cancel"),
        (("POST",), "/tasks/{taskId}/input", _input, "input"),
        (("POST",), "/tasks/{taskId}/detach", _detach, "detach"),
        (("GET",), "/artifacts/{artifactId}", _artifact, "artifact"),
    )
)
