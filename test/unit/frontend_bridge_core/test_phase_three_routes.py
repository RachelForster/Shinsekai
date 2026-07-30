from __future__ import annotations

import threading
from http import HTTPStatus
from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.operation_routes import OPERATION_ROUTES
from frontend_bridge_core.routes.plugin_routes import PLUGIN_ROUTES
from frontend_bridge_core.routes.router import (
    ApiRequest,
    JsonResponse,
    Router,
    TaskResponse,
)
from frontend_bridge_core.routes.template_routes import TEMPLATE_ROUTES


def _contracts(routes) -> set[tuple[str, str]]:
    return {(method, route.pattern) for route in routes for method in route.methods}


def _request(
    router: Router,
    state,
    method: str,
    path: str,
    body: dict | None = None,
) -> ApiRequest:
    matched = router.match(method, path)
    assert matched is not None
    return ApiRequest(
        state=state,
        method=method,
        path=path,
        query={},
        params=matched.params,
        body=body or {},
    )


def test_memory_route_contracts_remain_stable() -> None:
    assert _contracts(MEMORY_ROUTES) == {
        ("POST", "/api/characters/memories/add"),
        ("POST", "/api/characters/memories/delete"),
        ("POST", "/api/characters/memories/list"),
        ("POST", "/api/characters/memories/status"),
        ("POST", "/api/memory/forget"),
        ("POST", "/api/memory/list"),
        ("POST", "/api/memory/remember"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/status"),
    }


def test_template_route_contracts_remain_stable() -> None:
    assert _contracts(TEMPLATE_ROUTES) == {
        ("GET", "/api/templates"),
        ("GET", "/api/templates/session"),
        ("POST", "/api/templates"),
        ("POST", "/api/templates/generate"),
        ("POST", "/api/templates/session"),
        ("PUT", "/api/templates"),
    }


def test_operation_route_contracts_remain_stable() -> None:
    assert _contracts(OPERATION_ROUTES) == {
        ("GET", "/api/mcp/config"),
        ("POST", "/api/config/tts-bundle/download"),
        ("POST", "/api/mcp/config/apply"),
        ("POST", "/api/mcp/config/open"),
        ("POST", "/api/mcp/preview"),
        ("POST", "/api/model-assets/status"),
        ("POST", "/api/music-cover/config"),
        ("POST", "/api/music-cover/run"),
        ("POST", "/api/music-cover/search"),
        ("POST", "/api/runtime/install-missing-dependency"),
        ("POST", "/api/tools/sprite-prompts"),
        ("POST", "/api/tools/sprites/crop"),
        ("POST", "/api/tools/sprites/generate"),
        ("POST", "/api/tools/sprites/remove-background"),
    }


def test_plugin_route_contracts_remain_stable() -> None:
    assert _contracts(PLUGIN_ROUTES) == {
        ("DELETE", "/api/plugins/{plugin_id}"),
        ("GET", "/api/plugins"),
        ("GET", "/api/plugins/app-update/info"),
        ("GET", "/api/plugins/chat-ui-contributions"),
        ("GET", "/api/plugins/registry"),
        ("GET", "/api/plugins/status"),
        ("GET", "/api/plugins/{plugin_id}/ui"),
        ("POST", "/api/plugins/app-update/run"),
        ("POST", "/api/plugins/app-update/tags"),
        ("POST", "/api/plugins/install"),
        ("POST", "/api/plugins/publisher/copy-json"),
        ("POST", "/api/plugins/publisher/issue-url"),
        ("POST", "/api/plugins/publisher/scan"),
        ("POST", "/api/plugins/publisher/validate"),
        ("POST", "/api/plugins/repo-tags"),
        ("POST", "/api/plugins/{plugin_id}/chat-ui/{contribution_id}/run"),
        ("POST", "/api/plugins/{plugin_id}/enabled"),
        ("POST", "/api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}"),
        ("POST", "/api/plugins/{plugin_id}/ui/{page_id}/config"),
    }


def test_handler_dispatches_task_response_to_existing_task_transport(
    monkeypatch,
) -> None:
    state = SimpleNamespace()
    body = {"name": "Alice"}
    worker_calls: list[tuple[object, str, dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.operation_routes._generate_sprite_prompts",
        lambda request_state, task_id, payload: worker_calls.append(
            (request_state, task_id, payload)
        ),
    )
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/tools/sprite-prompts"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: body
    enqueued: list[dict] = []
    handler._enqueue_background_task = lambda **kwargs: enqueued.append(kwargs)

    handler._handle_write("POST")

    assert len(enqueued) == 1
    assert enqueued[0]["kind"] == "tools-prompts"
    assert enqueued[0]["title"] == "生成立绘提示词"
    enqueued[0]["worker"]("task-1")
    assert worker_calls == [(state, "task-1", body)]


def test_plugin_action_route_decodes_parameters_and_forwards_body(
    monkeypatch,
) -> None:
    body = {"values": {"enabled": True}}
    received: list[tuple[str, str, str, dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes._run_plugin_ui_action",
        lambda plugin_id, page_id, action_id, payload: (
            received.append((plugin_id, page_id, action_id, payload)) or {"ok": True}
        ),
    )
    router = Router(list(PLUGIN_ROUTES))
    path = "/api/plugins/demo%2Fplugin/ui/settings%20page/" "actions/reload%20config"
    request = _request(router, object(), "POST", path, body)
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, JsonResponse)
    assert response.data == {"ok": True}
    assert received == [("demo/plugin", "settings page", "reload config", body)]


def test_plugin_install_returns_existing_running_task() -> None:
    running = {
        "id": "task-1",
        "kind": "plugin-install",
        "source": "demo.plugin",
        "status": "running",
    }
    state = SimpleNamespace(
        task_lock=threading.Lock(),
        tasks={"task-1": running},
    )
    router = Router(list(PLUGIN_ROUTES))
    request = _request(
        router,
        state,
        "POST",
        "/api/plugins/install",
        {"id": "demo.plugin"},
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, JsonResponse)
    assert response.status is HTTPStatus.ACCEPTED
    assert response.data == running


def test_operation_task_response_preserves_task_metadata() -> None:
    router = Router(list(OPERATION_ROUTES))
    request = _request(
        router,
        object(),
        "POST",
        "/api/runtime/install-missing-dependency",
        {"moduleName": "demo_dependency"},
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, TaskResponse)
    assert response.kind == "runtime-dependency-install"
    assert response.task_updates == {
        "source": "demo_dependency",
        "phase": "pip",
        "progress": 0,
    }


def test_memory_search_preserves_legacy_field_aliases(monkeypatch) -> None:
    received: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.memory_routes._memory_tool_search",
        lambda query, character, limit: (
            received.append((query, character, limit)) or []
        ),
    )
    router = Router(list(MEMORY_ROUTES))
    request = _request(
        router,
        object(),
        "POST",
        "/api/memory/search",
        {
            "query": "hello",
            "character_name": "Alice",
            "limit": 3,
        },
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, JsonResponse)
    assert response.data == []
    assert received == [("hello", "Alice", 3)]


@pytest.mark.parametrize("body", [{}, {"moduleName": "  "}])
def test_runtime_dependency_route_preserves_required_field_validation(
    body: dict,
) -> None:
    router = Router(list(OPERATION_ROUTES))
    request = _request(
        router,
        object(),
        "POST",
        "/api/runtime/install-missing-dependency",
        body,
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    with pytest.raises(ValueError, match="moduleName is required"):
        matched.route.handler(request)
