"""Use cases for reading and editing owner-scoped relationship graphs."""
from copy import deepcopy
from application.characters.management import CharacterUseCase
from config.character_manager import CharacterManager
from config.schema import RelationGraph, RelationNode, RelationEdge

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
    def __init__(self, config, character_manager=None):
        self.config = config
        self.character_manager = character_manager if character_manager is not None else CharacterManager()

    def _resolve_relation_owner(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Owner is required")
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"Character not found: {name}")
        return character.name

    def get_relation_graph(self, owner):
        owner = self._resolve_relation_owner(owner)
        character = self.config.get_character_by_name(owner)
        graph = self.character_manager.parse_relation_graph(character.relation_graph).model_dump(mode="json", exclude_none=True)
        if not graph["nodes"]:
            graph["nodes"] = [{"key": owner}]
        return graph | {"owner": owner}

    def apply_relation_changes(self, owner,operations):
        with CharacterUseCase._mutation_lock:
            owner = self._resolve_relation_owner(owner)

            def mutate(graph):
                if not graph["nodes"]:
                    graph["nodes"] = [{"key": owner}]
                updated = apply_relation_operations(graph | {"owner": owner}, operations)
                updated.pop("owner")
                return updated

            graph = self.character_manager.update_relation_graph(owner,mutate)
            return graph.model_dump(mode="json", exclude_none=True) | {"owner": owner}


def build_relation_use_case(config):
    return CharacterRelationUseCase(config)
