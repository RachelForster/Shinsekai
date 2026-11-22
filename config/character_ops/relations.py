"""Relation-graph parsing and owner-scoped mutation operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from config.character_ops.target import CharacterPersistenceTarget, _with_character_lock
from config.schema import Character, RelationGraph


def parse_relation_graph(
    data: RelationGraph | Mapping[str, Any] | None = None,
) -> RelationGraph:
    """Parse a relation graph payload or return an independent empty graph."""
    if isinstance(data, RelationGraph):
        data = data.model_dump(mode="json")
    return RelationGraph.model_validate(deepcopy(data) if data is not None else {})


def rename_relation_graph_owner(
    graph: RelationGraph | Mapping[str, Any],
    old_name: str,
    new_name: str,
) -> RelationGraph:
    """Update node and edge owner references inside a character's relation graph."""
    parsed = graph if isinstance(graph, RelationGraph) else parse_relation_graph(graph)
    if not old_name or old_name == new_name:
        return parsed.model_copy(deep=True)
    value = parsed.model_dump(mode="json")
    for node in value["nodes"]:
        if node["key"] == old_name:
            node["key"] = new_name
    for edge in value["edges"]:
        for endpoint in ("source", "target"):
            if edge[endpoint] == old_name:
                edge[endpoint] = new_name
    return RelationGraph.model_validate(value)


def rename_references_in_other_graphs(
    characters: Sequence[Character],
    *,
    renamed_id: str,
    old_name: str,
    new_name: str,
) -> list[Character]:
    """Prepare and validate renamed references without persisting changes."""
    updated = []
    for character in characters:
        if character.id == renamed_id:
            continue
        graph = rename_relation_graph_owner(character.relation_graph, old_name, new_name)
        if graph != character.relation_graph:
            updated.append(character.model_copy(update={"relation_graph": graph}))
    return updated


@_with_character_lock
def update_character_relation_graph(
    target: CharacterPersistenceTarget,
    char_name: str,
    mutate: Callable[[dict[str, Any]], Any],
) -> RelationGraph:
    """Apply a mutator to ``char_name``'s relation graph, validate, and persist."""
    character = target.get_by_name(char_name)
    if character is None:
        raise ValueError(f"Character not found: {char_name}")
    current_graph = character.relation_graph
    updated = parse_relation_graph(mutate(current_graph.model_dump(mode="json")))
    next_character = character.model_copy(update={"relation_graph": updated})
    target.save_character(next_character)
    return updated.model_copy(deep=True)


__all__ = [
    "parse_relation_graph",
    "rename_relation_graph_owner",
    "update_character_relation_graph",
]
