from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

from frontend_bridge_core.routes.chat_routes import CHAT_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, Router


def _contracts() -> set[tuple[str, str]]:
    return {
        (method, route.pattern) for route in CHAT_ROUTES for method in route.methods
    }


def _request(
    router: Router,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    query: dict[str, list[str]] | None = None,
) -> tuple[ApiRequest, object]:
    matched = router.match(method, path)
    assert matched is not None
    return (
        ApiRequest(
            state=SimpleNamespace(),
            method=method,
            path=path,
            query=query or {},
            params=matched.params,
            body=body or {},
        ),
        matched.route,
    )


def test_chat_route_contracts_remain_stable() -> None:
    assert _contracts() == {
        ("DELETE", "/api/chat/themes/{theme_id}"),
        ("GET", "/api/chat/history"),
        ("GET", "/api/chat/runtime-status"),
        ("GET", "/api/chat/snapshot"),
        ("GET", "/api/chat/theme"),
        ("GET", "/api/chat/themes"),
        ("GET", "/api/chat/themes/active"),
        ("GET", "/api/chat/themes/{theme_id}"),
        ("POST", "/api/chat/close"),
        ("POST", "/api/chat/command"),
        ("POST", "/api/chat/init"),
        ("POST", "/api/chat/launch"),
        ("POST", "/api/chat/resume-last"),
        ("POST", "/api/chat/themes/active"),
        ("POST", "/api/chat/themes/save"),
    }


def test_chat_init_preserves_accepted_status(monkeypatch) -> None:
    task = {"id": "chat-init-1", "status": "queued"}
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes.start_chat_initialization",
        lambda _state, _body: task,
    )
    router = Router(list(CHAT_ROUTES))
    request, route = _request(
        router,
        "POST",
        "/api/chat/init",
        body={"mode": "resume-last"},
    )

    response = route.handler(request)

    assert response.data == task
    assert response.status is HTTPStatus.ACCEPTED


def test_snapshot_preserves_renderer_query_parameter(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.chat_routes._chat_snapshot",
        lambda _state, *, renderer_id: calls.append(renderer_id)
        or {"rendererId": renderer_id},
    )
    router = Router(list(CHAT_ROUTES))
    request, route = _request(
        router,
        "GET",
        "/api/chat/snapshot",
        query={"rendererId": ["renderer-1"]},
    )

    response = route.handler(request)

    assert response.data == {"rendererId": "renderer-1"}
    assert calls == ["renderer-1"]
