"""Safe story source loading and normalization into immutable domain models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re
from typing import Any, TypeVar

import yaml

from .diagnostics import StoryDiagnostic, StoryValidationError
from .models import (
    AdHocPolicy,
    CandidateQuery,
    CastConstraints,
    CastDefaults,
    CastFallback,
    CastMode,
    CastPolicy,
    CastSelection,
    CharacterDefinition,
    CharacterRegistry,
    CharacterSource,
    CharacterSourceType,
    Commitment,
    ConditionSpec,
    EffectSpec,
    FreeformIntent,
    NarrativeGraph,
    PortRef,
    RequiredRole,
    RuleEdge,
    RuleGraph,
    RuleNode,
    StoryChoice,
    StoryMetadata,
    StoryNode,
    StoryProject,
    StoryVariableDefinition,
    VariableScope,
    VariableType,
)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_E = TypeVar("_E")


class _Parser:
    def __init__(self) -> None:
        self.diagnostics: list[StoryDiagnostic] = []

    def error(self, code: str, message: str, path: str) -> None:
        self.diagnostics.append(StoryDiagnostic(code=code, message=message, path=path))

    def mapping(self, value: Any, path: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            self.error("schema.type", "expected an object", path)
            return {}
        return value

    def sequence(self, value: Any, path: str) -> Sequence[Any]:
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return value
        self.error("schema.type", "expected a list", path)
        return ()

    def string(
        self,
        value: Any,
        path: str,
        *,
        default: str = "",
        required: bool = False,
    ) -> str:
        if value is None and not required:
            return default
        if not isinstance(value, str) or (required and not value.strip()):
            self.error("schema.string", "expected a non-empty string", path)
            return default
        return value

    def story_id(self, value: Any, path: str) -> str:
        result = self.string(value, path, required=True)
        if result and not _ID_RE.fullmatch(result):
            self.error(
                "schema.id",
                "must match ^[a-z0-9][a-z0-9._-]{0,127}$",
                path,
            )
        return result

    def integer(
        self,
        value: Any,
        path: str,
        *,
        default: int = 0,
        minimum: int | None = None,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            self.error("schema.integer", "expected an integer", path)
            return default
        if minimum is not None and value < minimum:
            self.error("schema.range", f"must be at least {minimum}", path)
            return default
        return value

    def boolean(self, value: Any, path: str, *, default: bool = False) -> bool:
        if value is None:
            return default
        if not isinstance(value, bool):
            self.error("schema.boolean", "expected a boolean", path)
            return default
        return value

    def enum(self, enum_type: type[_E], value: Any, path: str, *, default: _E) -> _E:
        try:
            return enum_type(value)  # type: ignore[call-arg,return-value]
        except (TypeError, ValueError):
            allowed = ", ".join(member.value for member in enum_type)  # type: ignore[attr-defined]
            self.error("schema.enum", f"expected one of: {allowed}", path)
            return default

    def strings(self, value: Any, path: str) -> tuple[str, ...]:
        if value is None:
            return ()
        items = self.sequence(value, path)
        result: list[str] = []
        for index, item in enumerate(items):
            parsed = self.string(item, f"{path}[{index}]", required=True)
            if parsed:
                result.append(parsed)
        return tuple(result)

    def unique_ids(self, values: Sequence[Any], path: str) -> None:
        seen: dict[str, int] = {}
        for index, value in enumerate(values):
            item = self.mapping(value, f"{path}[{index}]")
            identifier = item.get("id")
            if not isinstance(identifier, str):
                continue
            if identifier in seen:
                self.error(
                    "schema.duplicate_id",
                    f"duplicate id {identifier!r}; first declared at index {seen[identifier]}",
                    f"{path}[{index}].id",
                )
            else:
                seen[identifier] = index


def _parse_condition(parser: _Parser, value: Any, path: str) -> ConditionSpec:
    if value is None or value is True:
        return ConditionSpec("true")
    if value is False:
        return ConditionSpec("false")
    source = parser.mapping(value, path)
    if len(source) != 1:
        parser.error(
            "condition.shape", "condition must contain exactly one operator", path
        )
        return ConditionSpec("false")
    op, raw_args = next(iter(source.items()), ("false", None))
    if op in {"all", "any"}:
        children = tuple(
            _parse_condition(parser, item, f"{path}.{op}[{index}]")
            for index, item in enumerate(parser.sequence(raw_args, f"{path}.{op}"))
        )
        return ConditionSpec(op, children)
    if op == "not":
        return ConditionSpec(
            "not", (_parse_condition(parser, raw_args, f"{path}.not"),)
        )
    if op in {"completed", "flag", "available", "alive", "sameLocationAs"}:
        return ConditionSpec(
            op, (parser.string(raw_args, f"{path}.{op}", required=True),)
        )
    if op in {"equals", "gte", "lte", "contains"}:
        args = parser.sequence(raw_args, f"{path}.{op}")
        if len(args) != 2:
            parser.error(
                "condition.arity", f"{op} requires two arguments", f"{path}.{op}"
            )
            return ConditionSpec("false")
        return ConditionSpec(op, (args[0], args[1]))
    parser.error("condition.operator", f"unsupported condition operator {op!r}", path)
    return ConditionSpec("false")


def _parse_effect(parser: _Parser, value: Any, path: str) -> EffectSpec:
    source = parser.mapping(value, path)
    if len(source) != 1:
        parser.error("effect.shape", "effect must contain exactly one operator", path)
        return EffectSpec("noop")
    op, raw_args = next(iter(source.items()), ("noop", None))
    aliases = {
        "appendCanon": "append-canon",
        "addSet": "add-set",
        "removeSet": "remove-set",
    }
    normalized_op = aliases.get(op, op)
    if normalized_op in {"set", "increment", "add-set", "remove-set"}:
        args = parser.sequence(raw_args, f"{path}.{op}")
        if len(args) != 2:
            parser.error("effect.arity", f"{op} requires two arguments", f"{path}.{op}")
            return EffectSpec("noop")
        return EffectSpec(normalized_op, (args[0], args[1]))
    if normalized_op in {"append-canon", "unlock"}:
        return EffectSpec(normalized_op, (raw_args,))
    parser.error("effect.operator", f"unsupported effect operator {op!r}", path)
    return EffectSpec("noop")


def _parse_variable(
    parser: _Parser,
    identifier: str,
    value: Any,
    path: str,
) -> StoryVariableDefinition:
    source = parser.mapping(value, path)
    variable_type = parser.enum(
        VariableType,
        source.get("type"),
        f"{path}.type",
        default=VariableType.BOOLEAN,
    )
    scope = parser.enum(
        VariableScope,
        source.get("scope", VariableScope.BRANCH.value),
        f"{path}.scope",
        default=VariableScope.BRANCH,
    )
    initial = source.get("initial")
    if initial is None:
        initial = {
            VariableType.BOOLEAN: False,
            VariableType.INTEGER: 0,
            VariableType.ENUM: "",
            VariableType.STRING_SET: [],
            VariableType.NODE_SET: [],
        }[variable_type]
    if variable_type in {VariableType.STRING_SET, VariableType.NODE_SET}:
        initial = parser.strings(initial, f"{path}.initial")
    minimum = source.get("min")
    maximum = source.get("max")
    if minimum is not None and (
        isinstance(minimum, bool) or not isinstance(minimum, int)
    ):
        parser.error("variable.bound", "min must be an integer", f"{path}.min")
        minimum = None
    if maximum is not None and (
        isinstance(maximum, bool) or not isinstance(maximum, int)
    ):
        parser.error("variable.bound", "max must be an integer", f"{path}.max")
        maximum = None
    return StoryVariableDefinition(
        id=parser.story_id(identifier, f"{path}.id"),
        type=variable_type,
        initial=initial,
        scope=scope,
        visible=parser.boolean(source.get("visible"), f"{path}.visible"),
        minimum=minimum,
        maximum=maximum,
        enum_values=parser.strings(source.get("values"), f"{path}.values"),
        allow_semantic_input=parser.boolean(
            source.get("allowSemanticInput"),
            f"{path}.allowSemanticInput",
        ),
    )


def _parse_character_source(parser: _Parser, value: Any, path: str) -> CharacterSource:
    source = parser.mapping(value, path)
    source_type = parser.enum(
        CharacterSourceType,
        source.get("type"),
        f"{path}.type",
        default=CharacterSourceType.EMBEDDED,
    )
    return CharacterSource(
        type=source_type,
        character_id=(
            parser.string(
                source.get("characterId"), f"{path}.characterId", required=True
            )
            if source_type == CharacterSourceType.LOCAL_LIBRARY
            else None
        ),
        path=(
            parser.string(source.get("path"), f"{path}.path", required=True)
            if source_type
            in {
                CharacterSourceType.EMBEDDED,
                CharacterSourceType.USER_IMPORTED,
                CharacterSourceType.AUTHOR_GENERATED,
            }
            else None
        ),
        revision=parser.string(source.get("revision"), f"{path}.revision") or None,
    )


def _parse_registry(parser: _Parser, value: Any, path: str) -> CharacterRegistry:
    source = parser.mapping(value or {}, path)
    raw_characters = parser.sequence(source.get("characters", ()), f"{path}.characters")
    parser.unique_ids(raw_characters, f"{path}.characters")
    characters: list[CharacterDefinition] = []
    for index, raw_character in enumerate(raw_characters):
        item_path = f"{path}.characters[{index}]"
        item = parser.mapping(raw_character, item_path)
        characters.append(
            CharacterDefinition(
                id=parser.story_id(item.get("id"), f"{item_path}.id"),
                source=_parse_character_source(
                    parser, item.get("source"), f"{item_path}.source"
                ),
                tags=parser.strings(item.get("tags"), f"{item_path}.tags"),
                roles=parser.strings(item.get("roles"), f"{item_path}.roles"),
                priority=parser.integer(
                    item.get("priority", 0), f"{item_path}.priority"
                ),
            )
        )
    defaults_source = parser.mapping(source.get("defaults", {}), f"{path}.defaults")
    ad_hoc_source = parser.mapping(source.get("adHocPolicy", {}), f"{path}.adHocPolicy")
    return CharacterRegistry(
        characters=tuple(characters),
        initial_cast=parser.strings(source.get("initialCast"), f"{path}.initialCast"),
        defaults=CastDefaults(
            max_active=parser.integer(
                defaults_source.get("maxActive", 8),
                f"{path}.defaults.maxActive",
                minimum=1,
                default=8,
            ),
            preserve_current_cast=parser.boolean(
                defaults_source.get("preserveCurrentCast"),
                f"{path}.defaults.preserveCurrentCast",
                default=True,
            ),
        ),
        ad_hoc_policy=AdHocPolicy(
            enabled=parser.boolean(
                ad_hoc_source.get("enabled"), f"{path}.adHocPolicy.enabled"
            ),
            max_per_scene=parser.integer(
                ad_hoc_source.get("maxPerScene", 0),
                f"{path}.adHocPolicy.maxPerScene",
                minimum=0,
            ),
            persist_scope=parser.enum(
                VariableScope,
                ad_hoc_source.get("persistScope", VariableScope.BRANCH.value),
                f"{path}.adHocPolicy.persistScope",
                default=VariableScope.BRANCH,
            ),
            require_promotion_for_reuse=parser.boolean(
                ad_hoc_source.get("requirePromotionForReuse"),
                f"{path}.adHocPolicy.requirePromotionForReuse",
                default=True,
            ),
        ),
    )


def _parse_cast_policy(
    parser: _Parser, value: Any, path: str, default_max: int
) -> CastPolicy:
    source = parser.mapping(value or {}, path)
    raw_roles = parser.sequence(
        source.get("requiredRoles", ()), f"{path}.requiredRoles"
    )
    roles: list[RequiredRole] = []
    for index, raw_role in enumerate(raw_roles):
        item_path = f"{path}.requiredRoles[{index}]"
        item = parser.mapping(raw_role, item_path)
        roles.append(
            RequiredRole(
                role=parser.string(
                    item.get("role"), f"{item_path}.role", required=True
                ),
                count=parser.integer(
                    item.get("count", 1), f"{item_path}.count", minimum=1, default=1
                ),
                prefer=parser.strings(item.get("prefer"), f"{item_path}.prefer"),
            )
        )
    query_source = parser.mapping(
        source.get("optionalQuery", {}), f"{path}.optionalQuery"
    )
    raw_conditions = query_source.get("allConditions", ())
    conditions = tuple(
        _parse_condition(parser, item, f"{path}.optionalQuery.allConditions[{index}]")
        for index, item in enumerate(
            parser.sequence(raw_conditions, f"{path}.optionalQuery.allConditions")
        )
    )
    constraint_source = parser.mapping(
        source.get("constraints", {}), f"{path}.constraints"
    )
    selection_source = parser.mapping(source.get("selection", {}), f"{path}.selection")
    fallback_source = parser.mapping(source.get("fallback", {}), f"{path}.fallback")
    return CastPolicy(
        mode=parser.enum(
            CastMode,
            source.get("mode", CastMode.FIXED.value),
            f"{path}.mode",
            default=CastMode.FIXED,
        ),
        required=parser.strings(source.get("required"), f"{path}.required"),
        required_roles=tuple(roles),
        optional_query=CandidateQuery(
            any_tags=parser.strings(
                query_source.get("anyTags"), f"{path}.optionalQuery.anyTags"
            ),
            all_tags=parser.strings(
                query_source.get("allTags"), f"{path}.optionalQuery.allTags"
            ),
            conditions=conditions,
        ),
        forbidden=parser.strings(source.get("forbidden"), f"{path}.forbidden"),
        constraints=CastConstraints(
            min_active=parser.integer(
                constraint_source.get("minActive", 0),
                f"{path}.constraints.minActive",
                minimum=0,
            ),
            max_active=parser.integer(
                constraint_source.get("maxActive", default_max),
                f"{path}.constraints.maxActive",
                minimum=1,
                default=default_max,
            ),
            preserve_current_cast=parser.boolean(
                constraint_source.get("preserveCurrentCast"),
                f"{path}.constraints.preserveCurrentCast",
                default=True,
            ),
            require_loaded_assets=parser.boolean(
                constraint_source.get("requireLoadedAssets"),
                f"{path}.constraints.requireLoadedAssets",
            ),
        ),
        selection=CastSelection(
            strategy=parser.string(
                selection_source.get("strategy"),
                f"{path}.selection.strategy",
                default="continuity-then-priority",
            ),
            allow_ai_proposal=parser.boolean(
                selection_source.get("allowAiProposal"),
                f"{path}.selection.allowAiProposal",
            ),
        ),
        fallback=CastFallback(
            on_missing_role=parser.string(
                fallback_source.get("onMissingRole"),
                f"{path}.fallback.onMissingRole",
                default="error",
            ),
            on_load_failure=parser.string(
                fallback_source.get("onLoadFailure"),
                f"{path}.fallback.onLoadFailure",
                default="error",
            ),
        ),
    )


def _parse_choice(parser: _Parser, value: Any, path: str) -> StoryChoice:
    source = parser.mapping(value, path)
    return StoryChoice(
        id=parser.story_id(source.get("id"), f"{path}.id"),
        label=parser.string(source.get("label"), f"{path}.label", required=True),
        when=_parse_condition(parser, source.get("when", True), f"{path}.when"),
        effects=tuple(
            _parse_effect(parser, effect, f"{path}.effects[{index}]")
            for index, effect in enumerate(
                parser.sequence(source.get("effects", ()), f"{path}.effects")
            )
        ),
        goto=parser.string(source.get("goto"), f"{path}.goto") or None,
    )


def _parse_intent(parser: _Parser, value: Any, path: str) -> FreeformIntent:
    source = parser.mapping(value, path)
    return FreeformIntent(
        id=parser.story_id(source.get("id"), f"{path}.id"),
        examples=parser.strings(source.get("examples"), f"{path}.examples"),
        when=_parse_condition(parser, source.get("when", True), f"{path}.when"),
        effects=tuple(
            _parse_effect(parser, effect, f"{path}.effects[{index}]")
            for index, effect in enumerate(
                parser.sequence(source.get("effects", ()), f"{path}.effects")
            )
        ),
        result_beat=parser.string(source.get("resultBeat"), f"{path}.resultBeat"),
    )


def _parse_narrative_graph(
    parser: _Parser,
    value: Any,
    path: str,
    *,
    fallback_start_node_id: str,
    default_max_cast: int,
) -> NarrativeGraph:
    source = parser.mapping(value, path)
    raw_nodes = parser.sequence(source.get("nodes", ()), f"{path}.nodes")
    parser.unique_ids(raw_nodes, f"{path}.nodes")
    nodes: list[StoryNode] = []
    for index, raw_node in enumerate(raw_nodes):
        item_path = f"{path}.nodes[{index}]"
        item = parser.mapping(raw_node, item_path)
        raw_choices = parser.sequence(item.get("choices", ()), f"{item_path}.choices")
        raw_intents = parser.sequence(
            item.get("freeformIntents", ()),
            f"{item_path}.freeformIntents",
        )
        parser.unique_ids(raw_choices, f"{item_path}.choices")
        parser.unique_ids(raw_intents, f"{item_path}.freeformIntents")
        nodes.append(
            StoryNode(
                id=parser.story_id(item.get("id"), f"{item_path}.id"),
                title=parser.string(
                    item.get("title"), f"{item_path}.title", required=True
                ),
                type=parser.string(
                    item.get("type"), f"{item_path}.type", default="story"
                ),
                chapter_id=parser.string(
                    item.get("chapterId"), f"{item_path}.chapterId"
                )
                or None,
                commitment=parser.enum(
                    Commitment,
                    item.get("commitment", Commitment.DRAFT.value),
                    f"{item_path}.commitment",
                    default=Commitment.DRAFT,
                ),
                enter_when=_parse_condition(
                    parser,
                    item.get("enterWhen", True),
                    f"{item_path}.enterWhen",
                ),
                on_enter=tuple(
                    _parse_effect(
                        parser, effect, f"{item_path}.onEnter[{effect_index}]"
                    )
                    for effect_index, effect in enumerate(
                        parser.sequence(item.get("onEnter", ()), f"{item_path}.onEnter")
                    )
                ),
                choices=tuple(
                    _parse_choice(
                        parser, choice, f"{item_path}.choices[{choice_index}]"
                    )
                    for choice_index, choice in enumerate(raw_choices)
                ),
                freeform_intents=tuple(
                    _parse_intent(
                        parser,
                        intent,
                        f"{item_path}.freeformIntents[{intent_index}]",
                    )
                    for intent_index, intent in enumerate(raw_intents)
                ),
                cast_policy=_parse_cast_policy(
                    parser,
                    item.get("castPolicy"),
                    f"{item_path}.castPolicy",
                    default_max_cast,
                ),
                exposed_context=dict(
                    parser.mapping(
                        item.get("exposedContext", {}), f"{item_path}.exposedContext"
                    )
                ),
                locked_context=dict(
                    parser.mapping(
                        item.get("lockedContext", {}), f"{item_path}.lockedContext"
                    )
                ),
            )
        )
    start_node_id = parser.story_id(
        source.get("startNodeId", fallback_start_node_id),
        f"{path}.startNodeId",
    )
    return NarrativeGraph(start_node_id=start_node_id, nodes=tuple(nodes))


def _parse_rule_graph(parser: _Parser, value: Any, path: str) -> RuleGraph:
    source = parser.mapping(value or {}, path)
    raw_nodes = parser.sequence(source.get("nodes", ()), f"{path}.nodes")
    raw_edges = parser.sequence(source.get("edges", ()), f"{path}.edges")
    parser.unique_ids(raw_nodes, f"{path}.nodes")
    nodes: list[RuleNode] = []
    for index, raw_node in enumerate(raw_nodes):
        item_path = f"{path}.nodes[{index}]"
        item = parser.mapping(raw_node, item_path)
        nodes.append(
            RuleNode(
                id=parser.story_id(item.get("id"), f"{item_path}.id"),
                type=parser.string(
                    item.get("type"), f"{item_path}.type", required=True
                ),
                config=dict(
                    parser.mapping(item.get("config", {}), f"{item_path}.config")
                ),
            )
        )
    edges: list[RuleEdge] = []
    for index, raw_edge in enumerate(raw_edges):
        item_path = f"{path}.edges[{index}]"
        item = parser.mapping(raw_edge, item_path)
        source_ref = parser.mapping(item.get("from"), f"{item_path}.from")
        target_ref = parser.mapping(item.get("to"), f"{item_path}.to")
        edges.append(
            RuleEdge(
                source=PortRef(
                    node_id=parser.story_id(
                        source_ref.get("nodeId"),
                        f"{item_path}.from.nodeId",
                    ),
                    port=parser.string(
                        source_ref.get("port"),
                        f"{item_path}.from.port",
                        required=True,
                    ),
                ),
                target=PortRef(
                    node_id=parser.story_id(
                        target_ref.get("nodeId"),
                        f"{item_path}.to.nodeId",
                    ),
                    port=parser.string(
                        target_ref.get("port"),
                        f"{item_path}.to.port",
                        required=True,
                    ),
                ),
            )
        )
    return RuleGraph(
        version=parser.integer(
            source.get("version", 1), f"{path}.version", minimum=1, default=1
        ),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def parse_story_project(source: Mapping[str, Any]) -> StoryProject:
    """Normalize an aggregate story mapping and reject invalid source shapes."""

    parser = _Parser()
    root = parser.mapping(source, "$")
    metadata_source = parser.mapping(root.get("metadata", {}), "$.metadata")
    variables_source = parser.mapping(root.get("variables", {}), "$.variables")
    variables = tuple(
        _parse_variable(parser, str(identifier), value, f"$.variables.{identifier}")
        for identifier, value in variables_source.items()
    )
    registry = _parse_registry(parser, root.get("cast", {}), "$.cast")
    fallback_start = parser.story_id(root.get("startNodeId"), "$.startNodeId")
    narrative_graph = _parse_narrative_graph(
        parser,
        root.get("narrativeGraph", {}),
        "$.narrativeGraph",
        fallback_start_node_id=fallback_start,
        default_max_cast=registry.defaults.max_active,
    )
    project = StoryProject(
        schema_version=parser.integer(
            root.get("schemaVersion", 1),
            "$.schemaVersion",
            minimum=1,
            default=1,
        ),
        id=parser.story_id(root.get("id"), "$.id"),
        version=parser.integer(
            root.get("version", 1), "$.version", minimum=1, default=1
        ),
        title=parser.string(root.get("title"), "$.title", required=True),
        status=parser.string(root.get("status"), "$.status", default="draft"),
        metadata=StoryMetadata(
            language=parser.string(
                metadata_source.get("language"), "$.metadata.language", default="zh-CN"
            ),
            estimated_minutes=(
                parser.integer(
                    metadata_source.get("estimatedMinutes"),
                    "$.metadata.estimatedMinutes",
                    minimum=1,
                )
                if metadata_source.get("estimatedMinutes") is not None
                else None
            ),
            generation_mode=parser.string(
                metadata_source.get("generationMode"),
                "$.metadata.generationMode",
                default="manual",
            ),
        ),
        variables=variables,
        character_registry=registry,
        narrative_graph=narrative_graph,
        rule_graph=_parse_rule_graph(
            parser, root.get("logicGraph", {}), "$.logicGraph"
        ),
    )
    if parser.diagnostics:
        raise StoryValidationError(parser.diagnostics)
    return project


class StoryProjectLoader:
    """Load a manifest and its declared YAML documents without path escape."""

    def load(self, path: str | Path) -> StoryProject:
        requested = Path(path)
        manifest_path = requested / "manifest.yaml" if requested.is_dir() else requested
        root = manifest_path.parent.resolve()
        manifest = self._read_yaml(manifest_path.resolve(), root)
        aggregate = dict(manifest)
        self._merge_ref(aggregate, manifest, "variablesRef", "variables", root)
        self._merge_ref(aggregate, manifest, "castRef", "cast", root)
        self._merge_ref(
            aggregate, manifest, "narrativeGraphRef", "narrativeGraph", root
        )
        self._merge_ref(aggregate, manifest, "logicGraphRef", "logicGraph", root)
        self._merge_chapter_refs(aggregate, manifest, root)
        return parse_story_project(aggregate)

    def _merge_chapter_refs(
        self,
        aggregate: dict[str, Any],
        manifest: Mapping[str, Any],
        root: Path,
    ) -> None:
        references = manifest.get("chaptersRef")
        if references is None:
            return
        if not isinstance(references, Sequence) or isinstance(
            references, (str, bytes, bytearray)
        ):
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.ref", "chaptersRef must be a list", "$.chaptersRef"
                    )
                ]
            )
        graph = aggregate.setdefault("narrativeGraph", {})
        if not isinstance(graph, dict):
            graph = dict(graph) if isinstance(graph, Mapping) else {}
            aggregate["narrativeGraph"] = graph
        nodes = graph.setdefault("nodes", [])
        if not isinstance(nodes, list):
            nodes = list(nodes) if isinstance(nodes, Sequence) else []
            graph["nodes"] = nodes
        for index, reference in enumerate(references):
            if not isinstance(reference, str) or not reference:
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.ref",
                            "chapter reference must be a string",
                            f"$.chaptersRef[{index}]",
                        )
                    ]
                )
            document = self._read_yaml((root / reference).resolve(), root)
            chapter = document.get("narrativeGraph", document)
            if not isinstance(chapter, Mapping):
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.document",
                            "chapter document must be an object",
                            reference,
                        )
                    ]
                )
            chapter_nodes = chapter.get("nodes", ())
            if not isinstance(chapter_nodes, Sequence) or isinstance(
                chapter_nodes, (str, bytes, bytearray)
            ):
                raise StoryValidationError(
                    [
                        StoryDiagnostic(
                            "schema.document",
                            "chapter nodes must be a list",
                            reference,
                        )
                    ]
                )
            nodes.extend(chapter_nodes)

    def _merge_ref(
        self,
        aggregate: dict[str, Any],
        manifest: Mapping[str, Any],
        ref_key: str,
        destination_key: str,
        root: Path,
    ) -> None:
        reference = manifest.get(ref_key)
        if reference is None:
            return
        if not isinstance(reference, str) or not reference:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.ref", "reference must be a string", f"$.{ref_key}"
                    )
                ]
            )
        target = (root / reference).resolve()
        document = self._read_yaml(target, root)
        aggregate[destination_key] = document.get(destination_key, document)

    def _read_yaml(self, path: Path, root: Path) -> Mapping[str, Any]:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.path_escape", "reference escapes story root", str(path)
                    )
                ]
            ) from error
        if not path.is_file():
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.missing_file", "story file does not exist", str(path)
                    )
                ]
            )
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise StoryValidationError(
                [StoryDiagnostic("schema.read_failed", str(error), str(path))]
            ) from error
        if not isinstance(value, Mapping):
            raise StoryValidationError(
                [
                    StoryDiagnostic(
                        "schema.document", "YAML document must be an object", str(path)
                    )
                ]
            )
        return value


def load_story_project(path: str | Path) -> StoryProject:
    return StoryProjectLoader().load(path)
