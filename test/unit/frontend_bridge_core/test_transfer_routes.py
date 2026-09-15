from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.backgrounds import BackgroundExportResult
from application.characters import CharacterExportResult
from frontend_bridge_core.routes import transfer_routes
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.router import ApiRequest, BodyKind
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
    received: list[tuple[object, list[object], tuple[str, ...]]] = []
    monkeypatch.setattr(
        transfer_routes,
        "_import_effects",
        lambda request_state, paths, *, additional_file_roots=(): (
            received.append((request_state, paths, additional_file_roots))
            or [{"name": "Spark"}]
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

    assert received == [(state, list(uploaded.paths), (str(uploaded.root),))]
    assert sent == [([{"name": "Spark"}], HTTPStatus.OK)]
    assert not uploaded.root.exists()


EXPORT_CASES = (
    ("character", "_execute_character_request", "Mio.char", CharacterExportResult),
    ("background", "_execute_background_request", "Room.bg", BackgroundExportResult),
    ("effect", "_execute_effect", "Spark.ef", None),
)


@pytest.mark.parametrize("resource,executor,filename,result_type", EXPORT_CASES)
@pytest.mark.parametrize("open_folder", [True, False, None])
def test_export_opens_output_folder_only_when_requested_after_writing_package(
    tmp_path, monkeypatch, resource, executor, filename, result_type, open_folder
):
    project_root = tmp_path / "project"
    output = project_root / "output" / filename
    relative = f"output/{filename}"
    payload = {"path": relative, "downloadUrl": f"/api/download?path={relative}"}

    def export_package(*_args):
        output.parent.mkdir(parents=True)
        output.write_bytes(b"package")
        return result_type(path=relative) if result_type else payload

    opened = []

    def open_directory(folder):
        assert output.read_bytes() == b"package"
        opened.append(folder)

    monkeypatch.setattr(transfer_routes, executor, export_package)
    monkeypatch.setattr("tools.file_util.platform.system", lambda: "Windows")
    monkeypatch.setattr("tools.file_util.os.startfile", open_directory, raising=False)
    # Resolve against the selected project even if the bridge's cwd differs.
    monkeypatch.chdir(tmp_path)
    request = ApiRequest(
        state=SimpleNamespace(project_root_dir=str(project_root)),
        method="POST",
        path=f"/api/{resource}s/export",
        query={},
        params={},
        body={"name": output.stem, **({"openFolder": open_folder} if open_folder is not None else {})},
    )

    response = getattr(transfer_routes, f"_export_{resource}")(request)

    assert response.data == payload
    assert opened == ([output.parent.resolve()] if open_folder else [])


@pytest.mark.parametrize("resource,executor,filename,result_type", EXPORT_CASES)
def test_failed_export_does_not_open_output_folder(
    tmp_path, monkeypatch, resource, executor, filename, result_type
):
    def fail_export(*_args):
        raise RuntimeError("export failed")

    monkeypatch.setattr(transfer_routes, executor, fail_export)
    monkeypatch.setattr(
        "tools.file_util._open_export_folder",
        lambda _path: pytest.fail("failed export opened a folder"),
    )
    request = ApiRequest(
        state=SimpleNamespace(project_root_dir=str(tmp_path)),
        method="POST",
        path=f"/api/{resource}s/export",
        query={},
        params={},
        body={"name": Path(filename).stem, "openFolder": True},
    )

    with pytest.raises(RuntimeError, match="export failed"):
        getattr(transfer_routes, f"_export_{resource}")(request)


def test_folder_open_failure_preserves_successful_export_response(tmp_path, monkeypatch):
    def fail_open(_folder):
        raise OSError("file manager unavailable")

    monkeypatch.setattr("tools.file_util.platform.system", lambda: "Windows")
    monkeypatch.setattr("tools.file_util.os.startfile", fail_open, raising=False)
    request = ApiRequest(
        state=SimpleNamespace(project_root_dir=str(tmp_path)),
        method="POST",
        path="/api/characters/export",
        query={},
        params={},
        body={"name": "Mio", "openFolder": True},
    )
    payload = {"path": "output/Mio.char", "downloadUrl": "/api/download?path=output/Mio.char"}

    assert transfer_routes._export_response(request, payload).data == payload
