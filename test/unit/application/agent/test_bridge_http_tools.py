from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from application.agent.runtime import AgentRuntime, UI_ORIGIN
from frontend_bridge_core.routes.api import _API_ROUTER
from frontend_bridge_core.routes.router import BodyKind
from frontend_bridge_core.transport.agent_http_tools import (
    READ_APIS,
    WRITE_APIS,
    BridgeHttpClient,
    BridgeReadInput,
    BridgeWriteInput,
    build_bridge_http_tools,
)
from sdk.agent import AgentHostToolCall, AgentTaskRequest
from test.unit.application.agent.test_runtime import ModelConfig, mock_setup, wait_for


@pytest.fixture
def bridge():
    requests = []
    reply = {"status": 200, "data": {"ok": True}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_api(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(
                (
                    self.command,
                    self.path,
                    self.headers["X-Shinsekai-Bridge-Token"],
                    json.loads(body) if body else None,
                )
            )
            if reply.get("disconnect"):
                self.close_connection = True
                return
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Location", "http://example.com/never-follow")
            self.end_headers()
            self.wfile.write(reply.get("raw", json.dumps(reply["data"]).encode()))

        do_GET = handle_api
        do_POST = handle_api

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, requests, reply
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def invoke(bridge, kind, arguments):
    server, _, _ = bridge
    tool = build_bridge_http_tools(*server.server_address, "private-bridge-token")[kind]
    return tool.execute(
        None,
        AgentHostToolCall(
            call_id="test-call", name=tool.definition.name, arguments=arguments
        ),
    )


def test_allowlist_matches_existing_json_http_routes():
    for api in (*READ_APIS.values(), *WRITE_APIS.values()):
        params = {
            name: "fixture" for name in ("plugin_id", "page_id", "action_id", "task_id")
        }
        match = _API_ROUTER.match(api.method, api.path.format(**params))
        assert match is not None, api
        assert match.route.body_kind != BodyKind.MULTIPART
        assert not api.path.startswith("/api/agent")


@pytest.mark.parametrize("model", [BridgeReadInput, BridgeWriteInput])
def test_model_cannot_choose_url_auth_or_unregistered_operations(model):
    for arguments in (
        {"operation": "http://example.com"},
        {"operation": "app.config", "url": "http://example.com"},
        {"operation": "plugins.install", "headers": {"Authorization": "injected"}},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(arguments)


def test_existing_http_response_is_redacted_without_losing_character_text(bridge):
    _, requests, reply = bridge
    reply["data"] = {
        "api_config": {
            "llm_api_key": {"provider": "provider-private-key"},
            "max_context_tokens": 128000,
        },
        "text": "人物设定与正文仍可读取。",
        "url": "/page?shinsekai_bridge_token=private-bridge-token",
        "echo": "provider-private-key",
        "nested": [{"APIKey": "another-private-key"}],
    }
    result = invoke(bridge, 0, {"operation": "app.config"})
    assert result.ok
    data = result.data["data"]
    assert data["api_config"]["max_context_tokens"] == 128000
    assert data["text"] == "人物设定与正文仍可读取。"
    wire = result.model_dump_json()
    assert "private-bridge-token" not in wire
    assert "provider-private-key" not in wire
    assert "another-private-key" not in wire
    assert requests == [("GET", "/api/config?view=agent", "private-bridge-token", None)]
    assert not result.effects


def test_path_parameters_are_encoded_and_post_read_keeps_original_body(bridge):
    _, requests, _ = bridge
    result = invoke(
        bridge,
        0,
        {"operation": "plugins.inspect", "params": {"plugin_id": "plugin/a?query=yes"}},
    )
    assert result.ok
    assert requests[0][1] == "/api/plugins/plugin%2Fa%3Fquery%3Dyes/ui"
    result = invoke(
        bridge, 0, {"operation": "logs.read", "body": {"path": "logs/run.jsonl"}}
    )
    assert result.ok
    assert requests[1] == (
        "POST",
        "/api/logs/read",
        "private-bridge-token",
        {"path": "logs/run.jsonl"},
    )


def test_character_name_is_encoded_as_one_fixed_query_parameter(bridge):
    result = invoke(
        bridge,
        0,
        {"operation": "characters.get", "params": {"name": "目标/角色 &?#+ 甲"}},
    )
    assert result.ok
    assert bridge[1][0][1] == (
        "/api/characters?name=%E7%9B%AE%E6%A0%87%2F%E8%A7%92%E8%89%B2"
        "+%26%3F%23%2B+%E7%94%B2"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "characters.list", "params": {"view": "full"}},
        {"operation": "characters.get"},
        {"operation": "characters.get", "params": {"name": ""}},
        {"operation": "characters.get", "params": {"name": "A", "view": "full"}},
        {"operation": "app.config", "params": {"view": "full"}},
        {"operation": "plugins.list", "body": {"view": "full"}},
        {"operation": "plugins.registry", "params": {"view": "full"}},
    ],
)
def test_missing_target_or_overriding_summary_does_not_send_request(bridge, arguments):
    result = invoke(bridge, 0, arguments)
    assert not result.ok
    assert result.error.code == "INVALID_REQUEST"
    assert not bridge[1]


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "plugins.configure", "params": {"plugin_id": "test"}},
        {"operation": "plugins.install", "params": {"path": "/api/agent/runtime/stop"}},
    ],
)
def test_invalid_route_parameters_do_not_send_or_apply_writes(bridge, arguments):
    result = invoke(bridge, 1, arguments)
    assert not result.ok
    assert result.error.code == "INVALID_REQUEST"
    assert result.effects[0].state == "not_applied"
    assert not bridge[1]


