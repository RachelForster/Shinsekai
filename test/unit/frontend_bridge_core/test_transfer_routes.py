from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes import transfer_routes
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.router import BodyKind
from frontend_bridge_core.routes.transfer_routes import TRANSFER_ROUTES
from frontend_bridge_core.routes.uploads import UploadedFiles


def _uploaded_files(tmp_path: Path, filename: str = "payload.zip") -> UploadedFiles:
    root = tmp_path / "upload"
    root.mkdir()
    path = root / filename
    path.write_bytes(b"payload")
    return UploadedFiles(root=root, paths=(path,))


def test_transfer_route_contracts_and_body_kinds_remain_explicit() -> None:
    assert {
        (method, route.pattern) for route in TRANSFER_ROUTES for method in route.methods
    } == {
        ("POST", "/api/backgrounds/export"),
        ("POST", "/api/backgrounds/import"),
        ("POST", "/api/backgrounds/import-upload"),
        ("POST", "/api/characters/export"),
        ("POST", "/api/characters/import"),
        ("POST", "/api/characters/import-upload"),
        ("POST", "/api/characters/memories/import-preview-upload"),
        ("POST", "/api/characters/memories/import-upload"),
        ("POST", "/api/chat/attachments/upload"),
        ("POST", "/api/chat/themes/upload"),
        ("POST", "/api/effects/export"),
        ("POST", "/api/effects/import"),
        ("POST", "/api/effects/import-upload"),
        ("POST", "/api/logs/import-upload"),
    }
    assert {
        route.pattern
        for route in TRANSFER_ROUTES
        if route.body_kind is BodyKind.MULTIPART
    } == {
        "/api/backgrounds/import-upload",
        "/api/characters/import-upload",
        "/api/characters/memories/import-preview-upload",
        "/api/characters/memories/import-upload",
        "/api/chat/attachments/upload",
        "/api/chat/themes/upload",
        "/api/effects/import-upload",
        "/api/logs/import-upload",
    }


def test_effect_upload_uses_multipart_dispatch_and_cleans_after_response(
    tmp_path,
    monkeypatch,
) -> None:
    uploaded = _uploaded_files(tmp_path, "effect.ef")
    state = object()
    received: list[tuple[object, list[str]]] = []
    monkeypatch.setattr(
        transfer_routes,
        "_import_effects",
        lambda request_state, paths: (
            received.append((request_state, paths)) or [{"name": "Spark"}]
        ),
    )
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "/api/effects/import-upload"
    handler._require_authorized_write = lambda _path: None
    handler._log_request_exception = lambda _error: None
    handler._read_upload_files = lambda: uploaded
    handler._read_json = lambda: pytest.fail("multipart route read JSON")
    sent: list[tuple[object, HTTPStatus]] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append(
        (payload, status)
    )

    handler.do_POST()

    assert received == [(state, [str(uploaded.paths[0])])]
    assert sent == [([{"name": "Spark"}], HTTPStatus.OK)]
    assert not uploaded.root.exists()
