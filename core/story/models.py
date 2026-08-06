"""Immutable authoring and compiled models for Shinsekai stories."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


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


@dataclass(frozen=True, slots=True)
class EffectSpec:
    op: str
    args: tuple[Any, ...] = ()


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


@dataclass(frozen=True, slots=True)
class CharacterSource:
    type: CharacterSourceType
    character_id: str | None = None
    path: str | None = None
    revision: str | None = None


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
    conditions: tuple[ConditionSpec, ...] = ()


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


@dataclass(frozen=True, slots=True)
class RuleEdge:
    source: PortRef
    target: PortRef


@dataclass(frozen=True, slots=True)
class RuleGraph:
    version: int = 1
    nodes: tuple[RuleNode, ...] = ()
    edges: tuple[RuleEdge, ...] = ()

    @property
    def by_id(self) -> Mapping[str, RuleNode]:
        return {node.id: node for node in self.nodes}


@dataclass(frozen=True, slots=True)
class StoryMetadata:
    language: str = "zh-CN"
    estimated_minutes: int | None = None
    generation_mode: str = "manual"


@dataclass(frozen=True, slots=True)
class StoryProject:
    schema_version: int
    id: str
    version: int
    title: str
    status: str
    metadata: StoryMetadata
    variables: tuple[StoryVariableDefinition, ...]
    character_registry: CharacterRegistry
    narrative_graph: NarrativeGraph
    rule_graph: RuleGraph

    @property
    def variables_by_id(self) -> Mapping[str, StoryVariableDefinition]:
        return {variable.id: variable for variable in self.variables}


@dataclass(frozen=True, slots=True)
class PortSchema:
    type: PortType
    required: bool = False
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class RuleNodeSchema:
    inputs: Mapping[str, PortSchema] = field(default_factory=dict)
    outputs: Mapping[str, PortSchema] = field(default_factory=dict)


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


@dataclass(frozen=True, slots=True)
class StoryProgram:
    schema_version: int
    story_id: str
    story_version: int
    source_hash: str
    start_node_id: str
    variables: tuple[StoryVariableDefinition, ...]
    character_registry: CharacterRegistry
    nodes: tuple[CompiledStoryNode, ...]
    rule_graph: RuleGraph
    source_map: Mapping[str, str]

    @property
    def nodes_by_id(self) -> Mapping[str, CompiledStoryNode]:
        return {node.id: node for node in self.nodes}
