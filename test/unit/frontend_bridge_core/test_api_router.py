from __future__ import annotations

import inspect
import json
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from application.runtime.state import BridgeState
from application.runtime.tasks import _create_task, _get_task
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    Router,
)
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES


def _state() -> BridgeState:
    return BridgeState(
        background_manager=None,
        character_manager=None,
        config_manager=None,
        template_generator=None,
    )


def _response(_request: ApiRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


def test_router_matches_fixed_and_decoded_dynamic_paths() -> None:
    router = Router(
        [
            Route(
                methods=frozenset({"get"}),
                pattern="/api/health",
                handler=_response,
                body_kind=BodyKind.NONE,
            ),
            Route(
                methods=frozenset({"GET"}),
                pattern="/api/tasks/{task_id}",
                handler=_response,
                body_kind=BodyKind.NONE,
            ),
        ]
    )

    fixed = router.match("GET", "/api/health")
    dynamic = router.match("get", "/api/tasks/task%20with%20spaces")

    assert fixed is not None
    assert fixed.params == {}
    assert dynamic is not None
    assert dynamic.params == {"task_id": "task with spaces"}
    assert router.match("POST", "/api/health") is None
    assert router.match("GET", "/api/tasks/one/more") is None


def test_router_rejects_duplicate_contracts_and_invalid_patterns() -> None:
    first = Route(
        methods=frozenset({"GET"}),
        pattern="/api/health",
        handler=_response,
    )
    duplicate = Route(
        methods=frozenset({"get"}),
        pattern="/api/health",
        handler=_response,
    )

    with pytest.raises(ValueError, match="duplicate route shape GET /api/health"):
        Router([first, duplicate])

    with pytest.raises(ValueError, match="duplicate route shape GET"):
        Router(
            [
                Route(
                    methods=frozenset({"GET"}),
                    pattern="/api/tasks/{task_id}",
                    handler=_response,
                ),
                Route(
                    methods=frozenset({"GET"}),
                    pattern="/api/tasks/{id}",
                    handler=_response,
                ),
            ]
        )

    with pytest.raises(ValueError, match="must start"):
        Route(
            methods=frozenset({"GET"}),
            pattern="api/health",
            handler=_response,
        )

    with pytest.raises(ValueError, match="unsupported route methods"):
        Route(
            methods=frozenset({"PATCH"}),
            pattern="/api/health",
            handler=_response,
        )


def test_api_handler_contains_no_feature_route_literals() -> None:
    from frontend_bridge_core.routes import api

    assert '"/api/' not in inspect.getsource(api)


def test_router_prefers_static_path_over_dynamic_path() -> None:
    dynamic = Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/themes/{theme_id}",
        handler=_response,
        name="themes.get",
    )
    static = Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/themes/active",
        handler=_response,
        name="themes.active",
    )

    matched = Router([dynamic, static]).match("GET", "/api/chat/themes/active")

    assert matched is not None
    assert matched.route.name == "themes.active"
    assert matched.params == {}


def test_registered_system_route_contracts_remain_stable() -> None:
    expected = {
        ("GET", "/api/config"),
        ("GET", "/api/config/network-proxy/detect"),
        ("GET", "/api/config/tts-bundle/recommendation"),
        ("GET", "/api/health"),
        ("GET", "/api/tasks/{task_id}"),
        ("POST", "/api/config/api"),
        ("POST", "/api/config/llm-connection-test"),
        ("POST", "/api/config/llm-models"),
        ("POST", "/api/config/system"),
        ("POST", "/api/tasks/{task_id}/cancel"),
        ("PUT", "/api/config/api"),
        ("PUT", "/api/config/system"),
    }

    actual = {
        (method, route.pattern) for route in SYSTEM_ROUTES for method in route.methods
    }

    assert actual == expected


def test_registered_story_route_contracts_match_main() -> None:
    assert {
        (method, route.pattern) for route in STORY_ROUTES for method in route.methods
    } == {
        ("GET", "/api/story/generation/{generation_task_id}"),
        ("POST", "/api/story/generation/start"),
        ("POST", "/api/story/generation/{generation_task_id}/cancel"),
        ("POST", "/api/story/generation/{generation_task_id}/regenerate"),
        ("POST", "/api/story/generation/{generation_task_id}/resume"),
        ("POST", "/api/story/start"),
    }


def test_task_routes_preserve_get_and_cancel_behavior() -> None:
    state = _state()
    task = _create_task(state, kind="download", title="Download")
    router = Router(list(SYSTEM_ROUTES))

    get_match = router.match("GET", f"/api/tasks/{task['id']}")
    assert get_match is not None
    get_response = get_match.route.handler(
        ApiRequest(
            state=state,
            method="GET",
            path=f"/api/tasks/{task['id']}",
            query={},
            params=get_match.params,
            body={},
        )
    )

    cancel_match = router.match("POST", f"/api/tasks/{task['id']}/cancel")
    assert cancel_match is not None
    cancel_response = cancel_match.route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path=f"/api/tasks/{task['id']}/cancel",
            query={},
            params=cancel_match.params,
            body={},
        )
    )

    assert get_response.data["id"] == task["id"]
    assert cancel_response.data["cancelRequested"] is True
    assert _get_task(state, task["id"])["phase"] == "cancelling"


def test_handler_dispatches_registered_json_route_without_changing_contract(
    monkeypatch,
) -> None:
    state = _state()
    payload = {"llm_provider": "OpenAI"}
    saved = SimpleNamespace(llm_provider="OpenAI")
    monkeypatch.setattr(
        "frontend_bridge_core.routes.system_routes._save_api_config",
        lambda received_state, received_payload: (
            saved if received_state is state and received_payload == payload else None
        ),
    )
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/config/api"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: payload
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler._handle_write("PUT")

    assert sent == [(saved, HTTPStatus.OK)]


def test_handler_get_uses_registered_health_path() -> None:
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=_state())
    handler.path = "/api/health"
    handler._require_authorized_read = lambda _path: None
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler.do_GET()

    assert sent[0][1] is HTTPStatus.OK
    assert sent[0][0]["ok"] is True
    assert sent[0][0]["plugins"]["status"] == "idle"


def test_registered_routes_keep_live_http_paths_and_methods() -> None:
    state = _state()
    task = _create_task(state, kind="download", title="Download")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urlopen(f"{base_url}/api/health", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urlopen(f"{base_url}/api/tasks/{task['id']}", timeout=5) as response:
            stored = json.loads(response.read().decode("utf-8"))
        cancel_request = Request(
            f"{base_url}/api/tasks/{task['id']}/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(cancel_request, timeout=5) as response:
            cancelled = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert health["ok"] is True
    assert stored["id"] == task["id"]
    assert cancelled["cancelRequested"] is True


def test_llm_route_preserves_bad_request_response(monkeypatch) -> None:
    def fail(_payload):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "frontend_bridge_core.routes.system_routes._fetch_llm_models",
        fail,
    )
    route = next(
        route for route in SYSTEM_ROUTES if route.pattern == "/api/config/llm-models"
    )

    response = route.handler(
        ApiRequest(
            state=_state(),
            method="POST",
            path=route.pattern,
            query={},
            params={},
            body={"provider": "OpenAI"},
        )
    )

    assert response.status is HTTPStatus.BAD_REQUEST
    assert response.data["type"] == "RuntimeError"
    assert response.data["error"]
