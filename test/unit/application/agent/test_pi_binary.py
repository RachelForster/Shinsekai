"""Opt-in contract test against the official binary and a local fake model server."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from application.agent.execute_host_tool import AgentHostTool
from application.agent.management import AgentProfile, AgentService
from application.agent.pi_configuration import prepare_pi_agent
from core.agent.pi_runtime import PiRuntime
from sdk.agent import (
    AgentHostToolResult,
    AgentOrigin,
    AgentSessionRequest,
    AgentTaskRequest,
)
from test.unit.application.agent.test_pi_configuration import ModelConfig


def terminal(client, receipt):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        task = client.get_task(receipt.task_id)
        if task.status.is_terminal:
            return task
        time.sleep(0.02)
    raise AssertionError("Pi task did not settle")


@pytest.mark.skipif(
    not os.environ.get("SHINSEKAI_TEST_PI_BINARY"),
    reason="Set SHINSEKAI_TEST_PI_BINARY to a verified official Pi binary",
)
@pytest.mark.parametrize("behavior", ["normal", "cancel", "auth-error"])
def test_official_pi_stream_tool_and_session_resume(tmp_path, behavior):
    calls, requests = [], []
    received, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            assert self.headers["Authorization"] == "Bearer fixture-api-key"
            assert self.path == "/v1/chat/completions"
            if behavior == "auth-error":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    b'{"error":{"message":"Invalid test credential","code":"invalid_api_key"}}'
                )
                return
            if behavior == "cancel":
                received.set()
                release.wait(10)
                return
            tool_done = any(
                message.get("role") == "tool" for message in body["messages"]
            )
            if not tool_done:
                delta = {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "fixture-tool-call",
                            "type": "function",
                            "function": {
                                "name": next(
                                    tool["function"]["name"]
                                    for tool in body["tools"]
                                    if "Host tool test.inspect:"
                                    in tool["function"]["description"]
                                ),
                                "arguments": '{"value":7}',
                            },
                        }
                    ]
                }
                finish = "tool_calls"
            else:
                delta, finish = {"content": "Pi 接入完成\u2028并保留会话。"}, "stop"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for payload in (
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant"},
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 4,
                        "total_tokens": 16,
                    },
                },
            ):
                event = {
                    "id": "fixture-completion",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test-model",
                    **payload,
                }
                self.wfile.write(
                    ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")

    class Input(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        value: int

    class Output(BaseModel):
        result: int

    def inspect(task, call):
        calls.append(call)
        return AgentHostToolResult(
            call_id=call.call_id, ok=True, data={"result": call.arguments["value"]}
        )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        setup = prepare_pi_agent(
            ModelConfig(
                key="fixture-api-key", url=f"http://127.0.0.1:{server.server_port}/v1"
            ),
            root=tmp_path,
            runtime=PiRuntime(Path(os.environ["SHINSEKAI_TEST_PI_BINARY"])),
        )
        tool = AgentHostTool.from_models(
            name="test.inspect",
            description="Inspect an integer",
            input_model=Input,
            output_model=Output,
            effect_kind="read",
            execute=inspect,
        )
        with AgentService(
            tmp_path / "agent.sqlite",
            backend=setup.backend,
            worker_environment=setup.worker_environment,
            profiles=(AgentProfile(tool_names=("test.inspect",)),),
            tools=(tool,),
        ) as service:
            origin = AgentOrigin(kind="user", caller_id="pi-test")
            client = service.bind(origin)
            session = client.create_session(
                AgentSessionRequest(
                    backend_id="pi", profile_id="basic", model_ref=setup.model_ref
                )
            )
            for index in range(2 if behavior == "normal" else 1):
                receipt = client.submit_task(
                    AgentTaskRequest(
                        request_id=f"request-{index}",
                        session_id=session.session_id,
                        origin=origin,
                        input={"text": "验证工具并继续会话"},
                        lifetime="detached",
                    )
                )
                if behavior == "cancel":
                    assert received.wait(15), list(service._supervisor.stderr)
                    client.cancel_task(receipt.task_id)
                task = terminal(client, receipt)
                if behavior == "cancel":
                    assert task.status == "cancelled", task.error
                    events = client.read_events(task.task_id).events
                    assert sum(event.type == "task.completed" for event in events) == 1
                    continue
                if behavior == "auth-error":
                    assert task.status == "failed", task.error
                    assert task.error.code == "AUTH_REQUIRED"
                    continue
                assert task.status == "succeeded", (
                    task.error,
                    list(service._supervisor.stderr),
                )
                assert task.result.summary == "Pi 接入完成\u2028并保留会话。"
                assert any(
                    event.type == "message.delta"
                    for event in client.read_events(task.task_id).events
                )
                assert not task.result.effects
            assert len(calls) == (1 if behavior == "normal" else 0)
            assert len(requests) == (3 if behavior == "normal" else 1)
            assert client.list_backends()[0].capabilities.native_session_resume
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".jsonl", ".sqlite"):
                assert b"fixture-api-key" not in path.read_bytes(), path
    finally:
        release.set()
        server.shutdown()
        server.server_close()
