from __future__ import annotations

import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from frontend_bridge_core.config import _openai_chat_endpoint
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.security import (
    download_url,
    host_matches,
    safe_content_disposition,
    safe_child_path,
    safe_existing_dir_path,
    safe_existing_file_path,
    safe_executable,
    safe_filename,
    safe_project_path,
    safe_search_query,
    validated_http_url,
)


def test_download_url_encodes_path_as_one_query_value():
    path = "/tmp/项目 & 100% #ready/archive.zip"
    url = download_url(path)

    assert url.startswith("/api/download?path=")
    assert parse_qs(urlsplit(url).query, errors="strict") == {"path": [path]}
    assert " " not in url
    assert "#" not in url
    assert "&" not in url.partition("?")[2]


def test_validated_http_url_rejects_control_chars_and_special_use_ips():
    for value in (
        "https://example.com\r\nX-Test: bad",
        " https://example.com/path",
        "https://example.com/path ",
        r"https://example.com\@attacker.test/path",
        "https://user:secret@example.com/path",
        "https://example.com/path#fragment",
    ):
        with pytest.raises(ValueError):
            validated_http_url(value)

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


def test_validated_http_url_normalizes_ipv6_loopback_without_changing_ownership():
    url = "http://[::1]:8080/v1/models"

    assert (
        validated_http_url(
            url,
            allow_localhost=True,
            allow_private_hosts=True,
        )
        == url
    )


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
    with pytest.raises(ValueError, match="absolute"):
        safe_executable("../definitely-missing-python", default="yt-dlp")

    with pytest.raises(ValueError):
        safe_executable("python;rm", default="yt-dlp")

    with pytest.raises(ValueError):
        safe_executable("python&&echo", default="yt-dlp")

    with pytest.raises(ValueError, match="surrounding whitespace"):
        safe_executable(" python", default="yt-dlp")

    with pytest.raises(ValueError, match="absolute"):
        safe_executable("~/python", default="yt-dlp")


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
    assert safe_filename("report.TXT", default_suffix=".txt") == "report.txt"
    assert safe_filename("a" * 255, default_suffix=".txt") == ("a" * 251) + ".txt"


def test_safe_filename_rejects_path_separators():
    with pytest.raises(ValueError):
        safe_filename("../secret")

    with pytest.raises(ValueError):
        safe_filename("dir/evil")

    with pytest.raises(ValueError):
        safe_filename(r"dir\evil")

    with pytest.raises(ValueError, match="surrounding whitespace"):
        safe_filename(" report.txt")


def test_safe_project_path_rejects_traversal(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)

    with pytest.raises(PermissionError):
        safe_project_path("../secret.txt")

    with pytest.raises(ValueError, match="surrounding whitespace"):
        safe_project_path(" data/file.txt", root=root)


def test_safe_project_path_rejects_ambiguous_windows_drive_relative_path(tmp_path):
    with pytest.raises(ValueError, match="drive-relative"):
        safe_project_path("D:session.json", root=tmp_path)


def test_safe_child_path_preserves_exact_portable_relative_identity(tmp_path):
    assert safe_child_path(tmp_path, "assets/app.js") == tmp_path / "assets" / "app.js"


@pytest.mark.parametrize(
    "raw",
    [
        "/assets/app.js",
        r"assets\app.js",
        "assets/./app.js",
        "assets/../app.js",
        "assets//app.js",
        "assets/app.js/",
        "D:app.js",
    ],
)
def test_safe_child_path_rejects_aliases_instead_of_retargeting(tmp_path, raw):
    with pytest.raises(ValueError):
        safe_child_path(tmp_path, raw)


def test_safe_child_path_rejects_existing_link_component(tmp_path):
    external = tmp_path / "external"
    root = tmp_path / "root"
    external.mkdir()
    root.mkdir()
    try:
        (root / "assets").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        safe_child_path(root, "assets/app.js")


def test_safe_existing_paths_reject_file_and_directory_aliases(tmp_path):
    target_file = tmp_path / "target.txt"
    target_dir = tmp_path / "target-dir"
    file_alias = tmp_path / "file-alias.txt"
    dir_alias = tmp_path / "dir-alias"
    target_file.write_text("private", encoding="utf-8")
    target_dir.mkdir()
    try:
        file_alias.symlink_to(target_file)
        dir_alias.symlink_to(target_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        safe_existing_file_path(file_alias)
    with pytest.raises(PermissionError, match="symbolic link"):
        safe_existing_dir_path(dir_alias)


def test_static_path_removes_only_the_http_route_slash(tmp_path):
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)

    assert handler._resolve_static_path(tmp_path, "/assets/app.js") == (
        tmp_path / "assets" / "app.js"
    )
    with pytest.raises(ValueError):
        handler._resolve_static_path(tmp_path, "//assets/app.js")


