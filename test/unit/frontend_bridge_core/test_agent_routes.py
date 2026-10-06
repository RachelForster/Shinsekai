from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from application.agent.runtime import AgentRuntime, UI_ORIGIN
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from test.unit.application.agent.test_runtime import ModelConfig, mock_setup, wait_for


@pytest.fixture
def live_agent(tmp_path):
    runtime = AgentRuntime(ModelConfig(), tmp_path, prepare=mock_setup)
    runtime.start()
    wait_for(lambda: runtime.snapshot()["status"] == "ready")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = SimpleNamespace(
        services=SimpleNamespace(agent=runtime), auth_token="bridge-test-secret"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, *, token="bridge-test-secret", origin=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=8)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Shinsekai-Bridge-Token"] = token
        if origin:
            headers["Origin"] = origin
        connection.request(
            method,
            path,
            body=None if body is None else json.dumps(body),
            headers=headers,
        )
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    try:
        yield runtime, request
    finally:
        server.shutdown()
        server.server_close()
        runtime.close()
        thread.join(3)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/agent/runtime"),
        ("GET", "/api/agent/sessions"),
        ("POST", "/api/agent/sessions"),
    ],
)
def test_agent_reads_and_writes_require_token_even_on_loopback(
    live_agent, method, path
):
    _, request = live_agent
    assert request(method, path, {} if method == "POST" else None, token="")[0] == 403
    assert (
        request(
            method,
            path,
            {} if method == "POST" else None,
            origin="https://untrusted.example",
        )[0]
        == 403
    )


def test_http_roundtrip_identity_idempotency_events_and_session_close(live_agent):
    runtime, request = live_agent
    status, session = request("POST", "/api/agent/sessions", {})
    assert status == 201
    assert session["owner"] == UI_ORIGIN.to_wire()
    path = f'/api/agent/sessions/{session["sessionId"]}/tasks'
    body = {"requestId": "same-message", "text": "hello HTTP"}
    status, receipt = request("POST", path, body)
    assert status == 202
    assert request("POST", path, body)[1]["taskId"] == receipt["taskId"]
    assert request("POST", path, {**body, "text": "different"})[0] == 409
    task_path = f'/api/agent/tasks/{receipt["taskId"]}'
    task = wait_for(
        lambda: (
            (value if value["status"] in {"succeeded", "failed"} else None)
            if (value := request("GET", task_path)[1])
            else None
        )
    )
    assert task["status"] == "succeeded"
    assert task["origin"] == UI_ORIGIN.to_wire()
    assert task["lifetime"] == "detached"
    assert task["limits"]["wallTimeMs"] is None
    assert task["limits"]["maxToolCalls"] == 20
    status, page = request("GET", task_path + "/events?afterSeq=0&limit=1000")
    assert status == 200
    assert any(event["type"] == "task.completed" for event in page["events"])
    assert (
        request("GET", task_path + f'/events?afterSeq={page["nextSeq"]}')[1]["events"]
        == []
    )
    assert (
        request("GET", "/api/agent/tasks?sessionId=" + session["sessionId"])[1][
            "tasks"
        ][0]["taskId"]
        == receipt["taskId"]
    )
    assert (
        request("POST", f'/api/agent/sessions/{session["sessionId"]}/close', {})[0]
        == 200
    )
    assert request("GET", "/api/agent/sessions")[1]["sessions"] == []
    assert "private-test-key" not in json.dumps(
        [session, task, page, runtime.snapshot()]
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"origin": {"kind": "plugin", "callerId": "attacker"}},
        {"limits": {"maxToolCalls": 999}},
        {"context": []},
        {"lifetime": "origin-bound"},
    ],
)
def test_task_identity_and_policy_cannot_be_supplied_by_http(live_agent, extra):
    _, request = live_agent
    session = request("POST", "/api/agent/sessions", {})[1]
    status, error = request(
        "POST",
        f'/api/agent/sessions/{session["sessionId"]}/tasks',
        {"requestId": "invalid", "text": "hello", **extra},
    )
    assert status == 400
    assert error["errorCode"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=1001", "limit=abc", "status=unknown"]
)
def test_bad_pagination_and_status_use_portable_errors(live_agent, query):
    _, request = live_agent
    status, error = request("GET", "/api/agent/tasks?" + query)
    assert status == 400
    assert error["agentError"]["code"] == "INVALID_REQUEST"


def test_runtime_stop_rejects_new_tasks(live_agent):
    runtime, request = live_agent
    assert request("POST", "/api/agent/runtime/stop", {})[0] == 200
    assert runtime.snapshot()["status"] == "stopped"
    assert request("POST", "/api/agent/sessions", {})[0] == 503
