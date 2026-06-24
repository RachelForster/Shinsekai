from __future__ import annotations

import pytest

from frontend_bridge_core.config import _openai_chat_endpoint
from frontend_bridge_core.handler import FrontendBridgeHandler
from frontend_bridge_core.security import (
    safe_content_disposition,
    safe_project_path,
    validated_http_url,
)


def test_validated_http_url_rejects_control_chars_and_special_use_ips():
    with pytest.raises(ValueError):
        validated_http_url("https://example.com\r\nX-Test: bad")

    with pytest.raises(ValueError):
        validated_http_url("http://169.254.169.254/latest/meta-data", allow_private_hosts=True)


def test_validated_http_url_allows_local_llm_when_requested():
    assert (
        validated_http_url(
            "http://127.0.0.1:1234/v1/chat/completions",
            allow_localhost=True,
            allow_private_hosts=True,
        )
        == "http://127.0.0.1:1234/v1/chat/completions"
    )


def test_llm_endpoint_rejects_metadata_service_url():
    with pytest.raises(ValueError):
        _openai_chat_endpoint("http://169.254.169.254/latest/meta-data")


def test_safe_project_path_rejects_traversal(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)

    with pytest.raises(PermissionError):
        safe_project_path("../secret.txt")


def test_safe_content_disposition_strips_header_control_chars():
    with pytest.raises(ValueError):
        safe_content_disposition('report.txt"\r\nX-Bad: 1')

    assert safe_content_disposition("报告 final.txt").startswith(
        'attachment; filename="final.txt"; filename*=UTF-8'
    )


def test_cors_reflects_only_sanitized_local_origins():
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    headers: list[tuple[str, str]] = []
    handler.headers = {"Origin": "http://localhost:5173"}
    handler.send_header = lambda key, value: headers.append((key, value))  # type: ignore[method-assign]

    handler._send_cors()

    assert ("Access-Control-Allow-Origin", "http://localhost:5173") in headers


def test_cors_drops_crlf_origin():
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    headers: list[tuple[str, str]] = []
    handler.headers = {"Origin": "http://localhost:5173\r\nX-Bad: 1"}
    handler.send_header = lambda key, value: headers.append((key, value))  # type: ignore[method-assign]

    handler._send_cors()

    assert not any(key == "Access-Control-Allow-Origin" for key, _value in headers)
