from __future__ import annotations

import threading
from http import HTTPStatus
from types import SimpleNamespace

from frontend_bridge_core.routes.plugin_routes import PLUGIN_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Router


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
