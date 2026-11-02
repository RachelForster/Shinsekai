"""Remote knowledge functions build HTTP requests only when called."""
from io import BytesIO
import json
import urllib.error
from unittest.mock import Mock

import pytest

from frontend_bridge_core.transport.knowledge_http import (
    request_knowledge_search, request_knowledge_status,
)


@pytest.fixture(autouse=True)
def remote_config(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", " http://bridge/api/knowledge/ ")
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC", raising=False)
    monkeypatch.setattr("application.knowledge.runtime.get_mem0", lambda: pytest.fail("local store accessed"))


@pytest.mark.parametrize("token", ["", "secret"])
def test_search_preserves_protocol_and_authentication(monkeypatch, token):
    calls = []
    def send(request, *, timeout):
        calls.append((request, timeout))
        return BytesIO(b'{"memories":[]}')
    monkeypatch.setenv("SHINSEKAI_MEMORY_SERVICE_TOKEN", f" {token} ")
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert request_knowledge_search("雾港", character_names=["A", "B"], limit=3) == {"memories": []}
    request, timeout = calls[0]
    assert request.full_url == "http://bridge/api/knowledge/search"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"query": "雾港", "characterNames": ["A", "B"], "limit": 3}
    assert "雾港" in request.data.decode("utf-8")
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["accept"] == "application/json"
    assert headers["content-type"] == "application/json"
    assert headers.get("x-shinsekai-bridge-token") == (token or None)
    assert timeout == 60.0


@pytest.mark.parametrize("configured,expected", [("", 60.0), ("bad", 60.0), ("0", 60.0), ("-1", 60.0), ("nan", 60.0), ("2.5", 2.5)])
def test_status_preserves_flags_and_timeout(monkeypatch, configured, expected):
    calls = []
    def send(request, *, timeout):
        calls.append((request, timeout))
        return BytesIO(b'{"status":"loading"}')
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC", configured)
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert request_knowledge_status(start_loading=True, retry=True) == {"status": "loading"}
    request, timeout = calls[0]
    assert request.full_url == "http://bridge/api/knowledge/status"
    assert json.loads(request.data) == {"startLoading": True, "retry": True}
    assert timeout == expected


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"null"])
def test_invalid_response_is_an_error_result(monkeypatch, payload):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(payload))
    assert "error" in request_knowledge_status()


@pytest.mark.parametrize("detail,expected", [(b"denied", "denied"), (b"", "Forbidden")])
def test_http_error_preserves_status_and_detail(monkeypatch, detail, expected):
    def send(*args, **kwargs):
        raise urllib.error.HTTPError("http://bridge", 403, "Forbidden", {}, BytesIO(detail))
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert request_knowledge_status() == {"error": f"knowledge service HTTP 403: {expected}"}


def test_network_failure_never_falls_back_to_local_storage(monkeypatch):
    def send(*args, **kwargs):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert "offline" in request_knowledge_search("fact", character_names=["A"])["error"]


@pytest.mark.parametrize("url,owner", [("", "0"), ("http://bridge", "1")])
def test_unconfigured_requests_never_send_or_load_store(monkeypatch, url, owner):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", url)
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", owner)
    send = Mock()
    monkeypatch.setattr("urllib.request.urlopen", send)
    assert request_knowledge_status() is None
    assert "error" in request_knowledge_search("fact", character_names=["A"])
    send.assert_not_called()


def test_connection_configuration_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_ENABLED", "0")
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, **kw: calls.append(req.full_url) or BytesIO(b'{}'))
    assert request_knowledge_status() == {}
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://new-service")
    assert request_knowledge_search("fact", character_names=["A"]) == {}
    assert calls == ["http://bridge/api/knowledge/status", "http://new-service/search"]
