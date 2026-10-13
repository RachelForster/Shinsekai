"""Outbound knowledge HTTP protocol and transitional configuration contracts."""

from io import BytesIO
import json
import urllib.error

import pytest

from ai.knowledge import operations, service
from frontend_bridge_core.routes.knowledge_routes import BridgeKnowledgeHttp


@pytest.mark.parametrize("token", ["", "secret"])
def test_request_preserves_http_protocol(monkeypatch, token):
    calls = []

    class Response(BytesIO):
        def read(self, size=-1):
            assert size == 1024 * 1024
            return super().read(size)

    def send(request, *, timeout):
        calls.append((request, timeout))
        return Response(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", send)
    payload = {"content": "雾港多雾。", "knowledge_id": "harbor"}
    assert BridgeKnowledgeHttp("http://bridge/api/knowledge/", token=token, timeout=12).request("remember", payload) == {"ok": True}
    request, timeout = calls[0]
    assert request.full_url == "http://bridge/api/knowledge/remember"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == payload
    assert "雾港多雾。" in request.data.decode("utf-8")
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["accept"] == "application/json"
    assert headers["content-type"] == "application/json"
    assert headers.get("x-shinsekai-bridge-token") == (token or None)
    assert timeout == 12


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"null"])
def test_invalid_response_is_an_error_result(monkeypatch, payload):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(payload))
    assert "error" in BridgeKnowledgeHttp("http://bridge").request("status", {})


@pytest.mark.parametrize("detail,expected", [(b"denied", "denied"), (b"", "Forbidden")])
def test_http_error_preserves_status_and_detail(monkeypatch, detail, expected):
    def send(*args, **kwargs):
        raise urllib.error.HTTPError("http://bridge", 403, "Forbidden", {}, BytesIO(detail))

    monkeypatch.setattr("urllib.request.urlopen", send)
    assert BridgeKnowledgeHttp("http://bridge").request("status", {}) == {
        "error": f"knowledge service HTTP 403: {expected}",
    }


def test_network_failure_never_falls_back_to_local_storage(monkeypatch):
    def send(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "0")
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://bridge")
    monkeypatch.setattr("urllib.request.urlopen", send)
    monkeypatch.setattr(operations, "get_mem0", lambda: pytest.fail("local fallback"))
    assert "offline" in operations.search_knowledge("fact", character_names=["A"])["error"]


@pytest.mark.parametrize("configured,expected", [("", 60.0), ("bad", 60.0), ("0", 60.0), ("-1", 60.0), ("2.5", 2.5)])
def test_service_preserves_connection_configuration(monkeypatch, configured, expected):
    calls = []

    def send(request, *, timeout):
        calls.append((request, timeout))
        return BytesIO(b'{"status":"loading"}')

    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "0")
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", " http://bridge/api/knowledge/ ")
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_TOKEN", " secret ")
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC", configured)
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert service.knowledge_service_status(start_loading=True, retry=True) == {"status": "loading"}
    request, timeout = calls[0]
    assert request.full_url == "http://bridge/api/knowledge/status"
    assert json.loads(request.data) == {"startLoading": True, "retry": True}
    assert request.get_header("X-shinsekai-bridge-token") == "secret"
    assert timeout == expected


def test_adapter_uses_explicit_settings_independently_of_owner(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "1")
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://unused")
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, **kw: calls.append(req.full_url) or BytesIO(b'{}'))
    assert BridgeKnowledgeHttp("http://explicit").request("status", {}) == {}
    assert calls == ["http://explicit/status"]
