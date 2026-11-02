from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes import api, knowledge_routes


@pytest.mark.parametrize("body,status", [
    ({"knowledge_id": "a", "add": ["A", "B"], "remove": ["C"]}, 200),
    ({"knowledge_id": "a", "add": "A", "remove": []}, 400),
    ({"knowledge_id": "a", "add": ["A"], "remove": [" A "]}, 400),
    ({"knowledge_id": "a", "add": [None], "remove": []}, 400),
    ({"knowledge_id": " ", "add": [], "remove": []}, 400),
])
def test_batch_binding_route_validates_before_dispatch(monkeypatch, body, status):
    calls, responses = [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/bindings/batch"
    handler._require_authorized_write = lambda path: None
    handler._read_json = lambda: body
    handler._send_json = lambda payload, status=200: responses.append((payload, status))
    handler._log_request_exception = lambda exc: None
    monkeypatch.setattr(knowledge_routes, "_knowledge_binding_operation", lambda op, **kw: calls.append((op, kw)) or {"ok": True})
    handler.do_POST()
    assert responses[0][1] == status
    assert calls == ([("batch", body)] if status == 200 else [])


def test_binding_names_get_uses_sqlite_operation(monkeypatch):
    calls, responses = [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/bindings/knowledge?knowledge_id=a%26b"
    handler._require_authorized_read = lambda path: None
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_binding_operation", lambda op, **kw: calls.append((op, kw)) or {"characterNames": []})
    handler.do_GET()
    assert calls == [("knowledge", {"knowledge_id": "a&b"})]
    assert responses == [{"characterNames": []}]


@pytest.mark.parametrize("names,expected_status", [(["A", "B"], 200), ("A", 400)])
def test_knowledge_search_preserves_chat_client_contract(monkeypatch, names, expected_status):
    calls, responses = [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/search"
    handler._require_authorized_write = lambda path: None
    handler._read_json = lambda: {"query": "harbor", "characterNames": names}
    handler._send_json = lambda payload, status=200: responses.append((payload, status))
    handler._log_request_exception = lambda exc: None
    monkeypatch.setattr(
        knowledge_routes, "_knowledge_search",
        lambda *args: calls.append(args) or {"memories": []},
    )
    handler.do_POST()
    assert responses[0][1] == expected_status
    assert calls == ([("harbor", ["A", "B"], 5)] if expected_status == 200 else [])


@pytest.mark.parametrize("path,operation,kwargs", [
    ("/api/knowledge/instances?query=harbor&page=2&refresh=true", "instances", {"query": "harbor", "page": 2, "refresh": True}),
    ("/api/knowledge/entries?knowledge_id=alpha", "entries", {"knowledge_id": "alpha"}),
])
def test_knowledge_get_routes_dispatch_to_browse(monkeypatch, path, operation, kwargs):
    calls, responses, authorized = [], [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = path
    handler._require_authorized_read = authorized.append
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_browse", lambda operation, **kwargs: calls.append((operation, kwargs)) or {"ok": True})
    handler.do_GET()
    assert authorized == [path.split("?")[0]]
    assert calls == [(operation, kwargs)]
    assert responses == [{"ok": True}]


def test_knowledge_entry_search_post_preserves_explicit_knowledge(monkeypatch):
    calls, responses = [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/entries/search"
    handler._require_authorized_write = lambda path: None
    handler._read_json = lambda: {"knowledge_id": "alpha", "query": "harbor", "limit": 20}
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_browse", lambda operation, **kwargs: calls.append((operation, kwargs)) or {"memories": []})
    handler.do_POST()
    assert calls == [("entries/search", {"knowledge_id": "alpha", "query": "harbor", "limit": 20})]
    assert responses == [{"memories": []}]


@pytest.mark.parametrize("operation,body,expected", [
    ("delete", {"knowledge_id": "a"}, {"knowledge_id": "a"}),
    ("list", {"knowledge_id": "a", "limit": 10}, {"knowledge_id": "a", "limit": 10}),
    ("remember", {"knowledge_id": "a", "content": "fact"}, {"knowledge_id": "a", "content": "fact"}),
    ("forget", {"memory_id": "id"}, {"memory_id": "id"}),
    ("remember-and-list", {"knowledge_id": "a", "content": "fact"}, {"knowledge_id": "a", "content": "fact"}),
    ("forget-and-list", {"knowledge_id": "a", "memory_id": "id"}, {"knowledge_id": "a", "memory_id": "id"}),
])
def test_knowledge_mutation_routes(monkeypatch, operation, body, expected):
    calls, responses = [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = f"/api/knowledge/{operation}"
    handler._require_authorized_write = lambda path: None
    handler._read_json = lambda: body
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_operation", lambda op, **kw: calls.append((op, kw)) or {"ok": True})
    handler.do_POST()
    assert calls == [(operation, expected)]
    assert responses == [{"ok": True}]


def test_knowledge_status_route_supports_explicit_retry(monkeypatch):
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/status"
    handler._require_authorized_write = lambda path: None
    handler._read_json = lambda: {"retry": True}
    calls, responses = [], []
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_get_knowledge_status", lambda **kw: calls.append(kw) or {"status": "loading"})
    handler.do_POST()
    assert calls == [{"start_loading": False, "retry": True}]
    assert responses == [{"status": "loading"}]


@pytest.mark.parametrize("operation,body", [
    ("add", {"character_name": "A", "knowledge_id": "w"}),
    ("remove", {"character_name": "A", "knowledge_id": "w"}),
])
def test_binding_write_routes_require_authorization(monkeypatch, operation, body):
    calls, responses, authorized = [], [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = f"/api/knowledge/bindings/{operation}"
    handler._require_authorized_write = authorized.append
    handler._read_json = lambda: body
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_binding_operation", lambda op, **kw: calls.append((op, kw)) or {"ok": True})
    handler.do_POST()
    assert authorized == [handler.path]
    assert calls == [(operation, body)]
    assert responses == [{"ok": True}]


def test_binding_read_route(monkeypatch):
    calls, responses, authorized = [], [], []
    handler = object.__new__(api.FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=object())
    handler.path = "/api/knowledge/bindings?character_name=A%26B&page=2"
    handler._require_authorized_read = authorized.append
    handler._send_json = lambda payload, status=200: responses.append(payload)
    handler._is_client_disconnect = lambda exc: False
    handler._log_request_exception = lambda exc: pytest.fail(str(exc))
    monkeypatch.setattr(knowledge_routes, "_knowledge_binding_operation", lambda op, **kw: calls.append((op, kw)) or {"bindings": []})
    handler.do_GET()
    assert authorized == ["/api/knowledge/bindings"]
    assert calls == [("list", {"character_name": "A&B", "page": 2})]