@pytest.mark.parametrize(
    "status,raw,code",
    [
        (403, None, "TOOL_DENIED"),
        (400, None, "INVALID_REQUEST"),
        (302, None, "INVALID_REQUEST"),
        (200, b"invalid-json", "PROTOCOL_MISMATCH"),
        (200, b'{"value": NaN}', "PROTOCOL_MISMATCH"),
        (200, b"x" * (BridgeHttpClient.MAX_RESPONSE_BYTES + 1), "LIMIT_EXCEEDED"),
    ],
    ids=["denied", "invalid", "redirect", "not-json", "nan", "oversized"],
)
def test_failed_writes_remain_unknown_and_are_never_retried(bridge, status, raw, code):
    _, requests, reply = bridge
    reply.update(status=status, data={"error": "failed private-bridge-token"})
    if raw is not None:
        reply["raw"] = raw
    result = invoke(
        bridge, 1, {"operation": "plugins.install", "body": {"source": "test"}}
    )
    assert not result.ok
    assert result.error.code == code
    assert result.effects[0].state == "unknown"
    assert "private-bridge-token" not in result.model_dump_json()
    assert len(requests) == 1


def test_lost_write_response_is_unknown_without_resubmitting(bridge):
    _, requests, reply = bridge
    reply["disconnect"] = True
    result = invoke(
        bridge, 1, {"operation": "plugins.install", "body": {"source": "fixture"}}
    )
    assert not result.ok
    assert result.error.code == "BACKEND_UNAVAILABLE"
    assert result.effects[0].state == "unknown"
    assert len(requests) == 1


def test_runtime_injects_tools_and_records_async_submission_once(bridge, tmp_path):
    server, requests, reply = bridge
    reply.update(status=202, data={"id": "bridge-job", "status": "queued"})
    tools = build_bridge_http_tools(*server.server_address, "private-bridge-token")
    config = ModelConfig()
    runtime = AgentRuntime(config, tmp_path, prepare=mock_setup, tools=tools)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "ready")
        session = runtime.create_session()
        call = {
            "callId": "install-once",
            "name": "shinsekai.bridge.write",
            "arguments": {
                "operation": "plugins.install",
                "body": {"source": "fixture.plugin"},
            },
        }
        with runtime.access(ready=True) as client:
            receipt = client.submit_task(
                AgentTaskRequest(
                    request_id="submit",
                    session_id=session.session_id,
                    origin=UI_ORIGIN,
                    input={"text": "安装插件"},
                    context=(
                        {
                            "kind": "text",
                            "source": "mock:plan",
                            "text": json.dumps({"tools": [call, call]}),
                        },
                    ),
                    lifetime="detached",
                )
            )
            task = wait_for(
                lambda: (
                    (value if value.status.is_terminal else None)
                    if (value := client.get_task(receipt.task_id))
                    else None
                )
            )
            assert task.status == "succeeded", task.error
            events = client.read_events(task.task_id).events
            result = next(
                event.payload.result
                for event in events
                if event.type == "tool.completed"
            )
            assert result.data["accepted"]
            assert result.data["taskId"] == "bridge-job"
            assert task.result.effects[0].state == "applied"
            assert "completion must be checked" in task.result.effects[0].description
        assert len(requests) == 1
        runtime._thread.join(3)
        config.model = "changed-model"
        runtime.start()
        wait_for(
            lambda: runtime.snapshot()["status"] == "ready"
            and not runtime.snapshot()["configurationChanged"]
        )
        assert set(runtime._service.tools) == {tool.definition.name for tool in tools}
    finally:
        runtime.close()
    assert b"private-bridge-token" not in (tmp_path / "agent.sqlite").read_bytes()
