from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_bridge_core.handler import BRIDGE_AUTH_HEADER, FrontendBridgeHandler
from frontend_bridge_core.media_paths import (
    _validate_windows_local_drive_path,
    iter_configured_external_media_paths,
    resolve_external_media_file,
    validate_readable_media_file,
)


def _handler_with_auth_token(
    token: str = "bridge-secret",
    *,
    configured_paths: list[str] | None = None,
    runtime_paths: list[str] | None = None,
) -> FrontendBridgeHandler:
    approved_runtime_paths = tuple(runtime_paths or ())
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(  # type: ignore[assignment]
        state=SimpleNamespace(
            auth_token=token,
            chat_stream=SimpleNamespace(
                approved_external_media_paths=lambda: approved_runtime_paths
            ),
            config_manager=SimpleNamespace(
                config={"configured_media": list(configured_paths or ())}
            ),
        )
    )
    handler.headers = {}
    return handler


@pytest.mark.parametrize("suffix", [".PNG", ".mp3", ".mkv", ".woff2"])
def test_readable_media_file_accepts_supported_regular_files(tmp_path: Path, suffix: str):
    source = tmp_path / f"asset{suffix}"
    source.write_bytes(b"media")

    assert validate_readable_media_file(source, roots=[tmp_path]) == source.resolve()


@pytest.mark.parametrize("suffix", [".txt", ".json", ".env", ".pem", ".yaml"])
def test_readable_media_file_rejects_non_media_extensions(tmp_path: Path, suffix: str):
    source = tmp_path / f"secret{suffix}"
    source.write_text("not media", encoding="utf-8")

    with pytest.raises(PermissionError, match="file type"):
        validate_readable_media_file(source, roots=[tmp_path])


def test_readable_media_file_rejects_directory_even_with_media_extension(tmp_path: Path):
    source = tmp_path / "not-a-file.mp4"
    source.mkdir()

    with pytest.raises(PermissionError, match="regular file"):
        validate_readable_media_file(source, roots=[tmp_path])


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_readable_media_file_rejects_fifo(tmp_path: Path):
    source = tmp_path / "named-pipe.mp3"
    os.mkfifo(source)

    with pytest.raises(PermissionError, match="regular file"):
        validate_readable_media_file(source, roots=[tmp_path])


def test_windows_path_policy_allows_absolute_local_drive_paths():
    _validate_windows_local_drive_path(r"Z:\media\clip.mp4")


@pytest.mark.parametrize(
    "raw_path",
    [
        r"\\.\pipe\shinsekai",
        r"\\?\C:\media\clip.mp4",
        r"\??\C:\media\clip.mp4",
        r"\\server\share\clip.mp4",
        r"D:relative\clip.mp4",
        r"C:\secrets\config.json:cover.png",
    ],
)
def test_windows_path_policy_rejects_device_unc_and_drive_relative_paths(raw_path: str):
    with pytest.raises(PermissionError):
        _validate_windows_local_drive_path(raw_path)


def test_media_resolver_allows_external_file_but_download_resolver_stays_project_scoped(
    tmp_path: Path,
    monkeypatch,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    external_media = tmp_path / "外部" / "语音.wav"
    external_media.parent.mkdir()
    external_media.write_bytes(b"media")
    monkeypatch.chdir(project_root)

    handler = _handler_with_auth_token(configured_paths=[str(external_media)])

    assert handler._resolve_media_path(str(external_media)) == external_media.resolve()
    assert resolve_external_media_file(
        external_media,
        approved_paths=[external_media],
    ) == external_media.resolve()

    with pytest.raises(PermissionError):
        handler._resolve_project_path(str(external_media))


def test_media_resolver_allows_runtime_registered_external_file(tmp_path: Path):
    external_media = tmp_path / "generated" / "voice.wav"
    external_media.parent.mkdir()
    external_media.write_bytes(b"media")
    handler = _handler_with_auth_token(runtime_paths=[str(external_media)])

    assert handler._resolve_media_path(str(external_media)) == external_media.resolve()


def test_media_resolver_rejects_unregistered_absolute_path(tmp_path: Path):
    external_media = tmp_path / "unregistered" / "voice.wav"
    external_media.parent.mkdir()
    external_media.write_bytes(b"media")
    handler = _handler_with_auth_token()

    with pytest.raises(PermissionError, match="not been approved"):
        handler._resolve_media_path(str(external_media))


@pytest.mark.skipif(os.name != "nt", reason="cross-drive paths are Windows-specific")
def test_configured_media_path_discovery_preserves_other_drive_paths():
    config = {
        "characters": [
            {
                "voice": r"D:\ShinsekaiAssets\voices\line.wav",
                "notes": r"D:\ShinsekaiAssets\notes.txt",
            }
        ],
        "bgm": r"E:\Music\scene.mp3",
    }

    assert tuple(iter_configured_external_media_paths(config)) == (
        r"D:\ShinsekaiAssets\voices\line.wav",
        r"E:\Music\scene.mp3",
    )


def test_media_get_requires_valid_bridge_token():
    handler = _handler_with_auth_token()
    handler.path = "/api/media?path=data%2Fvoice.mp3"
    sent: list[str] = []
    errors: list[Exception] = []
    handler._send_media_file = lambda path: sent.append(path)  # type: ignore[method-assign]
    handler._log_request_exception = lambda _exc: None  # type: ignore[method-assign]
    handler._send_exception_json = lambda exc: errors.append(exc)  # type: ignore[method-assign]

    handler.do_GET()

    assert not sent
    assert len(errors) == 1
    assert isinstance(errors[0], PermissionError)
    assert "auth token" in str(errors[0])


def test_media_get_accepts_bridge_token_from_query():
    handler = _handler_with_auth_token()
    handler.path = (
        "/api/media?path=data%2Fvoice.mp3"
        "&shinsekai_bridge_token=bridge-secret"
    )
    sent: list[str] = []
    handler._send_media_file = lambda path: sent.append(path)  # type: ignore[method-assign]

    handler.do_GET()

    assert sent == ["data/voice.mp3"]


def test_media_head_accepts_bridge_token_header_and_sends_no_body():
    handler = _handler_with_auth_token()
    handler.path = "/api/media?path=data%2Fvoice.mp3"
    handler.headers = {BRIDGE_AUTH_HEADER: "bridge-secret"}
    sent: list[tuple[str, bool]] = []
    handler._send_media_file = (  # type: ignore[method-assign]
        lambda path, *, send_body=True: sent.append((path, send_body))
    )

    handler.do_HEAD()

    assert sent == [("data/voice.mp3", False)]


def test_media_read_rejects_untrusted_origin_even_with_valid_token():
    handler = _handler_with_auth_token()
    handler.path = "/api/media?shinsekai_bridge_token=bridge-secret"
    handler.headers = {"Origin": "https://example.com"}

    with pytest.raises(PermissionError, match="origin"):
        handler._require_authorized_media_read()
