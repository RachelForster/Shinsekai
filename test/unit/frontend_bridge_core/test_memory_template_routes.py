from __future__ import annotations

from types import SimpleNamespace

from ai.llm.formats import (
    XmlTagsStreamParser,
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
)
from core.messaging.formats.registry import _reset_for_tests
from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Router
from frontend_bridge_core.routes.template_routes import TEMPLATE_ROUTES
from sdk.adapters.dialog_format import DialogFormatContribution, DialogOutputFormat


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
        ("POST", "/api/characters/memories/awaken"),
        ("POST", "/api/characters/memories/delete"),
        ("POST", "/api/characters/memories/delete-batch"),
        ("POST", "/api/characters/memories/export"),
        ("POST", "/api/characters/memories/list"),
        ("POST", "/api/characters/memories/pin"),
        ("POST", "/api/characters/memories/status"),
        ("POST", "/api/memory/awaken"),
        ("POST", "/api/memory/forget"),
        ("POST", "/api/memory/list"),
        ("POST", "/api/memory/pin"),
        ("POST", "/api/memory/recall"),
        ("POST", "/api/memory/remember"),
        ("POST", "/api/memory/rollback"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/status"),
        ("POST", "/api/memory/asset-index"),
        ("POST", "/api/memory/asset-search"),
    }


def test_template_route_contracts_remain_stable() -> None:
    assert _contracts(TEMPLATE_ROUTES) == {
        ("GET", "/api/templates"),
        ("GET", "/api/templates/dialog-formats"),
        ("GET", "/api/templates/presets"),
        ("GET", "/api/templates/session"),
        ("POST", "/api/templates"),
        ("POST", "/api/templates/generate"),
        ("POST", "/api/templates/presets"),
        ("POST", "/api/templates/session"),
        ("PUT", "/api/templates"),
        ("PUT", "/api/templates/presets"),
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


class _RoutePluginFormat(DialogOutputFormat):
    format_id = "route_custom_v1"
    label = "Route Custom"

    def create_stream_parser(self) -> XmlTagsStreamParser:
        return XmlTagsStreamParser()

    def parse_complete(self, raw: str):
        return []

    def validate(self, raw: str) -> bool:
        return True


def test_dialog_formats_endpoint_returns_bare_array() -> None:
    _reset_for_tests()
    configure_builtin_dialog_formats()
    configure_registered_dialog_formats(
        [
            DialogFormatContribution(
                format_id="route_custom_v1",
                factory=_RoutePluginFormat,
                label="Route Custom",
                plugin_id="route-plugin",
            )
        ]
    )
    try:
        router = Router(list(TEMPLATE_ROUTES))
        request = _request(router, object(), "GET", "/api/templates/dialog-formats")
        matched = router.match(request.method, request.path)
        assert matched is not None

        response = matched.route.handler(request)

        assert isinstance(response, JsonResponse)
        assert isinstance(response.data, list)
        assert [row["id"] for row in response.data[:4]] == [
            "xml_v1",
            "renpy_v1",
            "json_v1",
            "route_custom_v1",
        ]
        by_id = {row["id"]: row for row in response.data}
        assert by_id["xml_v1"]["builtin"] is True
        assert by_id["renpy_v1"]["builtin"] is True
        assert by_id["json_v1"]["builtin"] is True
        assert by_id["route_custom_v1"]["builtin"] is False

        en_state = SimpleNamespace(
            config_manager=SimpleNamespace(
                config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en"))
            )
        )
        en_req = _request(router, en_state, "GET", "/api/templates/dialog-formats")
        en_resp = matched.route.handler(en_req)
        assert isinstance(en_resp, JsonResponse)
        en_by_id = {row["id"]: row for row in en_resp.data}
        assert "transitions & motions" in en_by_id["xml_v1"]["label"]
        assert "transitions & motions" in en_by_id["renpy_v1"]["label"]
        assert "classic compatible" in en_by_id["json_v1"]["label"]
    finally:
        _reset_for_tests()
        configure_builtin_dialog_formats()


def test_character_memory_delete_batch_forwards_ids(monkeypatch) -> None:
    received: list[tuple[str, list[str], dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.memory_routes._delete_character_memories",
        lambda name, ids, **extra: (
            received.append((name, ids, extra)) or {"agentId": name, "count": 0, "memories": []}
        ),
    )
    router = Router(list(MEMORY_ROUTES))
    request = _request(
        router,
        object(),
        "POST",
        "/api/characters/memories/delete-batch",
        {"name": "Alice", "memoryIds": ["m1", " ", "m2"], "sessionId": "s1"},
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, JsonResponse)
    assert received == [("Alice", ["m1", "m2"], {"session_id": "s1"})]


def test_character_memory_delete_batch_rejects_invalid_ids() -> None:
    import pytest

    router = Router(list(MEMORY_ROUTES))
    for body in ({"name": "Alice", "memoryIds": "m1"}, {"name": "Alice", "memoryIds": []}):
        request = _request(router, object(), "POST", "/api/characters/memories/delete-batch", body)
        matched = router.match(request.method, request.path)
        assert matched is not None
        with pytest.raises(ValueError):
            matched.route.handler(request)


def test_character_memory_list_forwards_window(monkeypatch) -> None:
    received: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.memory_routes._list_character_memories",
        lambda name, **extra: received.append((name, extra)) or {"memories": []},
    )
    router = Router(list(MEMORY_ROUTES))
    for body in (
        {"name": "Alice"},
        {"name": "Alice", "offset": 200, "limit": 200},
        {"name": "Alice", "offset": 0, "limit": 5000, "sessionId": "s1"},
    ):
        request = _request(router, object(), "POST", "/api/characters/memories/list", body)
        matched = router.match(request.method, request.path)
        assert matched is not None
        matched.route.handler(request)

    assert received == [
        ("Alice", {}),
        ("Alice", {"limit": 200, "offset": 200}),
        ("Alice", {"limit": 1000, "session_id": "s1"}),
    ]


def test_character_memory_export_forwards_selection_and_labels(monkeypatch) -> None:
    received: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.memory_routes._export_character_memories",
        lambda name, **extra: received.append((name, extra)) or {"text": "x", "count": 1},
    )
    router = Router(list(MEMORY_ROUTES))
    request = _request(
        router,
        object(),
        "POST",
        "/api/characters/memories/export",
        {"name": "Alice", "memoryIds": ["m1", ""], "labels": {"header": "H"}},
    )
    matched = router.match(request.method, request.path)
    assert matched is not None

    response = matched.route.handler(request)

    assert isinstance(response, JsonResponse)
    assert response.data == {"text": "x", "count": 1}
    assert received == [
        ("Alice", {"session_id": "", "memory_ids": ["m1"], "labels": {"header": "H"}}),
    ]
