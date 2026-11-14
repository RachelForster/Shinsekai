from types import SimpleNamespace
from unittest.mock import Mock
from frontend_bridge_core.routes import character_relation_routes as routes
from frontend_bridge_core.routes.router import ApiRequest, Router, JsonResponse

def request(body=None, **params):
    return ApiRequest(state=SimpleNamespace(), method="POST", path="/", query={}, params=params, body=body or {})

def test_graph_read(monkeypatch):
    service = Mock()
    monkeypatch.setattr(routes, "get_relation_use_case", lambda _: service)
    assert isinstance(routes.get_relation_graph(request(owner="A")), JsonResponse)
    service.get_relation_graph.assert_called_once_with("A")

def test_owner_is_taken_from_route_and_changes_are_synchronous(monkeypatch):
    service = Mock()
    monkeypatch.setattr(routes, "get_relation_use_case", lambda _: service)
    response = routes.apply_relation_changes(request({"owner": "B", "operations": []}, owner="A"))
    assert isinstance(response, JsonResponse)
    service.apply_relation_changes.assert_called_once_with("A", [])

def test_routes_register_without_legacy_profile_endpoints():
    router = Router(routes.CHARACTER_RELATION_ROUTES)
    assert router.match("GET", "/api/character-relations/graphs/A")
    assert router.match("POST", "/api/character-relations/graphs/A/changes")
    assert router.match("POST", "/api/character-relations/context") is None
    assert router.match("POST", "/api/character-relations/resolve") is None
    assert router.match("POST", "/api/character-relations/profiles/A") is None
