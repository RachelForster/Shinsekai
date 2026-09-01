from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest

from application.characters import CharacterOperation
from application.effects import EffectOperation
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.background_routes import BACKGROUND_ROUTES
from frontend_bridge_core.routes.character_routes import CHARACTER_ROUTES
from frontend_bridge_core.routes.effect_routes import EFFECT_ROUTES
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Router,
)

RESOURCE_ROUTES = (
    *CHARACTER_ROUTES,
    *BACKGROUND_ROUTES,
    *EFFECT_ROUTES,
)


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


def test_character_route_contracts_remain_stable() -> None:
    assert _contracts(CHARACTER_ROUTES) == {
        ("GET", "/api/characters"),
        ("POST", "/api/characters"),
        ("POST", "/api/characters/ai-setting"),
        ("POST", "/api/characters/emotion-tags"),
        ("POST", "/api/characters/sprite-scale"),
        ("POST", "/api/characters/sprite-voice/delete"),
        ("POST", "/api/characters/sprite-voice/text"),
        ("POST", "/api/characters/sprite-voice/upload"),
        ("POST", "/api/characters/sprite-voice/voice-type"),
        ("POST", "/api/characters/sprites/auto-label"),
        ("POST", "/api/characters/sprites/delete"),
        ("POST", "/api/characters/sprites/delete-all"),
        ("POST", "/api/characters/sprites/upload"),
        ("POST", "/api/characters/translate"),
        ("PUT", "/api/characters"),
        ("DELETE", "/api/characters/{name}"),
    }


def test_background_route_contracts_remain_stable() -> None:
    assert _contracts(BACKGROUND_ROUTES) == {
        ("GET", "/api/backgrounds"),
        ("POST", "/api/backgrounds"),
        ("POST", "/api/backgrounds/bgm-tags"),
        ("POST", "/api/backgrounds/bgm/delete"),
        ("POST", "/api/backgrounds/bgm/delete-all"),
        ("POST", "/api/backgrounds/bgm/upload"),
        ("POST", "/api/backgrounds/images/auto-label"),
        ("POST", "/api/backgrounds/images/delete"),
        ("POST", "/api/backgrounds/images/delete-all"),
        ("POST", "/api/backgrounds/images/upload"),
        ("POST", "/api/backgrounds/tags"),
        ("POST", "/api/backgrounds/translate"),
        ("PUT", "/api/backgrounds"),
        ("DELETE", "/api/backgrounds/{name}"),
    }


def test_effect_route_contracts_remain_stable() -> None:
    assert _contracts(EFFECT_ROUTES) == {
        ("GET", "/api/effects"),
        ("POST", "/api/effects"),
        ("POST", "/api/effects/audio-tags"),
        ("POST", "/api/effects/audio/delete"),
        ("POST", "/api/effects/audio/delete-all"),
        ("POST", "/api/effects/audio/upload"),
        ("PUT", "/api/effects"),
        ("DELETE", "/api/effects/{name}"),
    }


def test_resource_list_routes_return_existing_config_collections() -> None:
    characters = [SimpleNamespace(name="A")]
    backgrounds = [SimpleNamespace(name="B")]
    effects = [SimpleNamespace(name="C")]
    state = SimpleNamespace(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                characters=characters,
                background_list=backgrounds,
                effect_list=effects,
            )
        )
    )
    router = Router(list(RESOURCE_ROUTES))

    responses = [
        router.match("GET", path).route.handler(  # type: ignore[union-attr]
            _request(router, state, "GET", path)
        )
        for path in ("/api/characters", "/api/backgrounds", "/api/effects")
    ]

    assert [response.data for response in responses] == [
        characters,
        backgrounds,
        effects,
    ]


def test_character_json_route_forwards_the_unchanged_body(monkeypatch) -> None:
    state = object()
    body = {"name": "Alice", "avatar": "alice.png"}
    saved = {"name": "Alice"}
    received: list[tuple[object, CharacterOperation, dict]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.character_routes._execute_character_request",
        lambda request_state, operation, request_body: (
            received.append((request_state, operation, request_body)) or saved
        ),
    )
    router = Router(list(CHARACTER_ROUTES))
    request = _request(router, state, "PUT", "/api/characters", body)

    matched = router.match(request.method, request.path)
    assert matched is not None
    response = matched.route.handler(request)

    assert response.data == saved
    assert received == [(state, CharacterOperation.SAVE, body)]


def test_handler_dispatches_registered_resource_route() -> None:
    characters = [SimpleNamespace(name="Alice")]
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(
        state=SimpleNamespace(
            config_manager=SimpleNamespace(
                config=SimpleNamespace(characters=characters)
            )
        )
    )
    handler.path = "/api/characters"
    handler._require_authorized_read = lambda _path: None
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler.do_GET()

    assert sent == [(characters, HTTPStatus.OK)]


def test_handler_delete_resource_route_does_not_read_a_json_body(monkeypatch) -> None:
    state = SimpleNamespace()
    deleted: list[tuple[object, EffectOperation, str]] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.effect_routes._execute_effect",
        lambda request, operation, *, name="": (
            deleted.append((request.state, operation, name))
            or JsonResponse({"message": "deleted"})
        ),
    )
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/effects/Thunder%20Clap"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: pytest.fail("DELETE route must not read a JSON body")
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler._handle_write("DELETE")

    assert deleted == [(state, EffectOperation.DELETE, "Thunder Clap")]
    assert sent == [({"message": "deleted"}, HTTPStatus.OK)]


def test_dynamic_delete_routes_decode_names_and_do_not_require_bodies(
    monkeypatch,
) -> None:
    deleted: list[tuple[str, str]] = []
    state = SimpleNamespace(
        character_manager=SimpleNamespace(
            delete_character=lambda name: (
                deleted.append(("character", name)) or ("deleted", ["Remaining"])
            )
        ),
        background_manager=SimpleNamespace(
            delete_background=lambda name: (
                deleted.append(("background", name)) or ("deleted", ["Remaining"])
            )
        ),
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.effect_routes._execute_effect",
        lambda request, operation, *, name="": (
            deleted.append(("effect", name)) or JsonResponse({"message": "deleted"})
        ),
    )
    router = Router(list(RESOURCE_ROUTES))

    for path in (
        "/api/characters/Alice%20A",
        "/api/backgrounds/Room%201",
        "/api/effects/Thunder%20Clap",
    ):
        request = _request(router, state, "DELETE", path)
        matched = router.match("DELETE", path)
        assert matched is not None
        assert matched.route.body_kind is BodyKind.NONE
        matched.route.handler(request)

    assert deleted == [
        ("character", "Alice A"),
        ("background", "Room 1"),
        ("effect", "Thunder Clap"),
    ]


@pytest.mark.parametrize(
    "message",
    [
        "找不到背景",
        "请选择背景",
        "删除失败",
    ],
)
def test_background_delete_preserves_error_detection(message: str) -> None:
    state = SimpleNamespace(
        background_manager=SimpleNamespace(
            delete_background=lambda _name: (message, [])
        )
    )
    router = Router(list(BACKGROUND_ROUTES))
    request = _request(router, state, "DELETE", "/api/backgrounds/Room")
    matched = router.match(request.method, request.path)
    assert matched is not None

    with pytest.raises(RuntimeError, match=message):
        matched.route.handler(request)
