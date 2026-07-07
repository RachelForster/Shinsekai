from __future__ import annotations

from types import SimpleNamespace

import pytest

from frontend_bridge_core.config import _openai_chat_endpoint
from frontend_bridge_core.handler import FrontendBridgeHandler
from frontend_bridge_core.security import (
    host_matches,
    safe_content_disposition,
    safe_executable,
    safe_filename,
    safe_project_path,
    safe_search_query,
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


def test_validated_http_url_respects_allowed_hosts_accepts_matching_host():
    url = "https://example.com/path"

    assert validated_http_url(url, allowed_hosts={"example.com"}) == url


def test_validated_http_url_respects_allowed_hosts_rejects_lookalike_domains():
    with pytest.raises(ValueError):
        validated_http_url("https://example.com.evil.com/path", allowed_hosts={"example.com"})

    with pytest.raises(ValueError):
        validated_http_url("https://evil-example.com/path", allowed_hosts={"example.com"})


def test_validated_http_url_rejects_localhost_by_default():
    with pytest.raises(ValueError):
        validated_http_url("http://localhost:8080")


def test_validated_http_url_allows_localhost_when_requested():
    url = "http://localhost:8080"

    assert validated_http_url(url, allow_localhost=True) == url


def test_host_matches_exact_host():
    assert host_matches("example.com", {"example.com"})
    assert host_matches("example.com", {"example.org", "example.com"})
    assert not host_matches("example.com", {"example.org", "sub.example.com"})
    assert not host_matches("evil.com", {"example.com"})


def test_host_matches_subdomains():
    assert host_matches("sub.example.com", {"example.com"})
    assert host_matches("deep.sub.example.com", {"example.com"})
    assert not host_matches("example.com.evil.com", {"example.com"})
    assert not host_matches("sub.example.org", {"example.com"})


def test_llm_endpoint_rejects_metadata_service_url():
    with pytest.raises(ValueError):
        _openai_chat_endpoint("http://169.254.169.254/latest/meta-data")


def test_safe_executable_allows_simple_command_and_default():
    assert safe_executable("python", default="yt-dlp") == "python"
    assert safe_executable("my_tool-1", default="yt-dlp") == "my_tool-1"
    assert safe_executable("", default="yt-dlp") == "yt-dlp"


def test_safe_executable_rejects_missing_paths_and_shell_metacharacters():
    with pytest.raises(FileNotFoundError):
        safe_executable("../definitely-missing-python", default="yt-dlp")

    with pytest.raises(ValueError):
        safe_executable("python;rm", default="yt-dlp")

    with pytest.raises(ValueError):
        safe_executable("python&&echo", default="yt-dlp")


def test_safe_search_query_allows_basic_queries():
    query = 'status:open tag:test message:"hello world"'

    assert safe_search_query(query) == query


def test_safe_search_query_rejects_control_chars_and_newlines():
    with pytest.raises(ValueError):
        safe_search_query("bad\nquery")

    with pytest.raises(ValueError):
        safe_search_query("bad\rquery")

    with pytest.raises(ValueError):
        safe_search_query("bad\tquery")


def test_safe_filename_applies_default_suffix_when_requested():
    assert safe_filename("report", default_suffix=".txt") == "report.txt"
    assert safe_filename("report.txt", default_suffix=".txt") == "report.txt"


def test_safe_filename_rejects_path_separators():
    with pytest.raises(ValueError):
        safe_filename("../secret")

    with pytest.raises(ValueError):
        safe_filename("dir/evil")

    with pytest.raises(ValueError):
        safe_filename(r"dir\evil")


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


def _handler_with_auth_token(token: str) -> FrontendBridgeHandler:
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=SimpleNamespace(auth_token=token))  # type: ignore[assignment]
    return handler


def test_inject_bridge_token_appends_token_to_frontend_urls():
    handler = _handler_with_auth_token("secret-token")
    detail = {
        "pages": [
            {"frontendUrl": "/api/plugins/demo/frontend/page/?pluginId=demo&pageId=page"},
            {"frontendUrl": "/api/plugins/demo/frontend/bare/"},
        ]
    }

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"].endswith("&shinsekai_bridge_token=secret-token")
    assert result["pages"][1]["frontendUrl"].endswith("?shinsekai_bridge_token=secret-token")


def test_inject_bridge_token_leaves_non_api_frontend_urls_unchanged():
    handler = _handler_with_auth_token("secret-token")
    detail = {
        "pages": [
            {
                "id": "external-page",
                "kind": "settings",
                "frontendUrl": "https://example.com/plugin",
            },
            {
                "id": "internal-non-api-page",
                "kind": "settings",
                "frontendUrl": "/plugins/demo/frontend/page/",
            },
        ]
    }

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"] == "https://example.com/plugin"
    assert result["pages"][1]["frontendUrl"] == "/plugins/demo/frontend/page/"


def test_inject_bridge_token_leaves_pages_without_frontend_url_untouched():
    handler = _handler_with_auth_token("secret-token")
    detail = {"pages": [{"id": "widget-page", "kind": "settings"}]}

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0] == {"id": "widget-page", "kind": "settings"}


def test_inject_bridge_token_noop_when_auth_disabled():
    handler = _handler_with_auth_token("")
    url = "/api/plugins/demo/frontend/page/?pluginId=demo&pageId=page"
    detail = {"pages": [{"frontendUrl": url}]}

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"] == url


def test_inject_bridge_token_does_not_duplicate_existing_token():
    handler = _handler_with_auth_token("secret-token")
    url = "/api/plugins/demo/frontend/page/?shinsekai_bridge_token=secret-token"
    detail = {"pages": [{"frontendUrl": url}]}

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"] == url
