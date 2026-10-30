from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from ai.t2i.comfyui_connection import probe_comfyui_connection
from frontend_bridge_core.routes.router import ApiRequest, Router
from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES


def test_probe_only_reads_system_stats_and_supports_a_proxy_prefix(monkeypatch):
    get = Mock(
        return_value=Mock(
            status_code=200,
            json=lambda: {"system": {"comfyui_version": "0.3.test"}, "devices": []},
        )
    )
    monkeypatch.setattr("ai.t2i.comfyui_connection.requests.get", get)
    assert probe_comfyui_connection(" http://localhost:8189/comfy/ ") == {
        "ok": True,
        "code": "connected",
        "serverVersion": "0.3.test",
    }
    get.assert_called_once_with(
        "http://localhost:8189/comfy/system_stats", timeout=10, allow_redirects=False
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "C:/AI/ComfyUI",
        "file:///ComfyUI",
        "http://",
        "http://localhost:70000",
        "http://localhost:0",
        "http://user:password@localhost:8188",
        "http://localhost:8188/?token=secret",
        "http://localhost/#workflow",
        "http://local\nhost:8188",
        "http://bad host:8188",
    ],
)
def test_invalid_urls_are_rejected_without_network_access(monkeypatch, url):
    get = Mock()
    monkeypatch.setattr("ai.t2i.comfyui_connection.requests.get", get)
    assert probe_comfyui_connection(url) == {"ok": False, "code": "invalid_url"}
    get.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (requests.exceptions.Timeout(), "timeout"),
        (
            requests.exceptions.ConnectionError("private diagnostic detail"),
            "unreachable",
        ),
        (requests.exceptions.SSLError(), "tls_error"),
    ],
)
def test_probe_returns_actionable_failure_codes_without_raw_network_details(
    monkeypatch, failure, code
):
    monkeypatch.setattr(
        "ai.t2i.comfyui_connection.requests.get", Mock(side_effect=failure)
    )
    assert probe_comfyui_connection("http://127.0.0.1:8188") == {
        "ok": False,
        "code": code,
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "auth_required"),
        (403, "auth_required"),
        (302, "not_comfyui"),
        (404, "http_error"),
        (500, "http_error"),
    ],
)
def test_probe_distinguishes_auth_redirect_and_http_failures(monkeypatch, status, code):
    monkeypatch.setattr(
        "ai.t2i.comfyui_connection.requests.get",
        Mock(return_value=Mock(status_code=status)),
    )
    assert probe_comfyui_connection("http://127.0.0.1:8188") == {
        "ok": False,
        "code": code,
        "httpStatus": status,
    }


def test_probe_rejects_html_with_a_success_status(monkeypatch):
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("HTML login page")
    monkeypatch.setattr(
        "ai.t2i.comfyui_connection.requests.get", Mock(return_value=response)
    )
    assert probe_comfyui_connection("http://localhost:8188") == {
        "ok": False,
        "code": "not_comfyui",
    }


def test_connection_route_checks_the_unsaved_address_and_never_initializes_adapter(
    monkeypatch,
):
    probe = Mock(return_value={"ok": True, "code": "connected"})
    start = Mock(
        side_effect=AssertionError("A connection check must not start ComfyUI")
    )
    monkeypatch.setattr("ai.t2i.comfyui_connection.probe_comfyui_connection", probe)
    monkeypatch.setattr("ai.t2i.t2i_adapter.ComfyUIT2IAdapter.__init__", start)
    path = "/api/config/comfyui-connection-test"
    match = Router(list(SYSTEM_ROUTES)).match("POST", path)
    request = ApiRequest(
        state=None,
        method="POST",
        path=path,
        query={},
        params={},
        body={"baseUrl": "http://localhost:8189"},
    )
    response = match.route.handler(request)
    assert response.data == {"ok": True, "code": "connected"}
    probe.assert_called_once_with("http://localhost:8189")
    start.assert_not_called()
