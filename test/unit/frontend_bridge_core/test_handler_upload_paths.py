from io import BytesIO

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
