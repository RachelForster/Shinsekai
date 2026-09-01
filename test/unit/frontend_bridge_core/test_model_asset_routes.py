from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

from frontend_bridge_core.routes import model_asset_routes
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.model_asset_routes import MODEL_ASSET_ROUTES


def test_model_asset_route_contracts_remain_stable() -> None:
    assert {
        (method, route.pattern)
        for route in MODEL_ASSET_ROUTES
        for method in route.methods
    } == {
        ("POST", "/api/model-assets/download"),
        ("POST", "/api/model-assets/status"),
    }


def test_download_route_reuses_an_existing_task(monkeypatch) -> None:
    state = object()
    request_model = object()
    spec = SimpleNamespace(
        asset_id="demo.asset",
        task_key="demo.asset:default",
        title="Demo asset",
        variant="default",
    )
    existing = {"id": "task-existing", "status": "running"}
    monkeypatch.setattr(
        model_asset_routes,
        "parse_model_asset_request",
        lambda _body: request_model,
    )
    monkeypatch.setattr(
        model_asset_routes,
        "configured_asr_model",
        lambda _state: "default",
    )
    monkeypatch.setattr(
        model_asset_routes,
        "resolve_model_asset",
        lambda _request, *, configured_asr_model: spec,
    )
    monkeypatch.setattr(
        model_asset_routes,
        "find_running_model_download",
        lambda _state, _task_key: existing,
    )

    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/model-assets/download"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: {"assetId": "demo.asset"}
    handler._enqueue_background_task = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("an existing download must not enqueue another task")
    )
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda data, status=HTTPStatus.OK: sent.append((data, status))

    handler.do_POST()

    assert sent == [(existing, HTTPStatus.ACCEPTED)]
