"""Actual subprocess tests for the portable task core and its failure boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from application.agent.management import AgentProfile, AgentService
from application.agent.execute_host_tool import AgentHostTool
from core.agent.storage import AgentStore
from sdk.agent import (
    AgentClient,
    AgentBackendConfig,
    AgentEffect,
    AgentHostToolCall,
    AgentHostToolResult,
    AgentInputAnswer,
    AgentLimits,
    AgentOrigin,
    AgentRequestError,
    AgentSessionRequest,
    AgentTaskRequest,
)


ORIGIN = AgentOrigin(kind="user", caller_id="test-user")


def client_session(service, *, caller=ORIGIN, profile="basic", administrator=False):
    client = service.bind(caller, profile_ids=(profile,), administrator=administrator)
    session = client.create_session(
        AgentSessionRequest(
            backend_id="mock", profile_id=profile, model_ref="mock-model"
        )
    )
    return client, session


def submit(client, session, *, request_id="request-1", plan=None, limits=None):
    context = (
        [
            {
                "kind": "text",
                "source": "mock:plan",
                "text": json.dumps(plan),
                "purpose": "contract test",
            }
        ]
        if plan
        else []
    )
    return client.submit_task(
        AgentTaskRequest(
            request_id=request_id,
            session_id=session.session_id,
            origin=client.origin,
            input={"text": "Inspect the service."},
            context=context,
            limits=limits or AgentLimits(),
            lifetime="origin-bound" if client.origin.kind == "roleplay" else "detached",
        )
    )


def wait_for(predicate, *, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Agent condition did not become true")


def terminal(client, task_id):
    return wait_for(
        lambda: (
            task if (task := client.get_task(task_id)).status.is_terminal else None
        )
    )


def event_seen(client, task_id, kind):
    return wait_for(
        lambda: next(
            (
                event
                for event in client.read_events(task_id).events
                if event.type == kind
            ),
            None,
        )
    )


@pytest.fixture
def service(tmp_path):
    owner = AgentService(tmp_path / "agent.sqlite")
    yield owner
    owner.close()


def test_submission_is_short_and_worker_runs_in_a_different_process(service):
    client, session = client_session(service)
    assert isinstance(client, AgentClient)
    receipt = submit(client, session, plan={"delayMs": 1500})
    assert receipt.status == "queued"  # No worker was even started by submit.
    service.start()
    event_seen(client, receipt.task_id, "message.delta")
    assert client.get_task(receipt.task_id).status == "running"
    task = terminal(client, receipt.task_id)
    assert task.result.data["workerPid"] != os.getpid()
    page = client.read_events(task.task_id, limit=2)
    rest = client.read_events(task.task_id, after_seq=page.next_seq)
    events = (*page.events, *rest.events)
    assert [event.event_seq for event in events] == list(range(1, len(events) + 1))
    assert sum(event.type == "task.completed" for event in events) == 1
    assert events[-1].payload.status == "succeeded"


def test_request_replay_works_when_queue_is_full_and_after_session_is_closed(tmp_path):
    with AgentService(tmp_path / "agent.sqlite", max_queued=1) as owner:
        owner.queue_paused = True
        client, session = client_session(owner)
        first = submit(client, session)
        assert submit(client, session).task_id == first.task_id
        with pytest.raises(AgentRequestError) as conflict:
            submit(client, session, plan={"delayMs": 1})
        assert conflict.value.error.code == "IDEMPOTENCY_CONFLICT"
        with pytest.raises(AgentRequestError) as full:
            submit(client, session, request_id="second")
        assert full.value.error.code == "LIMIT_EXCEEDED"
        client.cancel_task(first.task_id)
        client.close_session(session.session_id)
        assert submit(client, session).status == "cancelled"


def test_caller_cannot_spoof_origin_or_read_another_callers_tasks(service):
    client, session = client_session(service)
    other, _ = client_session(
        service, caller=AgentOrigin(kind="plugin", caller_id=ORIGIN.caller_id)
    )
    receipt = submit(client, session)
    with pytest.raises(AgentRequestError) as denied:
        other.get_task(receipt.task_id)
    assert denied.value.error.code == "AUTH_REQUIRED"
    assert not other.list_tasks().tasks
    request = AgentTaskRequest(
        request_id="fake",
        session_id=session.session_id,
        origin=other.origin,
        input={"text": "inspect"},
        lifetime="detached",
    )
    with pytest.raises(AgentRequestError):
        client.submit_task(request)
    admin = service.bind(AgentOrigin(kind="user", caller_id="ui"), administrator=True)
    assert admin.get_task(receipt.task_id).task_id == receipt.task_id


def test_fifo_serial_execution_and_session_busy(service):
    client, session = client_session(service)
    first = submit(client, session, plan={"delayMs": 500})
    second = submit(client, session, request_id="second")
    with pytest.raises(AgentRequestError) as busy:
        client.close_session(session.session_id)
    assert busy.value.error.code == "SESSION_BUSY"
    service.start()
    event_seen(client, first.task_id, "message.delta")
    assert client.get_task(second.task_id).status == "queued"
    a, b = terminal(client, first.task_id), terminal(client, second.task_id)
    assert a.status == b.status == "succeeded"
    events = client.read_events(second.task_id).events
    assert (
        next(event.timestamp for event in events if event.payload.status == "running")
        >= a.updated_at
    )
    client.close_session(session.session_id)
    assert not client.list_sessions().sessions


@pytest.mark.parametrize("running", [False, True])
def test_cancel_is_idempotent_and_does_not_announce_success(service, running):
    client, session = client_session(service)
    receipt = submit(client, session, plan={"delayMs": 30000})
    if running:
        service.start()
        event_seen(client, receipt.task_id, "message.delta")
    response = client.cancel_task(receipt.task_id)
    assert response.accepted
    task = terminal(client, receipt.task_id)
    assert task.status == "cancelled"
    assert not client.cancel_task(receipt.task_id).accepted
    assert (
        sum(
            event.type == "task.completed"
            for event in client.read_events(receipt.task_id).events
        )
        == 1
    )


def test_wall_clock_limit_stops_worker_and_is_structured(service):
    client, session = client_session(service)
    receipt = submit(
        client, session, plan={"delayMs": 30000}, limits=AgentLimits(wall_time_ms=800)
    )
    service.start()
    task = terminal(client, receipt.task_id)
    assert task.status == "interrupted"
    assert task.error.code == "LIMIT_EXCEEDED"
    wait_for(lambda: service._supervisor.process is None)


def test_unsupported_token_limit_is_not_silently_ignored(service):
    client, session = client_session(service)
    receipt = submit(client, session, limits=AgentLimits(max_tokens=10))
    service.start()
    task = terminal(client, receipt.task_id)
    assert task.status == "failed"
    assert task.error.code == "CAPABILITY_UNSUPPORTED"


def test_worker_loss_interrupts_only_its_task_and_new_session_can_run(service):
    client, first_session = client_session(service)
    crashed = submit(client, first_session, plan={"crash": True})
    _, second_session = client_session(service)
    later = submit(client, second_session, request_id="later")
    service.start()
    assert terminal(client, crashed.task_id).status == "interrupted"
    assert terminal(client, later.task_id).status == "succeeded"
    old = submit(client, first_session, request_id="old-session")
    assert terminal(client, old.task_id).error.code == "SESSION_RESUME_UNAVAILABLE"


def test_queue_survives_restart_and_requires_explicit_resume(tmp_path):
    database = tmp_path / "agent.sqlite"
    original = AgentService(database)
    client, session = client_session(original)
    receipt = submit(client, session)
    original.close()
    with AgentService(database) as restored:
        assert restored.queue_paused
        client = restored.bind(ORIGIN)
        time.sleep(0.1)
        assert client.get_task(receipt.task_id).status == "queued"
        assert restored._supervisor.process is None
        restored.resume_queue()
        assert terminal(client, receipt.task_id).status == "succeeded"
    again = AgentService(database)
    try:
        client = again.bind(ORIGIN)
        assert client.get_task(receipt.task_id).status == "succeeded"
        assert submit(client, session).task_id == receipt.task_id
    finally:
        again.close()


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: int


class Output(BaseModel):
    value: int


def host_tool(callback, *, effect="write"):
    return AgentHostTool.from_models(
        name="test.record",
        description="Record a value.",
        effect_kind=effect,
        input_model=Arguments,
        output_model=Output,
        execute=callback,
    )


def applied(call):
    return AgentHostToolResult(
        call_id=call.call_id,
        ok=True,
        data=call.arguments,
        effects=[
            AgentEffect(call_id=call.call_id, tool_name=call.name, state="applied")
        ],
    )


def tools_profile(**overrides):
    return AgentProfile(tool_names=("test.record",), **overrides)


def test_host_tools_use_typed_schemas_and_deduplicate_stable_call_ids(tmp_path):
    calls = []

    def record(task, call):
        calls.append(call.arguments["value"])
        return applied(call)

    with AgentService(
        tmp_path / "agent.sqlite",
        tools=(host_tool(record),),
        profiles=(tools_profile(),),
    ) as owner:
        client, session = client_session(owner)
        call = {"callId": "write-1", "name": "test.record", "arguments": {"value": 7}}
        task = terminal(
            client, submit(client, session, plan={"tools": [call, call]}).task_id
        )
        assert task.status == "succeeded"
        assert calls == [7]
        assert task.result.effects[0].state == "applied"
        assert len(task.result.effects) == 1
        assert (
            sum(
                event.type == "tool.started"
                for event in client.read_events(task.task_id).events
            )
            == 1
        )
        assert task.result.data["tools"] == [{"value": 7}, {"value": 7}]


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("changed-arguments", "IDEMPOTENCY_CONFLICT"),
        ("invalid-arguments", "INVALID_REQUEST"),
        ("unlisted-tool", "TOOL_DENIED"),
        ("budget", "LIMIT_EXCEEDED"),
    ],
)
def test_tool_policy_schema_conflicts_and_budget_do_not_execute_unapproved_work(
    tmp_path, scenario, code
):
    calls = []

    def record(task, call):
        calls.append(call.arguments)
        return applied(call)

    profile = tools_profile(limits=AgentLimits(max_tool_calls=1))
    with AgentService(
        tmp_path / "agent.sqlite", tools=(host_tool(record),), profiles=(profile,)
    ) as owner:
        client, session = client_session(owner)
        a = {"callId": "one", "name": "test.record", "arguments": {"value": 1}}
        b = {"callId": "two", "name": "test.record", "arguments": {"value": 2}}
        plan = (
            [a, {**a, "arguments": {"value": 2}}]
            if scenario == "changed-arguments"
            else [a, b]
        )
        if scenario == "invalid-arguments":
            plan = [{**a, "arguments": {"value": "wrong"}}]
        if scenario == "unlisted-tool":
            plan = [{**a, "name": "workspace.execute"}]
        task = terminal(client, submit(client, session, plan={"tools": plan}).task_id)
        assert task.error.code == code
        assert len(calls) == (1 if scenario in ("changed-arguments", "budget") else 0)


def test_cancel_waits_for_inflight_host_write_and_retains_applied_effect(tmp_path):
    started, release = threading.Event(), threading.Event()

    def record(task, call):
        started.set()
        assert release.wait(timeout=5)
        return applied(call)

    owner = AgentService(
        tmp_path / "agent.sqlite",
        tools=(host_tool(record),),
        profiles=(tools_profile(),),
    )
    try:
        owner.start()
        client, session = client_session(owner)
        call = {"callId": "one", "name": "test.record", "arguments": {"value": 1}}
        receipt = submit(client, session, plan={"tools": [call]})
        assert started.wait(timeout=5)
        assert client.cancel_task(receipt.task_id).task.status == "cancelling"
        time.sleep(0.1)
        assert client.get_task(receipt.task_id).status == "cancelling"
        release.set()
        task = terminal(client, receipt.task_id)
        assert task.status == "cancelled"
        assert task.result.effects[0].state == "applied"
    finally:
        release.set()
        owner.close()


def test_unsettled_write_is_interrupted_and_does_not_release_database_ownership(
    tmp_path,
):
    started, release = threading.Event(), threading.Event()

    def record(task, call):
        started.set()
        assert release.wait(timeout=10)
        return applied(call)

    database = tmp_path / "agent.sqlite"
    owner = AgentService(
        database,
        tools=(host_tool(record),),
        profiles=(tools_profile(),),
        cancel_grace_seconds=0.15,
    )
    try:
        owner.start()
        client, session = client_session(owner)
        receipt = submit(
            client,
            session,
            plan={
                "tools": [
                    {"callId": "one", "name": "test.record", "arguments": {"value": 1}}
                ]
            },
        )
        assert started.wait(timeout=5)
        client.cancel_task(receipt.task_id)
        task = terminal(client, receipt.task_id)
        assert task.status == "interrupted"
        assert task.result.effects[0].state == "unknown"
        with pytest.raises(AgentRequestError) as busy:
            owner.close(timeout=0.1)
        assert busy.value.error.code == "SESSION_BUSY"
        with pytest.raises(RuntimeError, match="already has an owner"):
            AgentStore(database)
    finally:
        release.set()
        owner.close()


def test_input_does_not_block_reader_and_answer_replay_is_idempotent(service):
    client, session = client_session(service)
    receipt = submit(client, session, plan={"question": "Choose a value"})
    service.start()
    event_seen(client, receipt.task_id, "input.requested")
    assert client.get_task(receipt.task_id).status == "waiting_input"
    assert service._supervisor.peer.request("worker.ping", {}) == {"ready": True}
    answer = AgentInputAnswer(input_request_id="mock-question", value="chosen")
    client.respond_input(receipt.task_id, answer)
    task = terminal(client, receipt.task_id)
    assert task.result.data["answer"] == "chosen"
    assert client.respond_input(receipt.task_id, answer).status == "succeeded"
    with pytest.raises(AgentRequestError):
        client.respond_input(
            receipt.task_id,
            AgentInputAnswer(input_request_id="mock-question", value="different"),
        )


@pytest.mark.parametrize("cancel", [True, False])
def test_input_wait_can_be_cancelled_or_expire(tmp_path, cancel):
    with AgentService(
        tmp_path / "agent.sqlite", profiles=(AgentProfile(input_timeout_ms=150),)
    ) as owner:
        client, session = client_session(owner)
        receipt = submit(client, session, plan={"question": "Choose a value"})
        event_seen(client, receipt.task_id, "input.requested")
        if cancel:
            client.cancel_task(receipt.task_id)
        task = terminal(client, receipt.task_id)
        assert task.status == ("cancelled" if cancel else "failed")
        if not cancel:
            assert task.error.code == "INPUT_EXPIRED"
        with pytest.raises(AgentRequestError):
            client.respond_input(
                receipt.task_id,
                AgentInputAnswer(input_request_id="mock-question", value="late"),
            )


def test_host_artifact_content_is_revision_bound_and_caller_authorized(tmp_path):
    holder = {}

    def record(task, call):
        artifact = holder["owner"].publish_text_artifact(
            task.task_id, "diagnostic report", title="Report"
        )
        result = applied(call)
        return result.model_copy(update={"artifact_refs": (artifact.artifact_id,)})

    with AgentService(
        tmp_path / "agent.sqlite",
        tools=(host_tool(record),),
        profiles=(tools_profile(),),
    ) as owner:
        holder["owner"] = owner
        client, session = client_session(owner)
        receipt = submit(
            client,
            session,
            plan={
                "tools": [
                    {"callId": "one", "name": "test.record", "arguments": {"value": 1}}
                ]
            },
        )
        task = terminal(client, receipt.task_id)
        artifact = task.result.artifacts[0]
        assert (
            client.read_artifact(artifact.artifact_id, revision=artifact.revision).text
            == "diagnostic report"
        )
        with pytest.raises(AgentRequestError):
            client.read_artifact(artifact.artifact_id, revision="wrong")
        other = owner.bind(AgentOrigin(kind="plugin", caller_id="another"))
        with pytest.raises(AgentRequestError):
            other.read_artifact(artifact.artifact_id, revision=artifact.revision)


def test_application_crash_preserves_unknown_write_and_never_replays_it(tmp_path):
    database, marker = tmp_path / "agent.sqlite", tmp_path / "written.txt"
    script = r"""
