from __future__ import annotations

from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.operation_routes import OPERATION_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, Router, TaskResponse


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


def test_operation_route_contracts_remain_stable() -> None:
    assert _contracts(OPERATION_ROUTES) == {
        ("GET", "/api/mcp/config"),
        ("POST", "/api/config/tts-bundle/download"),
        ("POST", "/api/mcp/config/apply"),
        ("POST", "/api/mcp/config/open"),
        ("POST", "/api/mcp/preview"),
        ("POST", "/api/music-cover/config"),
        ("POST", "/api/music-cover/run"),
        ("POST", "/api/music-cover/search"),
        ("POST", "/api/runtime/install-missing-dependency"),
        ("POST", "/api/tools/sprite-prompts"),
        ("POST", "/api/tools/sprites/crop"),
        ("POST", "/api/tools/sprites/generate"),
        ("POST", "/api/tools/sprites/remove-background"),
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
