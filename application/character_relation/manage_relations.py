"""Use cases for reading and editing owner-scoped relationship graphs."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from application.characters.management import CharacterUseCase, _CatalogCharacterTarget
from config.character_manager import CharacterManager
from config.character_ops.relations import (
    parse_relation_graph,
    update_character_relation_graph,
)
from config.schema import RelationEdge, RelationGraph, RelationNode

def _add_node(graph, node):
    node = RelationNode.model_validate(node).model_dump(exclude_none=True)
    if any(existing["key"] == node["key"] for existing in graph["nodes"]):
        raise ValueError("Node already exists")
    graph["nodes"].append(node)


def _delete_node(graph, key):
    if key == graph["owner"]:
        raise ValueError("Cannot delete the owner node")
    if not any(node["key"] == key for node in graph["nodes"]):
        raise ValueError("Node does not exist")
    graph["nodes"] = [node for node in graph["nodes"] if node["key"] != key]
    graph["edges"] = [edge for edge in graph["edges"] if key not in (edge["source"], edge["target"])]


def _upsert_edge(graph, edge):
    edge = RelationEdge.model_validate(edge).model_dump()
    graph["edges"] = [existing for existing in graph["edges"]
                      if (existing["source"], existing["target"]) != (edge["source"], edge["target"])]
    graph["edges"].append(edge)


def _delete_edge(graph, source, target):
    pair = (source, target)
    if not any((edge["source"], edge["target"]) == pair for edge in graph["edges"]):
        raise ValueError("Edge does not exist")
    graph["edges"] = [edge for edge in graph["edges"] if (edge["source"], edge["target"]) != pair]


def apply_relation_operations(graph, requests):
    if not isinstance(requests, list) or not requests or len(requests) > 1000:
        raise ValueError("Provide between 1 and 1000 graph operations")
    value = deepcopy(graph)
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError("Invalid graph operation")
        operation = request.get("op")
        if not isinstance(operation, str):
            raise ValueError("Graph operation name must be text")
        if operation == "add_node":
            _add_node(value, request.get("node"))
        elif operation == "delete_node":
            _delete_node(value, request.get("key"))
        elif operation == "upsert_edge":
            _upsert_edge(value, request.get("edge"))
        elif operation == "delete_edge":
            _delete_edge(value, request.get("source"), request.get("target"))
        else:
            raise ValueError("Unknown graph operation")
    owner = value.pop("owner")
    return RelationGraph.model_validate(value).model_dump(exclude_none=True) | {"owner": owner}


class CharacterRelationUseCase:
    def __init__(self, config, character_manager=None, *, characters: Any = None):
        self.config = config
        self._characters = characters
        if character_manager is None and characters is None:
            self.character_manager = CharacterManager()
        else:
            self.character_manager = character_manager

    def _get_character(self, name: str):
        if self._characters is not None:
            return self._characters.get_by_name(name)
        return self.config.get_character_by_name(name)

    def _resolve_relation_owner(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Owner is required")
        character = self._get_character(name)
        if character is None:
            raise ValueError(f"Character not found: {name}")
        return character.name

    def get_relation_graph(self, owner):
        owner = self._resolve_relation_owner(owner)
        character = self._get_character(owner)
        parser = (
            self.character_manager.parse_relation_graph
            if self.character_manager is not None
            else parse_relation_graph
        )
        graph = parser(character.relation_graph).model_dump(mode="json", exclude_none=True)
        if not graph["nodes"]:
            graph["nodes"] = [{"key": owner}]
        return graph | {"owner": owner}

    def apply_relation_changes(self, owner, operations):
        with CharacterUseCase._mutation_lock:
            owner = self._resolve_relation_owner(owner)

            def mutate(graph):
                if not graph["nodes"]:
                    graph["nodes"] = [{"key": owner}]
                updated = apply_relation_operations(graph | {"owner": owner}, operations)
                updated.pop("owner")
                return updated

            if self._characters is not None:
                graph = update_character_relation_graph(_CatalogCharacterTarget(self._characters), owner, mutate)
                refresh = getattr(self.config, "refresh_characters", None)
                if callable(refresh):
                    refresh()
            else:
                graph = self.character_manager.update_relation_graph(owner, mutate)
            return graph.model_dump(mode="json", exclude_none=True) | {"owner": owner}


def build_relation_use_case(config, *, characters: Any = None):
    return CharacterRelationUseCase(config, characters=characters)
