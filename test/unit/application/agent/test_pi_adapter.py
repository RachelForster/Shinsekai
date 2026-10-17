import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

import ai.agent.backends.pi as adapter
from ai.agent.backends.pi_rpc import PiRpcProcess
from sdk.agent import (
    AgentBackendConfig,
    AgentHostToolResult,
    AgentInputAnswer,
    AgentSessionConfig,
    AgentTaskExecution,
    AgentTaskRequest,
    AgentToolDefinition,
    AgentRequestError,
)

FAKE_PI = r"""
import json, os, socket, sys, threading, time
from pathlib import Path
scenario = sys.argv[1]
lock, stopped, answered = threading.Lock(), threading.Event(), threading.Event()
def emit(record):
    with lock:
        sys.stdout.buffer.write(json.dumps(record, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()
def callback(request):
    request['token'] = os.environ['SHINSEKAI_PI_HOST_TOKEN']
    with socket.create_connection(('127.0.0.1', int(os.environ['SHINSEKAI_PI_HOST_PORT']))) as stream:
        stream.sendall(json.dumps(request).encode() + b'\n')
        return json.loads(stream.makefile('rb').readline())
tools = []
if os.environ.get('SHINSEKAI_PI_TOOLS'):
    tools = json.loads(Path(os.environ['SHINSEKAI_PI_TOOLS']).read_text())
    callback({'kind':'ready', 'names':[tool['nativeName'] for tool in tools], 'activeTools':sys.argv[sys.argv.index('--tools')+1].split(',')})
def run():
    if scenario == 'die': os._exit(7)
    root = Path.cwd().parent / 'native'
    root.mkdir(exist_ok=True)
    (root / 'session.jsonl').write_text('session-history')
    emit({'type':'agent_start'})
    emit({'type':'message_start','message':{'role':'assistant'}})
    text = 'hello\u2028world'
    if scenario == 'tool':
        emit({'type':'tool_execution_start','toolCallId':'pi-stable-call','toolName':tools[0]['nativeName'],'args':{'value':9}})
        result = callback({'call':{'callId':'pi-stable-call','name':tools[0]['name'],'arguments':{'value':9}}})
        emit({'type':'tool_execution_end','toolCallId':'pi-stable-call','toolName':tools[0]['nativeName'],'result':result,'isError':False})
        text = json.dumps(result['data'])
    if scenario in ('native-tool', 'native-error'):
        emit({'type':'tool_execution_start','toolCallId':'read-call','toolName':'read','args':{'path':'/skills/shinsekai-guide/SKILL.md'}})
        emit({'type':'tool_execution_update','toolCallId':'read-call','toolName':'read','partialResult':{'content':[{'type':'text','text':'unrequested-file-content'}]}})
        emit({'type':'tool_execution_end','toolCallId':'read-call','toolName':'read','result':{'content':[{'type':'text','text':'unrequested-file-content'}]},'isError':False})
        emit({'type':'tool_execution_start','toolCallId':'shell-call','toolName':'powershell','args':{'command':'echo fixture-api-key; password=private-command-password; ' + os.environ['SHINSEKAI_PI_HOST_TOKEN'] + 'x' * 1000}})
        emit({'type':'tool_execution_end','toolCallId':'shell-call','toolName':'powershell','isError':scenario == 'native-error'})
        emit({'type':'auto_retry_start','attempt':1,'errorMessage':'fixture-api-key'})
        emit({'type':'auto_retry_end','success':True})
        emit({'type':'compaction_start','reason':'threshold'})
        emit({'type':'compaction_end','aborted':False,'result':{'summary':'unrequested-compaction-summary'}})
    emit({'type':'message_update','assistantMessageEvent':{'type':'thinking_delta','delta':'unrequested-internal-reasoning'}})
    if scenario == 'input':
        emit({'type':'extension_ui_request','method':'confirm','id':'dialog-1','title':'Confirm','message':'Continue?'})
        answered.wait(5)
    if scenario == 'slow': stopped.wait(10)
    reason = 'aborted' if stopped.is_set() else ('error' if scenario == 'error' else 'stop')
    emit({'type':'message_update','assistantMessageEvent':{'type':'text_delta','delta':text}})
    emit({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':text}], 'stopReason':reason,'errorMessage':'401 fixture-api-key','usage':{'input':5,'output':2,'totalTokens':7}}})
    emit({'type':'agent_end','messages':[],'willRetry':False})
    time.sleep(0.15)
    emit({'type':'agent_settled'})
for line in sys.stdin.buffer:
    request = json.loads(line)
    kind = request['type']
    if kind == 'extension_ui_response':
        answered.set()
        continue
    if scenario == 'invalid':
        sys.stdout.buffer.write(b'not-json\n'); sys.stdout.buffer.flush(); continue
    if scenario == 'wrong-command':
        emit({'type':'response','id':request['id'],'command':'wrong','success':True}); continue
    if scenario == 'silent': continue
    if kind == 'abort': stopped.set()
    data = {'model':{'id':'test-model','provider':'shinsekai'}} if kind == 'get_state' else None
    if kind == 'prompt': data = {'disposition':'started'}
    emit({'type':'response','id':request['id'],'command':kind,'success':True,'data':data})
    if kind == 'prompt': threading.Thread(target=run, daemon=True).start()
"""


