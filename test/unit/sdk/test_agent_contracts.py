"""Public Agent boundaries: wire compatibility, provenance and backend replacement."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from sdk.agent import (
    AgentArtifact,
    AgentArtifactContent,
    AgentBackend,
    AgentBackendCapabilities,
    AgentBackendConfig,
    AgentBackendDescriptor,
    AgentBackendEvent,
    AgentBackendSessionHandle,
    AgentDelegationRequest,
    AgentDelivery,
    AgentError,
    AgentErrorCode,
    AgentEvent,
    AgentEventPage,
    AgentEventType,
    AgentHostPort,
    AgentHostToolCall,
    AgentHostToolResult,
    AgentInputAnswer,
    AgentInputRequest,
    AgentLimits,
    AgentMessageCompleted,
    AgentMessageDelta,
    AgentOrigin,
    AgentRequester,
    AgentRequestError,
    AgentResult,
    AgentSessionConfig,
    AgentTask,
    AgentTaskCompletion,
    AgentTaskExecution,
    AgentTaskReceipt,
    AgentTaskRequest,
    AgentTaskStatus,
    AgentToolDefinition,
    AgentUsage,
    NullAgentRequester,
)


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def _origin() -> AgentOrigin:
    return AgentOrigin(
        kind="roleplay", caller_id="chat-runtime-01", conversation_id="chat-01",
        branch_id="branch-01", chat_instance_id="instance-01", source_turn_id="turn-18",
        context_epoch=4,
    )


def _request() -> AgentTaskRequest:
    return AgentTaskRequest(
        request_id="req-01", session_id="as-01", input={"text": "Inspect the voice service."},
        origin=_origin(), lifetime="origin-bound",
        context=[{"kind": "resourceRef", "ref": "diagnostics:tts", "source": "host"}],
        limits={"wallTimeMs": 120000, "maxToolCalls": 20},
    )


def _event(kind: str = "message.delta", *, seq: int = 1, **payload) -> AgentEvent:
    return AgentEvent.model_validate({
        "taskId": "at-01", "eventSeq": seq, "timestamp": "2026-10-06T08:00:00+08:00",
        "type": kind, "payload": payload or {"messageId": "msg-01", "delta": "working"},
    })


def test_design_submission_and_receipt_are_executable_contract_examples():
    design = Path(__file__).resolve().parents[3] / "docs" / "AGENT_SYSTEM_DESIGN_zh-CN.md"
    examples = re.findall(r"```json\s*\n(.*?)\n```", design.read_text(encoding="utf-8"), re.S)
    request = AgentTaskRequest.model_validate(json.loads(examples[0]))
    receipt = AgentTaskReceipt.model_validate(json.loads(examples[1]))
    assert request.origin == AgentOrigin.model_validate(json.loads(examples[0])["origin"])
    assert receipt.status is AgentTaskStatus.QUEUED


def test_task_request_round_trips_python_and_camel_case_json():
    request = _request()
    wire = request.to_wire()
    assert wire["requestId"] == "req-01"
    assert wire["limits"]["wallTimeMs"] == 120000
    assert wire["origin"]["sourceTurnId"] == "turn-18"
    assert wire["context"][0]["kind"] == "resourceRef"
    assert "request_id" not in wire
    assert AgentTaskRequest.model_validate_json(json.dumps(wire)) == request
    assert AgentTaskRequest.model_validate(request.model_dump()) == request


@pytest.mark.parametrize("field", [
    "conversation_id", "branch_id", "chat_instance_id", "source_turn_id", "context_epoch",
])
def test_roleplay_origin_requires_complete_binding(field):
    values = _origin().model_dump()
    values.pop(field)
    with pytest.raises(ValidationError, match="complete chat/branch/turn binding"):
        AgentOrigin.model_validate(values)


@pytest.mark.parametrize("override", [
    {"backendId": "other-backend"}, {"sessionId": "someone-else"},
    {"origin": {"kind": "user", "callerId": "admin"}}, {"profileId": "unrestricted"},
])
def test_role_model_request_cannot_supply_host_identity_or_policy(override):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentDelegationRequest.model_validate({"task": "inspect", **override})


@pytest.mark.parametrize("task", ["", "   "])
def test_empty_delegation_is_rejected(task):
    with pytest.raises(ValidationError):
        AgentDelegationRequest(task=task)


@pytest.mark.parametrize("field,value", [
    ("wallTimeMs", -1), ("wallTimeMs", True), ("wallTimeMs", 1.5),
    ("maxToolCalls", "20"), ("maxTokens", 0),
])
def test_execution_limits_reject_invalid_or_coerced_numbers(field, value):
    with pytest.raises(ValidationError):
        AgentLimits.model_validate({field: value})


def test_usage_preserves_unknown_values_and_rejects_invalid_cost():
    assert AgentUsage().to_wire() == {
        "inputTokens": None, "outputTokens": None, "totalTokens": None,
        "cost": None, "currency": None,
    }
    with pytest.raises(ValidationError):
        AgentUsage(cost=0.1)
    with pytest.raises(ValidationError):
        AgentUsage(cost=float("nan"), currency="USD")
    with pytest.raises(ValidationError):
        AgentUsage(input_tokens=True)


def test_contract_json_data_cannot_contain_nonfinite_numbers():
    with pytest.raises(ValidationError):
        AgentResult(summary="invalid", data={"nested": [float("inf")]})


def test_backend_identifiers_are_open_and_new_response_fields_are_tolerated():
    descriptor = AgentBackendDescriptor.model_validate({
        "backendId": "my.future-backend", "version": "2.7", "availability": "ready",
        "capabilities": {"hostTools": True, "futureCapability": True},
        "futureField": {"a": 1},
    })
    assert descriptor.backend_id == "my.future-backend"
    assert descriptor.capabilities.host_tools is True
    assert descriptor.capabilities.tool_policy_enforcement is False
    assert AgentError(code="FUTURE_ERROR", message="readable").code == "FUTURE_ERROR"


def test_events_select_payload_by_type_and_normalize_utc_timestamp():
    event = _event()
    assert isinstance(event.payload, AgentMessageDelta)
    assert event.to_wire()["timestamp"] == "2026-10-06T00:00:00Z"
    assert AgentEvent.model_validate_json(json.dumps(event.to_wire())) == event
    completed = _event("message.completed", messageId="msg-01", text="authoritative")
    assert isinstance(completed.payload, AgentMessageCompleted)


def test_event_rejects_a_payload_for_a_different_known_type():
    with pytest.raises(ValidationError):
        _event("message.delta", messageId="msg-01", text="not a delta")
    with pytest.raises(ValidationError, match="payload does not match"):
        AgentEvent(
            task_id="at-01", event_seq=1, timestamp=NOW, type="message.delta",
            payload=AgentMessageCompleted(message_id="msg-01", text="not a delta"),
        )


def test_unknown_events_and_task_states_are_not_interpreted_as_success():
    with pytest.raises(ValidationError):
        _event("future.event", a=1)
    with pytest.raises(ValidationError):
        _event("task.status", status="future-success")
    with pytest.raises(ValidationError):
        AgentTaskCompletion(status="unknown")


@pytest.mark.parametrize("status", ["queued", "running", "waiting_input", "cancelling"])
def test_task_completed_cannot_contain_an_intermediate_status(status):
    with pytest.raises(ValidationError, match="terminal status"):
        _event("task.completed", status=status)


def test_success_requires_result_and_failures_require_portable_error():
    with pytest.raises(ValidationError):
        AgentTaskCompletion(status="succeeded")
    with pytest.raises(ValidationError):
        AgentTaskCompletion(status="succeeded", result=AgentResult(summary="done"),
                            error=AgentError(code="INVALID_REQUEST", message="bad"))
    with pytest.raises(ValidationError):
        AgentTaskCompletion(status="failed")
    interrupted = AgentTaskCompletion(
        status="interrupted", error=AgentError(code="WORKER_LOST", message="worker exited"),
        result=AgentResult(summary="Partial output.", effects=[{
            "callId": "call-01", "toolName": "characters.save", "state": "unknown",
        }]),
    )
    assert interrupted.result.effects[0].state == "unknown"


def test_running_task_does_not_claim_a_final_result_and_task_round_trips():
    values = {
        **_request().to_wire(), "taskId": "at-01", "status": "running",
        "attemptId": "attempt-01", "createdAt": NOW, "updatedAt": NOW,
    }
    task = AgentTask.model_validate(values)
    assert AgentTask.model_validate(task.to_wire()) == task
    with pytest.raises(ValidationError, match="nonterminal"):
        AgentTask.model_validate({**values, "result": {"summary": "pretend done"}})


def test_event_page_enforces_task_order_and_cursor_without_requiring_contiguous_ids():
    first, later = _event(seq=1), _event(seq=3)
    page = AgentEventPage(task_id="at-01", events=[first, later], next_seq=4)
    assert page.next_seq == 4  # A transport may have skipped unknown event 2 or 4.
    with pytest.raises(ValidationError):
        AgentEventPage(task_id="at-01", events=[later, first], next_seq=3)
    with pytest.raises(ValidationError):
        AgentEventPage(task_id="at-01", events=[first, first], next_seq=1)
    with pytest.raises(ValidationError):
        AgentEventPage(task_id="other-task", events=[first], next_seq=1)
    with pytest.raises(ValidationError):
        AgentEventPage(task_id="at-01", events=[later], next_seq=2)


def test_timestamps_require_timezone_and_cursors_reject_boolean():
    with pytest.raises(ValidationError):
        AgentEvent(task_id="at-01", event_seq=1, timestamp=datetime(2026, 10, 6),
                   type="usage.updated", payload=AgentUsage())
    with pytest.raises(ValidationError):
        AgentEventPage(task_id="at-01", next_seq=True)


def test_tool_calls_cannot_smuggle_another_tasks_identity_and_errors_are_explicit():
    with pytest.raises(ValidationError):
        AgentHostToolCall.model_validate({
            "callId": "call-01", "name": "diagnostics.read", "taskId": "other-task",
        })
    with pytest.raises(ValidationError):
        AgentHostToolResult(call_id="call-01", ok=False)
    with pytest.raises(ValidationError):
        AgentHostToolResult(call_id="call-01", ok=True,
                            error=AgentError(code="TOOL_DENIED", message="denied"))
    result = AgentHostToolResult(call_id="call-01", ok=False,
                                error=AgentError(code="TOOL_DENIED", message="denied"))
    assert result.to_wire()["error"]["code"] == "TOOL_DENIED"


def test_artifacts_use_one_content_form_and_deliveries_require_roleplay_binding():
    artifact = AgentArtifact(
        artifact_id="artifact-01", kind="report", title="Report", mime_type="text/plain",
        size=0, revision="1",
    )
    assert AgentArtifactContent(artifact=artifact, text="").text == ""
    with pytest.raises(ValidationError):
        AgentArtifactContent(artifact=artifact)
    with pytest.raises(ValidationError):
        AgentArtifactContent(artifact=artifact, text="report", download_ref="download-01")
    with pytest.raises(ValidationError, match="roleplay origin"):
        AgentDelivery(delivery_id="delivery-01", task_id="at-01",
                      origin=AgentOrigin(kind="user", caller_id="user-01"),
                      completion=AgentTaskCompletion(status="cancelled"))


@pytest.mark.parametrize("operation", ["request_agent", "get_agent_task", "cancel_agent_task"])
def test_disabled_requester_never_invents_a_successful_task(operation):
    requester = NullAgentRequester()
    assert isinstance(requester, AgentRequester)
    argument = AgentDelegationRequest(task="inspect") if operation == "request_agent" else "at-01"
    with pytest.raises(AgentRequestError) as failure:
        getattr(requester, operation)(argument)
    assert failure.value.error.code == AgentErrorCode.BACKEND_UNAVAILABLE


class _FakeHost:
    def __init__(self):
        self.calls = []

    async def invoke_tool(self, request: AgentHostToolCall) -> AgentHostToolResult:
        self.calls.append(request)
        return AgentHostToolResult(call_id=request.call_id, ok=True, data={"connected": True})

    async def request_input(self, request: AgentInputRequest) -> AgentInputAnswer:
        return AgentInputAnswer(input_request_id=request.input_request_id, value="answer")


class _FakeBackend:
    async def initialize(self, config: AgentBackendConfig) -> AgentBackendDescriptor:
        return AgentBackendDescriptor(
            backend_id=config.backend_id, version=config.backend_version, availability="ready",
            capabilities=AgentBackendCapabilities(host_tools=True, tool_policy_enforcement=True),
        )

    async def open_session(self, config: AgentSessionConfig) -> AgentBackendSessionHandle:
        return AgentBackendSessionHandle({"private_session": config.session_id})

    async def run(self, session: AgentBackendSessionHandle, task: AgentTaskExecution, host: AgentHostPort):
        yield AgentBackendEvent(attempt_id=task.attempt_id, worker_seq=1, timestamp=NOW,
                                type="message.delta", payload=AgentMessageDelta(
                                    message_id="msg-01", delta="checking"))
        result = await host.invoke_tool(AgentHostToolCall(call_id="call-01", name=task.tools[0].name))
        yield AgentBackendEvent(attempt_id=task.attempt_id, worker_seq=2, timestamp=NOW,
                                type="task.completed", payload=AgentTaskCompletion(
                                    status="succeeded", result=AgentResult(summary="Checked.", data=result.data)))

    async def cancel(self, attempt_id: str) -> None:
        pass

    async def respond(self, input_request_id: str, answer: AgentInputAnswer) -> None:
        pass

    async def close_session(self, session: AgentBackendSessionHandle) -> None:
        pass

    async def shutdown(self) -> None:
        pass


@pytest.mark.parametrize("backend_id", ["backend-one", "some.future-backend"])
def test_backend_can_stream_and_call_host_through_the_same_contract(backend_id):
    async def run():
        backend, host = _FakeBackend(), _FakeHost()
        assert isinstance(backend, AgentBackend)
        assert isinstance(host, AgentHostPort)
        descriptor = await backend.initialize(AgentBackendConfig(backend_id=backend_id, backend_version="1"))
        session = await backend.open_session(AgentSessionConfig(
            session_id="as-01", backend_id=backend_id, backend_version="1", profile_id="diagnostics",
            model_ref="model-01", system_policy_ref="policy:1",
        ))
        execution = AgentTaskExecution(task_id="at-01", attempt_id="attempt-01", request=_request(), tools=[
            AgentToolDefinition(name="diagnostics.probe", description="Probe connection.",
                                input_schema={"type": "object"}, output_schema={"type": "object"},
                                effect_kind="read"),
        ])
        events = [event async for event in backend.run(session, execution, host)]
        assert descriptor.backend_id == backend_id
        assert events[-1].type is AgentEventType.TASK_COMPLETED
        assert events[-1].payload.result.data == {"connected": True}
        assert [call.name for call in host.calls] == ["diagnostics.probe"]
        await backend.close_session(session)
        await backend.shutdown()
    asyncio.run(run())


def test_root_exports_stay_lazy_and_do_not_load_a_host_or_backend():
    code = """
import sys
import sdk
assert 'sdk.agent' not in sys.modules
from sdk import AgentBackend, AgentRequester, AgentTask
from sdk.agent import AgentBackend as DirectBackend
assert AgentBackend is DirectBackend
assert not any(name.split('.')[0] in {
    'application', 'ai', 'config', 'core', 'frontend_bridge_core', 'plugin_system'
} for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
