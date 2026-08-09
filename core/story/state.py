"""Immutable runtime state for deterministic story execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .models import StoryVariableDefinition, VariableType


def freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(item) for item in value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    return value


def freeze_mapping(value: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(key): freeze_value(item) for key, item in (value or {}).items()}
    )


def variable_value_is_valid(
    definition: StoryVariableDefinition,
    value: Any,
) -> bool:
    """Return whether a runtime value satisfies its compiled variable contract."""

    if definition.type == VariableType.BOOLEAN:
        return isinstance(value, bool)
    if definition.type == VariableType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return not (
            (definition.minimum is not None and value < definition.minimum)
            or (definition.maximum is not None and value > definition.maximum)
        )
    if definition.type == VariableType.ENUM:
        return isinstance(value, str) and value in definition.enum_values
    if definition.type in {VariableType.STRING_SET, VariableType.NODE_SET}:
        return isinstance(value, frozenset) and all(
            isinstance(item, str) for item in value
        )
    return False


@dataclass(frozen=True, slots=True)
class CanonFact:
    id: str
    text: str
    source_event_id: str


@dataclass(frozen=True, slots=True)
class SemanticSignalState:
    sequence: int = 0
    usage: Mapping[str, int] = field(default_factory=freeze_mapping)
    turn_id: str | None = None
    scene_id: str | None = None
    chapter_id: str | None = None
    recent_fingerprints: tuple[tuple[str, int], ...] = ()
    accepted_cause_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CastState:
    registered_story_character_ids: frozenset[str] = frozenset()
    active_character_ids: tuple[str, ...] = ()
    offstage_character_ids: frozenset[str] = frozenset()
    story_scoped_character_ids: frozenset[str] = frozenset()
    ad_hoc_character_ids: frozenset[str] = frozenset()
    role_bindings: Mapping[str, str] = field(default_factory=freeze_mapping)
    resolved_for_node_id: str | None = None
    cast_revision: int = 0


@dataclass(frozen=True, slots=True)
class StoryState:
    schema_version: int
    story_id: str
    story_version: int
    program_source_hash: str
    revision: int
    current_node_id: str
    variables: Mapping[str, Any]
    completed_node_ids: frozenset[str] = frozenset()
    failed_node_ids: frozenset[str] = frozenset()
    unlocked_node_ids: frozenset[str] = frozenset()
    canon: tuple[CanonFact, ...] = ()
    semantic_signal_state: SemanticSignalState = field(
        default_factory=SemanticSignalState
    )
    cast_state: CastState = field(default_factory=CastState)
    event_cursor: int = 0
