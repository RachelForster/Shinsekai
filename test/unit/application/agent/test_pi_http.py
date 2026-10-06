"""Desktop composition and public HTTP API against a verified official Pi."""

from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.agent.pi_configuration import prepare_pi_agent
from application.agent.runtime import AgentRuntime
from application.agent.skills import BUNDLED_SKILL_NAMES
from core.agent.pi_runtime import PiRuntime
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.transport.agent_http_tools import build_bridge_http_tools
from test.unit.application.agent.test_pi_configuration import ModelConfig
from test.unit.application.agent.test_runtime import wait_for


@pytest.mark.skipif(
    not os.environ.get("SHINSEKAI_TEST_PI_BINARY"),
    reason="Set SHINSEKAI_TEST_PI_BINARY to a verified official Pi binary",
)
@pytest.mark.parametrize("behavior", ["restart", "shutdown", "bridge-tools"])
def test_official_pi_through_application_lifecycle_and_http(tmp_path, behavior):
    requests = []
    received, release = threading.Event(), threading.Event()

    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            assert self.headers["Authorization"] == "Bearer fixture-http-key"
            assert bool(body.get("tools")) == (behavior == "bridge-tools")
            if behavior == "shutdown":
                received.set()
                release.wait(10)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            deltas = [
                ({"role": "assistant"}, None),
                ({"content": "真实 Pi HTTP 验证完成。"}, None),
                ({}, "stop"),
            ]
            if behavior == "bridge-tools" and not any(
                message.get("role") == "tool" for message in body["messages"]
            ):
                function = next(
                    tool["function"]
                    for tool in body["tools"]
                    if "shinsekai.bridge.read" in tool["function"]["description"]
                )
                deltas = [
                    ({"role": "assistant"}, None),
                    (
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "bridge-read-call",
                                    "type": "function",
                                    "function": {
                                        "name": function["name"],
                                        "arguments": json.dumps(
                                            {"operation": "characters.list"}
                                        ),
                                    },
                                }
                            ]
                        },
                        None,
                    ),
                    ({}, "tool_calls"),
                ]
            for delta, finish in deltas:
                event = {
                    "id": "http-completion",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test-model",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(
                    ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    model_thread = threading.Thread(target=model.serve_forever, daemon=True)
    model_thread.start()
    config = ModelConfig(
        key="fixture-http-key", url=f"http://127.0.0.1:{model.server_port}/v1"
    )

    def prepare(config, **kwargs):
        return prepare_pi_agent(
            config,
            runtime=PiRuntime(Path(os.environ["SHINSEKAI_TEST_PI_BINARY"])),
            **kwargs,
        )

    bridge = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    tools = (
        build_bridge_http_tools(*bridge.server_address, "http-bridge-token")
        if behavior == "bridge-tools"
        else ()
    )
    if behavior == "bridge-tools":
        config.config = SimpleNamespace(
            api_config=config.config.api_config, characters=[{"name": "HTTP 人物"}]
        )
    runtime = AgentRuntime(config, tmp_path, prepare=prepare, tools=tools)
    runtime.start()
    wait_for(lambda: runtime.snapshot()["status"] == "ready")
    bridge.state = SimpleNamespace(
        auth_token="http-bridge-token",
        services=SimpleNamespace(agent=runtime),
        config_manager=config,
    )
    bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    bridge_thread.start()

    def request(method, path, body=None):
        connection = http.client.HTTPConnection(*bridge.server_address, timeout=10)
        connection.request(
            method,
            "/api/agent" + path,
            None if body is None else json.dumps(body),
            {
                "Content-Type": "application/json",
                "X-Shinsekai-Bridge-Token": "http-bridge-token",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status < 400, payload
        return payload

    try:
        session = request("POST", "/sessions", {})
        for index in range(2 if behavior == "restart" else 1):
            receipt = request(
                "POST",
                f'/sessions/{session["sessionId"]}/tasks',
                {"requestId": f"message-{index}", "text": f"public message {index}"},
            )
            task_path = f'/tasks/{receipt["taskId"]}'
            if behavior == "shutdown":
                assert received.wait(15)
                process = runtime._service._supervisor.process
                assert request("POST", "/runtime/stop", {})["status"] == "stopped"
                assert process.poll() is not None
                assert runtime._service._closed
                break
            task = wait_for(
                lambda: (
                    (value if value["status"] in {"succeeded", "failed"} else None)
                    if (value := request("GET", task_path))
                    else None
                ),
                timeout=25,
            )
            assert task["status"] == "succeeded", task["error"]
            assert task["result"]["summary"] == "真实 Pi HTTP 验证完成。"
            page = request("GET", task_path + "/events?afterSeq=0&limit=1000")
            assert any(event["type"] == "message.delta" for event in page["events"])
            if index == 0:
                runtime.close()
                runtime = AgentRuntime(config, tmp_path, prepare=prepare, tools=tools)
                runtime.start()
                wait_for(lambda: runtime.snapshot()["status"] == "ready")
                bridge.state.services.agent = runtime
                assert (
                    request("GET", "/sessions")["sessions"][0]["sessionId"]
                    == session["sessionId"]
                )
        if behavior == "bridge-tools":
            assert len(requests) == 2
            messages = requests[-1]["messages"]
            response = next(
                json.loads(message["content"])
                for message in messages
                if message.get("role") == "tool"
            )
            assert response["data"] == [{"name": "HTTP 人物"}]
            assert any(event["type"] == "tool.completed" for event in page["events"])
        if behavior == "restart":
            assert len(requests) == 2
            model_messages = json.dumps(requests[0]["messages"], ensure_ascii=False)
            # Pi omits its native skill index without read/bash; host preloading
            # must supply the instructions independently of that index.
            assert "<available_skills>" not in model_messages
            for name in BUNDLED_SKILL_NAMES:
                assert name in model_messages
            assert "下方已提供完整技能正文" in model_messages
            assert "python -m sdk.cli create my_plugin" in model_messages
            assert any(
                message.get("role") == "assistant"
                and "真实 Pi HTTP" in str(message.get("content"))
                for message in requests[1]["messages"]
            )
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl", ".sqlite"}:
                assert b"fixture-http-key" not in path.read_bytes()
                assert b"http-bridge-token" not in path.read_bytes()
    finally:
        release.set()
        bridge.shutdown()
        bridge.server_close()
        runtime.close()
        model.shutdown()
        model.server_close()
        bridge_thread.join(3)
        model_thread.join(3)
