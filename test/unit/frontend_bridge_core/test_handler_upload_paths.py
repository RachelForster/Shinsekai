from io import BytesIO
from types import SimpleNamespace

import pytest

import frontend_bridge_core.routes.api as handler_module
from frontend_bridge_core.routes.api import (
    FrontendBridgeHandler,
    _MULTIPART_UPLOAD_PATHS,
)


def test_multipart_upload_routes_include_every_file_import_endpoint():
    assert _MULTIPART_UPLOAD_PATHS == {
        "/api/backgrounds/import-upload",
        "/api/characters/import-upload",
        "/api/characters/memories/import-preview-upload",
        "/api/characters/memories/import-upload",
        "/api/effects/import-upload",
        "/api/logs/import-upload",
        "/api/chat/attachments/upload",
        "/api/chat/themes/upload",
    }


def test_upload_staging_is_removed_when_publication_fails(tmp_path, monkeypatch):
    boundary = "shinsekai-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="effect.ef"\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
        "payload\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    staging_dir = tmp_path / "upload-staging"
    staging_dir.mkdir()
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    handler.rfile = BytesIO(body)
    monkeypatch.setattr(
        handler_module,
        "create_private_temporary_directory",
        lambda **_kwargs: (staging_dir, staging_dir.lstat()),
    )

    def fail_publication(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(handler_module, "write_bytes_exclusive", fail_publication)

    with pytest.raises(OSError, match="disk full"):
        handler._read_upload_files()

    assert not staging_dir.exists()


def test_upload_cleanup_preserves_a_replacement_directory(tmp_path):
    staging = tmp_path / "upload-staging"
    preserved = tmp_path / "preserved"
    staging.mkdir()
    (staging / "owned.bin").write_bytes(b"owned")
    identity = staging.lstat()
    staging.rename(preserved)
    staging.mkdir()
    replacement = staging / "replacement.bin"
    replacement.write_bytes(b"replacement")

    handler_module._cleanup_upload_directory(staging, identity)

    assert replacement.read_bytes() == b"replacement"
    assert (preserved / "owned.bin").read_bytes() == b"owned"


def test_attachment_upload_passes_bridge_project_root_to_staging(tmp_path, monkeypatch):
    project_root = tmp_path / "selected-project"
    project_root.mkdir()
    upload_dir = tmp_path / "upload-staging"
    upload_dir.mkdir()
    upload = upload_dir / "attachment.txt"
    upload.write_text("payload", encoding="utf-8")
    captured = {}

    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(
        state=SimpleNamespace(project_root_dir=project_root.as_posix())
    )
    handler.path = "/api/chat/attachments/upload"
    handler._require_authorized_write = lambda _path: None
    handler._read_upload_files = lambda: (upload_dir, upload_dir.lstat(), [upload])
    handler._send_json = lambda payload, *_args, **_kwargs: captured.setdefault(
        "response", payload
    )
    handler._is_client_disconnect = lambda _exc: False
    handler._log_request_exception = lambda _exc: None
    handler._send_exception_json = lambda exc: pytest.fail(str(exc))

    staged = [{"kind": "file", "name": upload.name, "path": upload.name, "size": 7}]

    def fake_stage(paths, *, project_root):
        captured["paths"] = list(paths)
        captured["project_root"] = project_root
        return staged

    monkeypatch.setattr(handler_module, "stage_uploaded_chat_attachments", fake_stage)
    monkeypatch.setattr(handler_module, "_cleanup_upload_directory", lambda *_args: None)

    handler._handle_write("POST")

    assert captured["paths"] == [upload]
    assert captured["project_root"] == project_root.resolve()
    assert captured["response"] == {"attachments": staged}
