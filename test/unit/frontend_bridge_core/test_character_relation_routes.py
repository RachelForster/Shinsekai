from types import SimpleNamespace
from unittest.mock import Mock
import pytest
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

def test_resolver_rejects_invalid_character_names(monkeypatch):
    from application.character_relation.manage_relations import CharacterRelationUseCase
    service = CharacterRelationUseCase(None, None)
    monkeypatch.setattr(service, "get_relation_graph", lambda _: {})
    monkeypatch.setattr(routes, "get_relation_use_case", lambda _: service)
    with pytest.raises(ValueError, match="character_names"):
        routes.select_relation_context(request({"owner": "A", "character_names": "B"}))

def test_routes_register_without_legacy_profile_endpoints():
    router = Router(routes.CHARACTER_RELATION_ROUTES)
    assert router.match("GET", "/api/character-relations/graphs/A")
    assert router.match("POST", "/api/character-relations/graphs/A/changes")
    assert router.match("POST", "/api/character-relations/context")
    assert router.match("POST", "/api/character-relations/resolve") is None
    assert router.match("POST", "/api/character-relations/profiles/A") is None


def test_context_selection_passes_only_participating_names(monkeypatch):
    service = Mock()
    monkeypatch.setattr(routes, "get_relation_use_case", lambda _: service)
    routes.select_relation_context(request({
        "owner": "A", "character_names": ["B"], "query": "Mention C",
    }))
    service.select_relation_context.assert_called_once_with("A", ["B"])
