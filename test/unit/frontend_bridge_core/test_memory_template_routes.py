from __future__ import annotations

from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Router
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
        ("POST", "/api/memory/asset-search"),
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
