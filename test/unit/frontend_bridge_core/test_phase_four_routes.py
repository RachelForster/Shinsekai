from __future__ import annotations

import threading
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes import transfer_routes, uploads as upload_module
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.router import BodyKind
from frontend_bridge_core.routes.transfer_routes import TRANSFER_ROUTES
from frontend_bridge_core.routes.uploads import UploadedFiles, read_uploaded_files


def _uploaded_files(tmp_path: Path, filename: str = "payload.zip") -> UploadedFiles:
    root = tmp_path / "upload"
    root.mkdir()
    path = root / filename
    path.write_bytes(b"payload")
    return UploadedFiles(root=root, paths=(path,))


def _handler(state: object, path: str) -> FrontendBridgeHandler:
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = path
    handler._require_authorized_write = lambda _path: None
    handler._log_request_exception = lambda _error: None
    return handler


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


def test_multipart_reader_stages_files_and_cleans_them() -> None:
    boundary = "shinsekai-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="demo.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    uploaded = read_uploaded_files(
        f"multipart/form-data; boundary={boundary}",
        str(len(body)),
        BytesIO(body),
    )
    root = uploaded.root

    assert uploaded.paths[0].name == "demo.txt"
    assert uploaded.paths[0].read_text() == "hello"
    uploaded.cleanup()
    assert not root.exists()


def test_multipart_reader_cleans_temp_directory_when_no_files_are_valid(
    tmp_path,
    monkeypatch,
) -> None:
    upload_root = tmp_path / "invalid-upload"
    upload_root.mkdir()
    monkeypatch.setattr(
        upload_module.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(upload_root),
    )
    boundary = "invalid-upload-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="other"\r\n\r\n'
        "ignored\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    with pytest.raises(ValueError, match="no files uploaded"):
        read_uploaded_files(
            f"multipart/form-data; boundary={boundary}",
            str(len(body)),
            BytesIO(body),
        )

    assert not upload_root.exists()


def test_uploaded_files_cleanup_ownership_can_be_transferred(tmp_path) -> None:
    uploaded = _uploaded_files(tmp_path)
    cleanup = uploaded.transfer_cleanup()

    uploaded.cleanup()
    assert uploaded.root.exists()

    cleanup()
    assert not uploaded.root.exists()


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
    handler = _handler(state, "/api/effects/import-upload")
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


def test_sync_upload_cleanup_runs_when_route_handler_fails(
    tmp_path,
    monkeypatch,
) -> None:
    uploaded = _uploaded_files(tmp_path, "theme.zip")
    failure = ValueError("invalid theme")
    monkeypatch.setattr(
        transfer_routes,
        "install_theme_from_zip",
        lambda _state, _path: (_ for _ in ()).throw(failure),
    )
    handler = _handler(object(), "/api/chat/themes/upload")
    handler._read_upload_files = lambda: uploaded
    errors: list[Exception] = []
    handler._send_exception_json = errors.append

    handler.do_POST()

    assert errors == [failure]
    assert not uploaded.root.exists()


def test_async_upload_cleanup_is_transferred_to_task_transport(
    tmp_path,
    monkeypatch,
) -> None:
    uploaded = _uploaded_files(tmp_path, "memory.json")
    state = object()
    worker_calls: list[tuple[object, str, str, tuple[Path, ...], Path]] = []
    monkeypatch.setattr(
        transfer_routes,
        "_run_character_memory_import",
        lambda request_state, task_id, name, paths, *, source_root: (
            worker_calls.append((request_state, task_id, name, paths, source_root))
            or {"ok": True}
        ),
    )
    handler = _handler(
        state,
        "/api/characters/memories/import-upload?name=Mika%20A",
    )
    handler._read_upload_files = lambda: uploaded
    enqueued: list[dict] = []
    handler._enqueue_background_task = lambda **kwargs: enqueued.append(kwargs)

    handler.do_POST()

    assert len(enqueued) == 1
    assert uploaded.root.exists()
    assert enqueued[0]["worker"]("task-1") == {"ok": True}
    assert worker_calls == [(state, "task-1", "Mika A", uploaded.paths, uploaded.root)]

    enqueued[0]["cleanup"]()
    assert not uploaded.root.exists()


def test_task_transport_cleans_transferred_uploads_after_worker(tmp_path) -> None:
    uploaded = _uploaded_files(tmp_path)
    cleanup_finished = threading.Event()
    cleanup = uploaded.transfer_cleanup()
    saw_upload: list[bool] = []
    state = SimpleNamespace(task_lock=threading.Lock(), tasks={})
    handler = _handler(state, "/api/test")
    handler._send_json = lambda _payload, _status=HTTPStatus.OK: None

    def cleanup_and_signal() -> None:
        cleanup()
        cleanup_finished.set()

    handler._enqueue_background_task(
        kind="test",
        title="Test",
        message="Queued",
        worker=lambda _task_id: saw_upload.append(uploaded.root.exists()),
        cleanup=cleanup_and_signal,
    )

    assert cleanup_finished.wait(timeout=2)
    assert saw_upload == [True]
    assert not uploaded.root.exists()


def test_task_transport_cleans_uploads_when_thread_start_fails(
    tmp_path,
    monkeypatch,
) -> None:
    uploaded = _uploaded_files(tmp_path)
    cleanup = uploaded.transfer_cleanup()
    state = SimpleNamespace(task_lock=threading.Lock(), tasks={})
    handler = _handler(state, "/api/test")

    class BrokenThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(
        "frontend_bridge_core.routes.api.threading.Thread",
        BrokenThread,
    )

    with pytest.raises(RuntimeError, match="thread start failed"):
        handler._enqueue_background_task(
            kind="test",
            title="Test",
            message="Queued",
            worker=lambda _task_id: None,
            cleanup=cleanup,
        )

    assert not uploaded.root.exists()
