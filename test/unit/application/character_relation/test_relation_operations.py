"""Relation graph mutations, queries, and persistence through the use case.

Names follow test_<operation>_<condition>_<expected_behavior>.
Input constraints are checked through operations; prompt rendering belongs in chat tests.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from application.character_relation.manage_relations import CharacterRelationUseCase, apply_relation_operations
from config.config_manager import ConfigManager
from config.schema import Character


@pytest.fixture
def relation_config(tmp_path, monkeypatch):
    config = object.__new__(ConfigManager)
    config._CHARACTERS_CONFIG_PATH = tmp_path / "characters.yaml"
    config._config = SimpleNamespace(characters=[
        Character(name=name, color="#fff", sprite_prefix=name, character_brief=f"Brief {name}")
        for name in ("chuchu", "pareo", "lock")
    ])
    monkeypatch.setattr("config.character_manager.ConfigManager", lambda: config)
    return config


@pytest.fixture
def service(relation_config):
    return CharacterRelationUseCase(relation_config)


def apply(service, *operations, owner="chuchu"):
    return service.apply_relation_changes(owner, list(operations))


def add_node(key):
    return {"op": "add_node", "node": {"key": key}}


def upsert_edge(source="chuchu", target="pareo", **fields):
    return {"op": "upsert_edge", "edge": {
        "source": source, "target": target, "content": "Trusted friend", **fields,
    }}


@pytest.fixture
def initialized_graph(service):
    return apply(service, add_node("pareo"), add_node("lock"),
                 upsert_edge(temperature=7), upsert_edge("pareo", "chuchu", temperature=-2))


def test_query_uninitialized_graph_returns_owner_node(service):
    assert service.get_relation_graph("chuchu")["nodes"] == [{"key": "chuchu"}]


def rename_owner(service, new_name):
    return service.character_manager.add_character(
        new_name, "#fff", "chuchu", "", "", "", "", "", "",
        edit_as_name="chuchu",
    )


@pytest.mark.parametrize("new_name", ["Renamed", "CHUCHU"])
def test_rename_owner_migrates_graph(service, initialized_graph, new_name):
    other_before = deepcopy(service.get_relation_graph("pareo"))
    rename_owner(service, new_name)
    graph = service.get_relation_graph(new_name)
    expected = deepcopy(initialized_graph)
    expected["owner"] = new_name
    for node in expected["nodes"]:
        if node["key"] == "chuchu":
            node["key"] = new_name
    for collection in ("edges", "outgoing", "incoming"):
        for edge in expected[collection]:
            for endpoint in ("source", "target"):
                if edge[endpoint] == "chuchu":
                    edge[endpoint] = new_name
    assert graph == expected
    assert service.get_relation_graph("pareo") == other_before
    data = yaml.safe_load(service.config._CHARACTERS_CONFIG_PATH.read_text(encoding="utf-8"))
    reopened = Character.model_validate(next(item for item in data if item["name"] == new_name))
    assert reopened.relation_graph.model_dump(mode="json", exclude_none=True) == {
        field: graph[field] for field in ("nodes", "edges")
    }
    with pytest.raises(ValueError, match="Cannot delete the owner node"):
        apply(service, {"op": "delete_node", "key": new_name}, owner=new_name)


def test_empty_graph_returns_new_owner_node(service):
    rename_owner(service, "Renamed")
    graph = service.get_relation_graph("Renamed")
    assert graph["nodes"] == [{"key": "Renamed"}]
    assert graph["edges"] == []


def test_update_owner_same_name_preserves_graph(service, initialized_graph):
    rename_owner(service, "chuchu")
    assert service.get_relation_graph("chuchu") == initialized_graph


def test_rename_owner_node_collision_preserves_character_and_file(service, initialized_graph):
    apply(service, add_node("Renamed"))
    character = service.config.get_character_by_name("chuchu")
    before = character.model_dump(mode="json")
    saved = service.config._CHARACTERS_CONFIG_PATH.read_bytes()
    with pytest.raises(ValueError, match="unique"):
        rename_owner(service, "RENAMED")
    assert character.model_dump(mode="json") == before
    assert service.config._CHARACTERS_CONFIG_PATH.read_bytes() == saved


def test_query_unknown_owner_raises_error(service):
    with pytest.raises(ValueError, match="Character not found"):
        service.get_relation_graph("Missing")


def test_add_node_custom_person_creates_unconnected_node(service):
    graph = apply(service, add_node("Innkeeper"))
    assert graph["nodes"] == [{"key": "chuchu"}, {"key": "Innkeeper"}]


def test_add_node_does_not_modify_other_owner_graph(service):
    before = service.get_relation_graph("pareo")
    apply(service, add_node("Innkeeper"), owner="chuchu")
    assert service.get_relation_graph("pareo") == before


@pytest.mark.parametrize("key", ["pareo", "PAREO"], ids=["exact", "different-case"])
def test_add_node_duplicate_key_raises_error(service, key):
    apply(service, add_node("pareo"))
    with pytest.raises(ValueError, match="already exists|unique"):
        apply(service, add_node(key))


def test_query_deleted_library_character_preserves_local_node(service):
    apply(service, add_node("pareo"))
    service.config.config.characters[:] = [c for c in service.config.config.characters if c.name != "pareo"]
    assert service.get_relation_graph("chuchu")["nodes"] == [{"key": "chuchu"}, {"key": "pareo"}]


def test_delete_node(service, initialized_graph):
    graph = apply(service, {"op": "delete_node", "key": "pareo"})
    assert graph["nodes"] == [{"key": "chuchu"}, {"key": "lock"}]


def test_delete_node_removes_incident_edges_only(service, initialized_graph):
    unrelated = upsert_edge("chuchu", "lock")["edge"]
    apply(service, {"op": "upsert_edge", "edge": unrelated})
    graph = apply(service, {"op": "delete_node", "key": "pareo"})
    assert graph["edges"] == [{**unrelated, "temperature": 0}]


def test_delete_node_owner_raises_error(service):
    with pytest.raises(ValueError, match="Cannot delete the owner node"):
        apply(service, {"op": "delete_node", "key": "chuchu"}, owner="chuchu")


def test_delete_node_missing_node_raises_error(service):
    with pytest.raises(ValueError, match="Node does not exist"):
        apply(service, {"op": "delete_node", "key": "Missing"}, owner="chuchu")


def test_upsert_edge_new_pair_creates_directed_edge(service):
    graph = apply(service, add_node("pareo"), upsert_edge(temperature=7))
    assert graph["edges"] == [{
        "source": "chuchu", "target": "pareo", "content": "Trusted friend","temperature": 7,
    }]


def test_upsert_edge_content_at_limit_succeeds(service, initialized_graph):
    content = "雪" * 100
    graph = apply(service, upsert_edge(content=content), owner="chuchu")
    assert next(edge for edge in graph["edges"] if edge["source"] == "chuchu")["content"] == content


def test_upsert_edge_content_over_limit_raises_error(service, initialized_graph):
    with pytest.raises(ValueError, match="at most 100"):
        apply(service, upsert_edge(content="雪" * 101), owner="chuchu")


@pytest.mark.parametrize("temperature", [-11, 11, 1.5],
                         ids=["below-minimum", "above-maximum", "fraction"])
def test_upsert_edge_invalid_temperature_raises_error(service, initialized_graph, temperature):
    with pytest.raises(ValueError, match="temperature"):
        apply(service, upsert_edge(temperature=temperature), owner="chuchu")


def test_upsert_edge_existing_pair_replaces_edge(service, initialized_graph):
    graph = apply(service, upsert_edge(temperature=9, content="Updated attitude"))
    assert [e for e in graph["edges"] if e["source"] == "chuchu"] == [{
        "source": "chuchu", "target": "pareo", "temperature": 9, "content": "Updated attitude",
    }]


def test_upsert_edge_preserves_reverse_direction(service, initialized_graph):
    reverse = initialized_graph["incoming"]
    graph = apply(service, upsert_edge(temperature=9))
    assert graph["incoming"] == reverse


def test_upsert_edge_does_not_modify_other_owner_perspective(service, initialized_graph):
    before = service.get_relation_graph("chuchu")
    apply(service, add_node("chuchu"), upsert_edge("pareo", "chuchu", temperature=9), owner="pareo")
    assert service.get_relation_graph("chuchu") == before


@pytest.mark.parametrize("source, target", [("chuchu", "chuchu"), ("pareo", "Missing")],
                         ids=["self-edge", "missing-endpoint"])
def test_upsert_edge_invalid_endpoints_raise_error(service, initialized_graph, source, target):
    with pytest.raises(ValueError, match="endpoints"):
        apply(service, upsert_edge(source, target))


def test_delete_edge_removes_only_requested_direction(service, initialized_graph):
    graph = apply(service, {"op": "delete_edge", "source": "chuchu", "target": "pareo"})
    assert graph["edges"] == initialized_graph["incoming"]


def test_delete_edge_missing_pair_raises_error(service):
    with pytest.raises(ValueError, match="Edge does not exist"):
        apply(service, {"op": "delete_edge", "source": "chuchu", "target": "pareo"})


def test_apply_changes_batch_adds_nodes_and_edges(service):
    graph = apply(
        service,
        add_node("pareo"),
        add_node("lock"),
        upsert_edge("chuchu", "pareo", temperature=7),
        upsert_edge("pareo", "lock", temperature=-2),
        owner="chuchu",
    )
    assert {"nodes": graph["nodes"], "edges": graph["edges"]} == {
        "nodes": [{"key": "chuchu"}, {"key": "pareo"}, {"key": "lock"}],
        "edges": [
            {"source": "chuchu", "target": "pareo", "temperature": 7, "content": "Trusted friend"},
            {"source": "pareo", "target": "lock", "temperature": -2, "content": "Trusted friend"},
        ],
    }


def test_apply_changes_failed_batch_preserves_graph(service, initialized_graph):
    with pytest.raises(ValueError, match="endpoints"):
        apply(service, add_node("New person"), upsert_edge("New person", "Missing"))
    assert service.get_relation_graph("chuchu") == initialized_graph


def test_apply_changes_failed_batch_preserves_saved_file(service, initialized_graph):
    before = service.config._CHARACTERS_CONFIG_PATH.read_bytes()
    with pytest.raises(ValueError, match="endpoints"):
        apply(service, add_node("New person"), upsert_edge("New person", "Missing"))
    assert service.config._CHARACTERS_CONFIG_PATH.read_bytes() == before


def test_apply_operations_failed_batch_preserves_input_graph(initialized_graph):
    original = deepcopy(initialized_graph)
    with pytest.raises(ValueError):
        apply_relation_operations(initialized_graph, [add_node("New person"), upsert_edge("New person", "Missing")])
    assert initialized_graph == original


@pytest.mark.parametrize("operation, message", [
    ({"op": []}, "operation name"),
    ({"op": "unknown"}, "Unknown graph operation"),
    ({"op": "update_node", "node": {"key": "pareo"}}, "Unknown graph operation"),
], ids=["non-text", "unknown", "removed-update-node"])
def test_apply_changes_invalid_operation_raises_error(service, operation, message):
    with pytest.raises(ValueError, match=message):
        apply(service, operation)


def test_apply_changes_save_failure_restores_graph(service, initialized_graph, monkeypatch):
    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(service.config, "save_characters_config", fail_save)
    with pytest.raises(OSError, match="disk full"):
        apply(service, add_node("New person"))
    assert service.get_relation_graph("chuchu") == initialized_graph


def test_apply_changes_persisted_graph_can_be_reloaded(service, initialized_graph):
    data = yaml.safe_load(service.config._CHARACTERS_CONFIG_PATH.read_text(encoding="utf-8"))
    reopened = Character.model_validate(data[0]).relation_graph.model_dump(mode="json", exclude_none=True)
    assert reopened == {field: initialized_graph[field] for field in ("nodes", "edges")}