def fake_script(tmp_path):
    path = tmp_path / "fake_pi.py"
    path.write_text(FAKE_PI, encoding="utf-8")
    return path


@pytest.mark.parametrize("scenario", ["invalid", "wrong-command", "silent"])
def test_rpc_failure_is_portable_and_stops_process(tmp_path, scenario):
    async def run():
        rpc = PiRpcProcess(
            [sys.executable, str(fake_script(tmp_path)), scenario], cwd=tmp_path, env={}
        )
        # Windows process creation requires the inherited OS environment.
        import os

        rpc.env = os.environ.copy()
        await rpc.start()
        try:
            with pytest.raises(AgentRequestError) as error:
                await rpc.request("get_state", timeout=0.2)
            assert error.value.error.code in ("PROTOCOL_MISMATCH", "WORKER_LOST")
        finally:
            await rpc.close()
        assert rpc.process.returncode is not None

    asyncio.run(run())


class Host:
    def __init__(self):
        self.calls, self.questions = [], []

    async def invoke_tool(self, call):
        self.calls.append(call)
        return AgentHostToolResult(call_id=call.call_id, ok=True, data={"value": 9})

    async def request_input(self, request):
        self.questions.append(request)
        return AgentInputAnswer(input_request_id=request.input_request_id, value=True)


def setup(monkeypatch, tmp_path, scenario):
    script = fake_script(tmp_path)
    monkeypatch.setenv("SHINSEKAI_PI_API_KEY", "fixture-api-key")
    monkeypatch.setattr(
        adapter,
        "PiRpcProcess",
        lambda command, **kwargs: PiRpcProcess(
            [sys.executable, str(script), scenario, *command[1:]], **kwargs
        ),
    )
    policy = tmp_path / "policy.md"
    policy.write_text("trusted system policy")
    backend = adapter.PiAgentBackend()
    backend.executable = Path(sys.executable)
    backend.config = AgentBackendConfig(
        backend_id="pi",
        backend_version="1",
        state_ref=str(tmp_path / "sessions"),
        options={
            "models": {
                "model-ref": {
                    "id": "test-model",
                    "api": "openai-completions",
                    "baseUrl": "http://localhost/v1",
                }
            },
            "policies": {"agent:default": str(policy)},
        },
    )
    session = AgentSessionConfig(
        session_id="as-test",
        backend_id="pi",
        backend_version="1",
        profile_id="basic",
        model_ref="model-ref",
        system_policy_ref="agent:default",
    )
    request = AgentTaskRequest(
        request_id="request-1",
        session_id=session.session_id,
        origin={"kind": "user", "callerId": "test"},
        input={"text": "/login is task text"},
        lifetime="detached",
    )
    tools = (
        (
            AgentToolDefinition(
                name="test.inspect",
                description="Inspect",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                effect_kind="read",
            ),
        )
        if scenario == "tool"
        else ()
    )
    task = AgentTaskExecution(
        task_id="task-1", attempt_id="attempt-1", request=request, tools=tools
    )
    return backend, session, task, Host()


