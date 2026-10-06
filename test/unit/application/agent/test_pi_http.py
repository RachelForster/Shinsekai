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
from core.agent.pi_runtime import PiRuntime
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from test.unit.application.agent.test_pi_configuration import ModelConfig
from test.unit.application.agent.test_runtime import wait_for


@pytest.mark.skipif(
    not os.environ.get("SHINSEKAI_TEST_PI_BINARY"),
    reason="Set SHINSEKAI_TEST_PI_BINARY to a verified official Pi binary",
)
@pytest.mark.parametrize("behavior", ["restart", "shutdown"])
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
            assert not body.get("tools")
            if behavior == "shutdown":
                received.set()
                release.wait(10)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [
                ({"role": "assistant"}, None),
                ({"content": "真实 Pi HTTP 验证完成。"}, None),
                ({}, "stop"),
            ]:
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

    runtime = AgentRuntime(config, tmp_path, prepare=prepare)
    runtime.start()
    wait_for(lambda: runtime.snapshot()["status"] == "ready")
    bridge = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    bridge.state = SimpleNamespace(
        auth_token="http-bridge-token", services=SimpleNamespace(agent=runtime)
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
                runtime = AgentRuntime(config, tmp_path, prepare=prepare)
                runtime.start()
                wait_for(lambda: runtime.snapshot()["status"] == "ready")
                bridge.state.services.agent = runtime
                assert (
                    request("GET", "/sessions")["sessions"][0]["sessionId"]
                    == session["sessionId"]
                )
        if behavior == "restart":
            assert len(requests) == 2
            assert any(
                message.get("role") == "assistant"
                and "真实 Pi HTTP" in str(message.get("content"))
                for message in requests[1]["messages"]
            )
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl", ".sqlite"}:
                assert b"fixture-http-key" not in path.read_bytes()
    finally:
        release.set()
        bridge.shutdown()
        bridge.server_close()
        runtime.close()
        model.shutdown()
        model.server_close()
        bridge_thread.join(3)
        model_thread.join(3)
