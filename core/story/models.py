"""Immutable authoring and compiled models for Shinsekai stories."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .semantic import SemanticSignalDefinition


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class FrozenDict(Mapping[Any, Any]):
    """A recursively copied, read-only mapping used by immutable story models."""

    __slots__ = ("_data",)

    def __init__(self, source: Mapping[Any, Any] | None = None) -> None:
        frozen = {key: _freeze_value(value) for key, value in (source or {}).items()}
        self._data = MappingProxyType(frozen)

    def __getitem__(self, key: Any) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"


def _freeze_value(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


class VariableType(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    ENUM = "enum"
    STRING_SET = "string_set"
    NODE_SET = "node_set"


class VariableScope(str, Enum):
    BRANCH = "branch"
    GLOBAL = "global"


class CharacterSourceType(str, Enum):
    LOCAL_LIBRARY = "local-library"
    EMBEDDED = "embedded"
    USER_IMPORTED = "user-imported"
    AUTHOR_GENERATED = "author-generated"


class CastMode(str, Enum):
    FIXED = "fixed"
    MIXED = "mixed"
    ROLE_BASED = "role-based"
    DYNAMIC = "dynamic"


class Commitment(str, Enum):
    DRAFT = "draft"
    COMMITTED = "committed"
    FROZEN = "frozen"


class PortType(str, Enum):
    ANY = "Any"
    BOOLEAN = "Boolean"
    INTEGER = "Integer"
    STRING = "String"
    STORY_EVENT = "StoryEvent"
    SEMANTIC_SIGNAL_EVENT = "SemanticSignalEvent"
    EFFECT = "Effect"
    NODE_UNLOCKED_EVENT = "NodeUnlockedEvent"
    NODE_ENTERED_EVENT = "NodeEnteredEvent"
    CHARACTER_READY_EVENT = "CharacterReadyEvent"
    CAST_RESOLVED_EVENT = "CastResolvedEvent"
    CAST_CHANGED_EVENT = "CastChangedEvent"
    RESOURCE_LIFECYCLE_CUE = "ResourceLifecycleCue"
    PRESENTATION_CUE = "PresentationCue"


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    op: str
    args: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "args", tuple(_freeze_value(item) for item in self.args)
        )


@dataclass(frozen=True, slots=True)
class CandidateConditionSpec:
    op: str
    args: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "args", tuple(_freeze_value(item) for item in self.args)
        )


@dataclass(frozen=True, slots=True)
class EffectSpec:
    op: str
    args: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "args", tuple(_freeze_value(item) for item in self.args)
        )


@dataclass(frozen=True, slots=True)
class StoryVariableDefinition:
    id: str
    type: VariableType
    initial: Any
    scope: VariableScope = VariableScope.BRANCH
    visible: bool = False
    minimum: int | None = None
    maximum: int | None = None
    enum_values: tuple[str, ...] = ()
    allow_semantic_input: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial", _freeze_value(self.initial))


@dataclass(frozen=True, slots=True)
class CharacterSource:
    type: CharacterSourceType
    character_id: str | None = None
    path: str | None = None
    revision: str | None = None
    content_digest: str | None = None


@dataclass(frozen=True, slots=True)
class CharacterDefinition:
    id: str
    source: CharacterSource
    tags: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    priority: int = 0


@dataclass(frozen=True, slots=True)
class CastDefaults:
    max_active: int = 8
    preserve_current_cast: bool = True


@dataclass(frozen=True, slots=True)
class AdHocPolicy:
    enabled: bool = False
    max_per_scene: int = 0
    persist_scope: VariableScope = VariableScope.BRANCH
    require_promotion_for_reuse: bool = True


@dataclass(frozen=True, slots=True)
class CharacterRegistry:
    characters: tuple[CharacterDefinition, ...] = ()
    initial_cast: tuple[str, ...] = ()
    defaults: CastDefaults = field(default_factory=CastDefaults)
    ad_hoc_policy: AdHocPolicy = field(default_factory=AdHocPolicy)

    @property
    def by_id(self) -> Mapping[str, CharacterDefinition]:
        return {character.id: character for character in self.characters}


@dataclass(frozen=True, slots=True)
class RequiredRole:
    role: str
    count: int = 1
    prefer: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateQuery:
    any_tags: tuple[str, ...] = ()
    all_tags: tuple[str, ...] = ()
    conditions: tuple[CandidateConditionSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class CastConstraints:
    min_active: int = 0
    max_active: int = 8
    preserve_current_cast: bool = True
    require_loaded_assets: bool = False


@dataclass(frozen=True, slots=True)
class CastSelection:
    strategy: str = "continuity-then-priority"
    allow_ai_proposal: bool = False


@dataclass(frozen=True, slots=True)
class CastFallback:
    on_missing_role: str = "error"
    on_load_failure: str = "error"


@dataclass(frozen=True, slots=True)
class CastPolicy:
    mode: CastMode = CastMode.FIXED
    required: tuple[str, ...] = ()
    required_roles: tuple[RequiredRole, ...] = ()
    optional_query: CandidateQuery = field(default_factory=CandidateQuery)
    forbidden: tuple[str, ...] = ()
    constraints: CastConstraints = field(default_factory=CastConstraints)
    selection: CastSelection = field(default_factory=CastSelection)
    fallback: CastFallback = field(default_factory=CastFallback)


@dataclass(frozen=True, slots=True)
class StoryChoice:
    id: str
    label: str
    when: ConditionSpec = field(default_factory=lambda: ConditionSpec("true"))
    effects: tuple[EffectSpec, ...] = ()
    goto: str | None = None


@dataclass(frozen=True, slots=True)
class FreeformIntent:
    id: str
    examples: tuple[str, ...] = ()
    when: ConditionSpec = field(default_factory=lambda: ConditionSpec("true"))
    effects: tuple[EffectSpec, ...] = ()
    result_beat: str = ""


@dataclass(frozen=True, slots=True)
class StoryNode:
    id: str
    title: str
    type: str = "story"
    chapter_id: str | None = None
    commitment: Commitment = Commitment.DRAFT
    enter_when: ConditionSpec = field(default_factory=lambda: ConditionSpec("true"))
    on_enter: tuple[EffectSpec, ...] = ()
    choices: tuple[StoryChoice, ...] = ()
    freeform_intents: tuple[FreeformIntent, ...] = ()
    cast_policy: CastPolicy = field(default_factory=CastPolicy)
    exposed_context: Mapping[str, Any] = field(default_factory=dict)
    locked_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "exposed_context", FrozenDict(self.exposed_context))
        object.__setattr__(self, "locked_context", FrozenDict(self.locked_context))


@dataclass(frozen=True, slots=True)
class NarrativeGraph:
    start_node_id: str
    nodes: tuple[StoryNode, ...]

    @property
    def by_id(self) -> Mapping[str, StoryNode]:
        return {node.id: node for node in self.nodes}


@dataclass(frozen=True, slots=True)
class PortRef:
    node_id: str
    port: str


@dataclass(frozen=True, slots=True)
class RuleNode:
    id: str
    type: str
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", FrozenDict(self.config))


@dataclass(frozen=True, slots=True)
class RuleEdge:
    source: PortRef
    target: PortRef


@dataclass(frozen=True, slots=True)
class RuleGraph:
    version: int = 1
    nodes: tuple[RuleNode, ...] = ()
    edges: tuple[RuleEdge, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))

    @property
    def by_id(self) -> Mapping[str, RuleNode]:
        return {node.id: node for node in self.nodes}


@dataclass(frozen=True, slots=True)
class StoryMetadata:
    language: str = "zh-CN"
    estimated_minutes: int | None = None
    generation_mode: str = "manual"
    resource_bindings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_bindings", FrozenDict(self.resource_bindings)
        )


@dataclass(frozen=True, slots=True)
class StoryProject:
    schema_version: int
    id: str
    version: int
    title: str
    status: str
    metadata: StoryMetadata
    variables: tuple[StoryVariableDefinition, ...]
    semantic_signals: tuple[SemanticSignalDefinition, ...]
    character_registry: CharacterRegistry
    narrative_graph: NarrativeGraph
    rule_graph: RuleGraph

    @property
    def variables_by_id(self) -> Mapping[str, StoryVariableDefinition]:
        return {variable.id: variable for variable in self.variables}

    @property
    def semantic_signals_by_id(self) -> Mapping[str, SemanticSignalDefinition]:
        return {definition.id: definition for definition in self.semantic_signals}


@dataclass(frozen=True, slots=True)
class PortSchema:
    type: PortType
    required: bool = False
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class RuleNodeSchema:
    inputs: Mapping[str, PortSchema] = field(default_factory=dict)
    outputs: Mapping[str, PortSchema] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", FrozenDict(self.inputs))
        object.__setattr__(self, "outputs", FrozenDict(self.outputs))


@dataclass(frozen=True, slots=True)
class CompiledStoryNode:
    id: str
    title: str
    type: str
    enter_when: ConditionSpec
    on_enter: tuple[EffectSpec, ...]
    choices: tuple[StoryChoice, ...]
    freeform_intents: tuple[FreeformIntent, ...]
    cast_policy: CastPolicy
    exposed_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "exposed_context", FrozenDict(self.exposed_context))


@dataclass(frozen=True, slots=True)
class StoryProgram:
    schema_version: int
    story_id: str
    story_version: int
    source_hash: str
    start_node_id: str
    variables: tuple[StoryVariableDefinition, ...]
    semantic_signals: tuple[SemanticSignalDefinition, ...]
    character_registry: CharacterRegistry
    nodes: tuple[CompiledStoryNode, ...]
    rule_graph: RuleGraph
    source_map: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_map", FrozenDict(self.source_map))

    @property
    def nodes_by_id(self) -> Mapping[str, CompiledStoryNode]:
        return {node.id: node for node in self.nodes}

    @property
    def variables_by_id(self) -> Mapping[str, StoryVariableDefinition]:
        return {variable.id: variable for variable in self.variables}

    @property
    def semantic_signals_by_id(self) -> Mapping[str, SemanticSignalDefinition]:
        return {definition.id: definition for definition in self.semantic_signals}