import os, sys, time
from pathlib import Path
from test.unit.application.agent.test_management import ORIGIN, client_session, submit, host_tool, tools_profile
from application.agent.management import AgentService
def write(task, call):
    Path(sys.argv[2]).write_text("written exactly once", encoding="utf-8")
    os._exit(24)
owner = AgentService(sys.argv[1], tools=(host_tool(write),), profiles=(tools_profile(),))
owner.start()
client, session = client_session(owner)
receipt = submit(client, session, plan={"tools": [{"callId": "one", "name": "test.record", "arguments": {"value": 1}}]})
time.sleep(10)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(database), str(marker)],
        timeout=15,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 24, result.stderr
    owner = AgentService(database)
    try:
        client = owner.bind(ORIGIN)
        task = client.list_tasks().tasks[0]
        assert task.status == "interrupted"
        assert task.result.effects[0].state == "unknown"
        owner.start()
        time.sleep(0.1)
        assert owner._supervisor.process is None
        assert marker.read_text(encoding="utf-8") == "written exactly once"
        replay = owner._invoke_tool(
            task.task_id,
            AgentHostToolCall(
                call_id="one", name="test.record", arguments={"value": 1}
            ),
        )
        assert replay.error.code == "WORKER_LOST"
        assert (
            len(
                [
                    event
                    for event in client.read_events(task.task_id).events
                    if event.type == "task.completed"
                ]
            )
            == 1
        )
    finally:
        owner.close()