def test_static_path_decodes_unicode_once_and_rejects_encoded_aliases(tmp_path):
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    asset = tmp_path / "assets" / "你好 world.js"
    literal_percent = tmp_path / "assets" / "100%2Fready.js"
    asset.parent.mkdir()
    asset.write_text("unicode", encoding="utf-8")
    literal_percent.write_text("literal", encoding="utf-8")

    assert handler._resolve_static_path(
        tmp_path,
        "/assets/%E4%BD%A0%E5%A5%BD%20world.js",
    ) == asset
    assert handler._resolve_static_path(
        tmp_path,
        "/assets/100%252Fready.js",
    ) == literal_percent
    with pytest.raises(ValueError):
        handler._resolve_static_path(tmp_path, "/assets/%2e%2e/secret.js")
    with pytest.raises(ValueError):
        handler._resolve_static_path(tmp_path, "/assets%5csecret.js")
    with pytest.raises(ValueError, match="percent"):
        handler._resolve_static_path(tmp_path, "/assets/bad%escape.js")


def _project_path_handler(project_root):
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(
        state=SimpleNamespace(project_root_dir=project_root.as_posix())
    )
    return handler


def test_http_project_file_resolver_uses_exact_project_identity(tmp_path):
    handler = _project_path_handler(tmp_path)

    assert handler._resolve_project_path("data/media/item.png") == (
        tmp_path / "data/media/item.png"
    )


@pytest.mark.parametrize(
    "raw",
    (
        "./data/media/item.png",
        "data//media/item.png",
        "data/./media/item.png",
        "data/media/../item.png",
        "data/media/item.png/",
    ),
)
def test_http_project_file_resolver_rejects_lexical_aliases(tmp_path, raw):
    handler = _project_path_handler(tmp_path)

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        handler._resolve_project_path(raw)


def test_http_media_resolver_distinguishes_resources_project_and_external_files(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    resource = source / "assets" / "system" / "picture.png"
    managed = project / "data" / "media" / "item.png"
    external = tmp_path / "external" / "item.png"
    resource.parent.mkdir(parents=True)
    managed.parent.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    resource.write_bytes(b"resource")
    managed.write_bytes(b"managed")
    external.write_bytes(b"external")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())
    handler = _project_path_handler(project)
    handler.server.state.chat_stream = SimpleNamespace(
        approved_external_media_paths=lambda: [external.as_posix()]
    )

    assert handler._resolve_media_path("assets/system/picture.png") == resource
    assert handler._resolve_media_path("data/media/item.png") == managed
    assert handler._resolve_media_path(external.as_posix()) == external
    assert handler._resolve_resource_path("assets/system/picture.png") == resource


def test_http_resource_resolver_rejects_linked_application_assets(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    external = tmp_path / "external"
    source.mkdir()
    project.mkdir()
    external.mkdir()
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())
    try:
        (source / "assets").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    handler = _project_path_handler(project)

    with pytest.raises(PermissionError, match="symbolic link"):
        handler._resolve_resource_path("assets/system/picture.png")


@pytest.mark.parametrize(
    "raw",
    (
        "./assets/system/picture.png",
        "assets//system/picture.png",
        "data/./media/item.png",
        "data/media/../item.png",
    ),
)
def test_http_media_resolver_rejects_lexical_aliases(tmp_path, raw):
    handler = _project_path_handler(tmp_path)

    with pytest.raises((PermissionError, ValueError)):
        handler._resolve_media_path(raw)


def test_http_project_file_resolver_does_not_guess_legacy_duplicate_segments(
    tmp_path,
):
    handler = _project_path_handler(tmp_path)
    canonical = tmp_path / "data/backgrounds/demo/image.png"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"image")

    resolved = handler._resolve_project_path(
        "data/backgrounds/demo/backgrounds/demo/image.png"
    )

    assert resolved != canonical
    assert not resolved.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows drive paths are native on Windows")
def test_safe_project_path_never_reinterprets_windows_absolute_path_as_posix_relative(tmp_path):
    with pytest.raises(ValueError, match="not native"):
        safe_project_path(r"D:\history\session.json", root=tmp_path)


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


def test_inject_bridge_token_matches_query_keys_not_path_or_query_values():
    handler = _handler_with_auth_token("secret-token")
    detail = {
        "pages": [
            {
                "frontendUrl": (
                    "/api/plugins/shinsekai_bridge_token/frontend/page/"
                    "?pluginId=shinsekai_bridge_token"
                )
            }
        ]
    }

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"] == (
        "/api/plugins/shinsekai_bridge_token/frontend/page/"
        "?pluginId=shinsekai_bridge_token&shinsekai_bridge_token=secret-token"
    )


def test_inject_bridge_token_replaces_stale_duplicates_and_preserves_fragment():
    handler = _handler_with_auth_token("new token")
    detail = {
        "pages": [
            {
                "frontendUrl": (
                    "/api/plugins/demo/frontend/page/"
                    "?shinsekai_bridge_token=stale&mode=full"
                    "&shinsekai_bridge_token=older#content"
                )
            }
        ]
    }

    result = handler._inject_bridge_token(detail)

    assert result["pages"][0]["frontendUrl"] == (
        "/api/plugins/demo/frontend/page/"
        "?mode=full&shinsekai_bridge_token=new+token#content"
    )