@pytest.mark.parametrize(
    "scenario,status",
    [
        ("normal", "succeeded"),
        ("tool", "succeeded"),
        ("input", "succeeded"),
        ("error", "failed"),
        ("die", "interrupted"),
    ],
)
def test_adapter_maps_events_and_waits_for_settled(
    monkeypatch, tmp_path, scenario, status
):
    async def run():
        backend, config, task, host = setup(monkeypatch, tmp_path, scenario)
        session = await backend.open_session(config)
        started = time.monotonic()
        events = [event async for event in backend.run(session, task, host)]
        assert events[-1].type == "task.completed"
        assert events[-1].payload.status == status
        if scenario != "die":
            assert time.monotonic() - started >= 0.15
            assert any(event.type == "usage.updated" for event in events)
        if scenario == "tool":
            assert host.calls[0].call_id == "pi-stable-call"
            assert host.calls[0].arguments == {"value": 9}
            assert not any(
                event.type == "activity.updated" and event.payload.kind == "tool"
                for event in events
            )
        if scenario == "input":
            assert host.questions[0].question == "Confirm\nContinue?"
        assert "fixture-api-key" not in json.dumps(
            [event.to_wire() for event in events]
        )
        assert backend.rpc is None
        if scenario != "die":
            assert (await backend.open_session(config)).root == session.root
            for path in (session.root / "native").glob("*.jsonl"):
                path.unlink()
            with pytest.raises(AgentRequestError) as error:
                await backend.open_session(config)
            assert error.value.error.code == "SESSION_RESUME_UNAVAILABLE"

    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["native-tool", "native-error"])
def test_native_activity_is_bounded_redacted_and_separate_from_host_tools(
    monkeypatch, tmp_path, scenario
):
    async def run():
        backend, config, task, host = setup(monkeypatch, tmp_path, scenario)
        session = await backend.open_session(config)
        events = [event async for event in backend.run(session, task, host)]
        activities = [
            event.payload for event in events if event.type == "activity.updated"
        ]
        tools = [value for value in activities if value.kind == "tool"]
        assert [(value.name, value.status) for value in tools] == [
            ("read", "running"),
            ("read", "succeeded"),
            ("powershell", "running"),
            ("powershell", "failed" if scenario == "native-error" else "succeeded"),
        ]
        assert tools[0].activity_id == tools[1].activity_id
        assert tools[0].activity_id.startswith(task.attempt_id + ":")
        assert tools[0].target == "/skills/shinsekai-guide/SKILL.md"
        assert len(tools[2].target) == 512
        assert "<redacted>" in tools[2].target
        assert {
            (value.name, value.status)
            for value in activities
            if value.kind == "runtime"
        } == {
            (name, status)
            for name in ("starting", "retrying", "compacting")
            for status in ("running", "succeeded")
        }
        assert any(
            value.name == "responding" and value.status == "running"
            for value in activities
        )
        wire = json.dumps([event.to_wire() for event in events])
        for secret in (
            "fixture-api-key",
            "private-command-password",
            "unrequested-file-content",
            "unrequested-compaction-summary",
            "unrequested-internal-reasoning",
        ):
            assert secret not in wire
        assert not host.calls
        assert events[-1].payload.status == "succeeded"

    asyncio.run(run())


def test_cancel_confirms_pi_child_exit(monkeypatch, tmp_path):
    async def run():
        backend, config, task, host = setup(monkeypatch, tmp_path, "slow")
        session = await backend.open_session(config)
        events = []

        async def consume():
            async for event in backend.run(session, task, host):
                events.append(event)

        consumer = asyncio.create_task(consume())
        deadline = time.monotonic() + 5
        while (
            backend.rpc is None or not (session.root / "native/session.jsonl").exists()
        ) and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        rpc = backend.rpc
        await backend.cancel(task.attempt_id)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        assert rpc.process.returncode is not None
        assert not any(
            event.type == "task.completed" and event.payload.status == "succeeded"
            for event in events
        )

    asyncio.run(run())