def test_unknown_events_advance_cursor_and_duplicate_worker_events_do_not_repeat(
    service,
):
    client, session = client_session(service)
    receipt = submit(client, session)
    with service._cv, service._store.transaction():
        task = service._update(
            client.get_task(receipt.task_id), status="running", attemptId="attempt-1"
        )
    event = {
        "attemptId": "attempt-1",
        "workerSeq": 1,
        "timestamp": task.created_at.isoformat(),
        "type": "future.event",
        "payload": {"future": True},
    }
    service._notification("task.event", {"taskId": task.task_id, "event": event})
    service._notification("task.event", {"taskId": task.task_id, "event": event})
    page = client.read_events(task.task_id)
    assert len(page.events) == 1  # queued only; future event is skipped.
    assert page.next_seq == 2
    with pytest.raises(ValueError):
        service._notification(
            "task.event",
            {"taskId": task.task_id, "event": {**event, "payload": {"changed": True}}},
        )
    with service._cv, service._store.transaction():
        from sdk.agent import AgentTaskCompletion

        service._finish(
            service._task(task.task_id), AgentTaskCompletion(status="cancelled")
        )


def test_cli_can_run_a_mock_task_against_persistent_database(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "application.agent",
            "--task",
            "hello",
            "--database",
            str(tmp_path / "agent.sqlite"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert lines[0]["status"] == "queued"
    assert lines[-1]["status"] == "succeeded"


@pytest.mark.parametrize(
    "operation",
    ["list_tasks", "list_sessions", "get_task", "cancel_task", "close_session"],
)
def test_closed_service_returns_portable_errors(tmp_path, operation):
    owner = AgentService(tmp_path / "agent.sqlite")
    client, session = client_session(owner)
    receipt = submit(client, session)
    owner.close()
    argument = (
        ()
        if operation.startswith("list_")
        else (session.session_id if operation == "close_session" else receipt.task_id,)
    )
    with pytest.raises(AgentRequestError) as failure:
        getattr(client, operation)(*argument)
    assert failure.value.error.code == "BACKEND_UNAVAILABLE"


def role_origin():
    return AgentOrigin(
        kind="roleplay",
        caller_id="chat",
        conversation_id="conversation",
        branch_id="branch",
        chat_instance_id="instance",
        source_turn_id="turn",
        context_epoch=1,
    )


@pytest.mark.parametrize("detached", [False, True])
def test_origin_revocation_cancels_only_origin_bound_work(tmp_path, detached):
    valid = threading.Event()
    valid.set()
    with AgentService(
        tmp_path / "agent.sqlite", origin_valid=lambda origin: valid.is_set()
    ) as owner:
        role, session = client_session(owner, caller=role_origin())
        receipt = submit(role, session, plan={"delayMs": 1000})
        event_seen(role, receipt.task_id, "message.delta")
        admin = owner.bind(ORIGIN, administrator=True)
        if detached:
            admin.detach_task(receipt.task_id)
        valid.clear()
        task = terminal(admin, receipt.task_id)
        assert task.status == ("succeeded" if detached else "cancelled")
        with pytest.raises(AgentRequestError):
            role.detach_task(receipt.task_id)


def test_recovered_role_queue_revalidates_origin_before_execution(tmp_path):
    database = tmp_path / "agent.sqlite"
    original = AgentService(database, origin_valid=lambda origin: True)
    role, session = client_session(original, caller=role_origin())
    receipt = submit(role, session)
    original.close()
    with AgentService(database, origin_valid=lambda origin: False) as restored:
        restored.resume_queue()
        admin = restored.bind(ORIGIN, administrator=True)
        assert terminal(admin, receipt.task_id).status == "cancelled"
        assert restored._supervisor.process is None


def test_invalid_tool_output_keeps_host_reported_applied_effect(tmp_path):
    def record(task, call):
        return applied(call).model_copy(update={"data": {"wrong": True}})

    with AgentService(
        tmp_path / "agent.sqlite",
        tools=(host_tool(record),),
        profiles=(tools_profile(),),
    ) as owner:
        client, session = client_session(owner)
        task = terminal(
            client,
            submit(
                client,
                session,
                plan={
                    "tools": [
                        {
                            "callId": "one",
                            "name": "test.record",
                            "arguments": {"value": 1},
                        }
                    ]
                },
            ).task_id,
        )
        assert task.status == "failed"
        assert task.result.effects[0].state == "applied"


def test_early_backend_completion_is_held_until_execution_settles(tmp_path):
    script = r"""
import asyncio
from datetime import datetime, timezone
from ai.agent.backends.mock import MockAgentBackend
from sdk.agent import AgentBackendEvent
from application.agent.worker import Worker
async def run(self, session, task, host):
    yield AgentBackendEvent(attempt_id=task.attempt_id, worker_seq=1, timestamp=datetime.now(timezone.utc),
        type="message.delta", payload={"messageId": "one", "delta": "working"})
    yield AgentBackendEvent(attempt_id=task.attempt_id, worker_seq=2, timestamp=datetime.now(timezone.utc),
        type="task.completed", payload={"status": "succeeded", "result": {"summary": "done", "effects": [
            {"callId": "fake", "toolName": "fake", "state": "applied"}]}})
    await asyncio.sleep(0.8)
MockAgentBackend.run = run
raise SystemExit(Worker().run())
"""
    with AgentService(
        tmp_path / "agent.sqlite", worker_command=(sys.executable, "-c", script)
    ) as owner:
        client, session = client_session(owner)
        receipt = submit(client, session)
        event_seen(client, receipt.task_id, "message.delta")
        time.sleep(0.1)
        assert client.get_task(receipt.task_id).status == "running"
        task = terminal(client, receipt.task_id)
        assert task.status == "succeeded"
        assert not task.result.effects  # Only the host ledger supplies operation facts.


def test_recovered_queue_cannot_switch_backend(tmp_path):
    database = tmp_path / "agent.sqlite"
    service = AgentService(database)
    client, session = client_session(service)
    receipt = submit(client, session)
    service.close()
    with AgentService(
        database, backend=AgentBackendConfig(backend_id="pi", backend_version="1")
    ) as restored:
        client = restored.bind(ORIGIN)
        assert restored.queue_paused
        restored.resume_queue()
        task = terminal(client, receipt.task_id)
        assert task.status == "failed"
        assert task.error.code == "SESSION_BACKEND_MISMATCH"
        assert restored._supervisor.process is None
