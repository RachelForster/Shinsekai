"""Validation and deterministic compilation of story authoring models."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from sdk.path_utils import is_portable_relative_path

from .diagnostics import (
    DiagnosticSeverity,
    StoryCompileError,
    StoryDiagnostic,
)
from .models import (
    CandidateConditionSpec,
    CastMode,
    CastPolicy,
    CompiledStoryNode,
    ConditionSpec,
    EffectSpec,
    PortSchema,
    PortType,
    RuleGraph,
    RuleNode,
    RuleNodeSchema,
    StoryProgram,
    StoryProject,
    StoryVariableDefinition,
    VariableScope,
    VariableType,
)
from .semantic import MAX_REPEAT_WINDOW, SignalStrength
from .state import freeze_value, variable_value_is_valid


def _ports(
    *,
    inputs: Mapping[str, PortSchema] | None = None,
    outputs: Mapping[str, PortSchema] | None = None,
) -> RuleNodeSchema:
    return RuleNodeSchema(inputs=inputs or {}, outputs=outputs or {})


BUILTIN_RULE_NODE_SCHEMAS: Mapping[str, RuleNodeSchema] = {
    "on-choice": _ports(
        outputs={"event": PortSchema(PortType.STORY_EVENT, multiple=True)}
    ),
    "on-intent": _ports(
        outputs={"event": PortSchema(PortType.STORY_EVENT, multiple=True)}
    ),
    "on-node-completed": _ports(
        outputs={"event": PortSchema(PortType.STORY_EVENT, multiple=True)}
    ),
    "semantic-signal": _ports(
        outputs={"accepted": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, multiple=True)}
    ),
    "metric-ref": _ports(
        outputs={"value": PortSchema(PortType.INTEGER, multiple=True)}
    ),
    "flag-ref": _ports(outputs={"value": PortSchema(PortType.BOOLEAN, multiple=True)}),
    "confidence-gate": _ports(
        inputs={"signal": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"accepted": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, multiple=True)},
    ),
    "speech-act-gate": _ports(
        inputs={"signal": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"accepted": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, multiple=True)},
    ),
    "deduplicate": _ports(
        inputs={"event": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"event": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, multiple=True)},
    ),
    "rate-limit": _ports(
        inputs={"event": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"event": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, multiple=True)},
    ),
    "strength-map": _ports(
        inputs={"signal": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "compare": _ports(
        inputs={"input": PortSchema(PortType.INTEGER, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "condition.gte": _ports(
        inputs={"input": PortSchema(PortType.INTEGER, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "condition.lte": _ports(
        inputs={"input": PortSchema(PortType.INTEGER, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "condition.equals": _ports(
        inputs={"input": PortSchema(PortType.ANY, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "all": _ports(
        inputs={"input": PortSchema(PortType.BOOLEAN, required=True, multiple=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "any": _ports(
        inputs={"input": PortSchema(PortType.BOOLEAN, required=True, multiple=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "not": _ports(
        inputs={"input": PortSchema(PortType.BOOLEAN, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "contains": _ports(
        inputs={"input": PortSchema(PortType.ANY, required=True)},
        outputs={"result": PortSchema(PortType.BOOLEAN, multiple=True)},
    ),
    "increment-metric": _ports(
        inputs={"event": PortSchema(PortType.SEMANTIC_SIGNAL_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "set-variable": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "add-set": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "remove-set": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "append-canon": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"effect": PortSchema(PortType.EFFECT, multiple=True)},
    ),
    "router": _ports(
        inputs={
            "event": PortSchema(PortType.STORY_EVENT, required=True),
            "when": PortSchema(PortType.BOOLEAN),
        },
        outputs={"event": PortSchema(PortType.STORY_EVENT, multiple=True)},
    ),
    "unlock": _ports(
        inputs={"when": PortSchema(PortType.BOOLEAN, required=True)},
        outputs={"event": PortSchema(PortType.NODE_UNLOCKED_EVENT, multiple=True)},
    ),
    "enter-story-node": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"event": PortSchema(PortType.NODE_ENTERED_EVENT, multiple=True)},
    ),
    "character-ensure": _ports(
        outputs={"ready": PortSchema(PortType.CHARACTER_READY_EVENT, multiple=True)}
    ),
    "cast-resolve": _ports(
        outputs={"resolved": PortSchema(PortType.CAST_RESOLVED_EVENT, multiple=True)}
    ),
    "character-enter": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"changed": PortSchema(PortType.CAST_CHANGED_EVENT, multiple=True)},
    ),
    "character-exit": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"changed": PortSchema(PortType.CAST_CHANGED_EVENT, multiple=True)},
    ),
    "character-replace": _ports(
        inputs={"event": PortSchema(PortType.STORY_EVENT, required=True)},
        outputs={"changed": PortSchema(PortType.CAST_CHANGED_EVENT, multiple=True)},
    ),
    "character-preload": _ports(
        outputs={"cue": PortSchema(PortType.RESOURCE_LIFECYCLE_CUE, multiple=True)}
    ),
    "character-unload": _ports(
        outputs={"cue": PortSchema(PortType.RESOURCE_LIFECYCLE_CUE, multiple=True)}
    ),
    "presentation": _ports(
        inputs={"event": PortSchema(PortType.ANY, required=True)},
        outputs={"cue": PortSchema(PortType.PRESENTATION_CUE, multiple=True)},
    ),
}


@dataclass(frozen=True, slots=True)
class CompileResult:
    program: StoryProgram | None
    diagnostics: tuple[StoryDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.program is not None and not any(
            item.severity == DiagnosticSeverity.ERROR for item in self.diagnostics
        )


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _primitive(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(_primitive(key)): _primitive(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_primitive(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _primitive(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def story_program_json(program: StoryProgram, *, indent: int | None = None) -> str:
    return json.dumps(
        _primitive(program),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if indent is None else None,
        indent=indent,
    )


class StoryCompiler:
    """Compile authoring models into a validated, immutable StoryProgram."""

    def __init__(
        self,
        *,
        node_schemas: Mapping[str, RuleNodeSchema] | None = None,
    ) -> None:
        self._node_schemas = dict(node_schemas or BUILTIN_RULE_NODE_SCHEMAS)

    def compile(self, project: StoryProject) -> StoryProgram:
        result = self.compile_with_diagnostics(project)
        if not result.ok or result.program is None:
            raise StoryCompileError(
                item
                for item in result.diagnostics
                if item.severity == DiagnosticSeverity.ERROR
            )
        return result.program

    def compile_with_diagnostics(self, project: StoryProject) -> CompileResult:
        diagnostics: list[StoryDiagnostic] = []
        self._validate_project(project, diagnostics)
        diagnostics.sort(key=lambda item: (item.path, item.code, item.message))
        if any(item.severity == DiagnosticSeverity.ERROR for item in diagnostics):
            return CompileResult(program=None, diagnostics=tuple(diagnostics))
        source_hash = hashlib.sha256(
            canonical_json(project).encode("utf-8")
        ).hexdigest()
        nodes = tuple(
            CompiledStoryNode(
                id=node.id,
                title=node.title,
                type=node.type,
                enter_when=node.enter_when,
                on_enter=node.on_enter,
                choices=node.choices,
                freeform_intents=node.freeform_intents,
                cast_policy=node.cast_policy,
                exposed_context=node.exposed_context,
            )
            for node in project.narrative_graph.nodes
        )
        source_map: dict[str, str] = {}
        for index, node in enumerate(project.narrative_graph.nodes):
            source_map[f"node:{node.id}"] = f"$.narrativeGraph.nodes[{index}]"
            for choice_index, choice in enumerate(node.choices):
                source_map[f"choice:{node.id}/{choice.id}"] = (
                    f"$.narrativeGraph.nodes[{index}].choices[{choice_index}]"
                )
            for intent_index, intent in enumerate(node.freeform_intents):
                source_map[f"intent:{node.id}/{intent.id}"] = (
                    f"$.narrativeGraph.nodes[{index}].freeformIntents[{intent_index}]"
                )
        for index, node in enumerate(project.rule_graph.nodes):
            source_map[f"rule:{node.id}"] = f"$.logicGraph.nodes[{index}]"
        rule_graph = RuleGraph(
            version=project.rule_graph.version,
            nodes=tuple(
                RuleNode(id=node.id, type=node.type, config=node.config)
                for node in project.rule_graph.nodes
            ),
            edges=tuple(project.rule_graph.edges),
        )
        return CompileResult(
            program=StoryProgram(
                schema_version=1,
                story_id=project.id,
                story_version=project.version,
                source_hash=source_hash,
                start_node_id=project.narrative_graph.start_node_id,
                variables=project.variables,
                semantic_signals=project.semantic_signals,
                character_registry=project.character_registry,
                nodes=nodes,
                rule_graph=rule_graph,
                source_map=source_map,
            ),
            diagnostics=tuple(diagnostics),
        )

    def _validate_project(
        self,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        if project.schema_version != 1:
            self._error(
                diagnostics,
                "project.schema_version",
                f"unsupported schemaVersion {project.schema_version}",
                "$.schemaVersion",
            )
        variables = project.variables_by_id
        nodes = project.narrative_graph.by_id
        characters = project.character_registry.by_id
        if project.narrative_graph.start_node_id not in nodes:
            self._error(
                diagnostics,
                "narrative.missing_start",
                f"start node {project.narrative_graph.start_node_id!r} does not exist",
                "$.narrativeGraph.startNodeId",
            )
        self._validate_variables(project, diagnostics)
        self._validate_semantic_signals(project, diagnostics)
        self._validate_registry(project, diagnostics)
        for node_index, node in enumerate(project.narrative_graph.nodes):
            node_path = f"$.narrativeGraph.nodes[{node_index}]"
            self._validate_condition(
                node.enter_when,
                variables,
                nodes,
                diagnostics,
                f"{node_path}.enterWhen",
            )
            self._validate_effects(
                node.on_enter,
                variables,
                nodes,
                diagnostics,
                f"{node_path}.onEnter",
            )
            self._validate_cast_policy(
                node.cast_policy, characters, diagnostics, f"{node_path}.castPolicy"
            )
            self._validate_json_value(
                node.exposed_context,
                diagnostics,
                f"{node_path}.exposedContext",
            )
            self._validate_json_value(
                node.locked_context,
                diagnostics,
                f"{node_path}.lockedContext",
            )
            leaked_values = self._leaf_strings(
                node.exposed_context
            ) & self._leaf_strings(node.locked_context)
            if leaked_values:
                self._error(
                    diagnostics,
                    "narrative.secret_leak",
                    "exposedContext repeats locked content",
                    f"{node_path}.exposedContext",
                )
            for choice_index, choice in enumerate(node.choices):
                choice_path = f"{node_path}.choices[{choice_index}]"
                if choice.goto is not None and choice.goto not in nodes:
                    self._error(
                        diagnostics,
                        "narrative.missing_target",
                        f"target node {choice.goto!r} does not exist",
                        f"{choice_path}.goto",
                    )
                self._validate_condition(
                    choice.when,
                    variables,
                    nodes,
                    diagnostics,
                    f"{choice_path}.when",
                )
                self._validate_effects(
                    choice.effects,
                    variables,
                    nodes,
                    diagnostics,
                    f"{choice_path}.effects",
                )
            for intent_index, intent in enumerate(node.freeform_intents):
                intent_path = f"{node_path}.freeformIntents[{intent_index}]"
                self._validate_condition(
                    intent.when,
                    variables,
                    nodes,
                    diagnostics,
                    f"{intent_path}.when",
                )
                self._validate_effects(
                    intent.effects,
                    variables,
                    nodes,
                    diagnostics,
                    f"{intent_path}.effects",
                )
        self._validate_rule_graph(project, diagnostics)

    def _validate_variables(
        self,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        for variable in project.variables:
            path = f"$.variables.{variable.id}"
            if variable.minimum is not None and variable.maximum is not None:
                if variable.minimum > variable.maximum:
                    self._error(
                        diagnostics,
                        "variable.bounds",
                        "min cannot exceed max",
                        path,
                    )
            if variable.type == VariableType.BOOLEAN:
                valid_initial = isinstance(variable.initial, bool)
            elif variable.type == VariableType.INTEGER:
                valid_initial = isinstance(variable.initial, int) and not isinstance(
                    variable.initial, bool
                )
                if valid_initial and variable.minimum is not None:
                    valid_initial = variable.initial >= variable.minimum
                if valid_initial and variable.maximum is not None:
                    valid_initial = variable.initial <= variable.maximum
            elif variable.type == VariableType.ENUM:
                valid_initial = isinstance(variable.initial, str) and (
                    not variable.enum_values or variable.initial in variable.enum_values
                )
                if not variable.enum_values:
                    self._error(
                        diagnostics,
                        "variable.enum_values",
                        "enum variables must declare at least one allowed value",
                        f"{path}.values",
                    )
            else:
                valid_initial = isinstance(
                    variable.initial, (list, tuple, set, frozenset)
                ) and all(isinstance(item, str) for item in variable.initial)
            if not valid_initial:
                self._error(
                    diagnostics,
                    "variable.initial_type",
                    f"initial value is invalid for {variable.type.value}",
                    f"{path}.initial",
                )
            if variable.allow_semantic_input and variable.type != VariableType.INTEGER:
                self._error(
                    diagnostics,
                    "variable.semantic_type",
                    "semantic input is only supported for integer variables",
                    f"{path}.allowSemanticInput",
                )

    def _validate_semantic_signals(
        self,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        variables = project.variables_by_id
        seen: set[str] = set()
        required_strengths = set(SignalStrength)
        for index, definition in enumerate(project.semantic_signals):
            path = f"$.semanticSignals[{index}]"
            if definition.id in seen:
                self._error(
                    diagnostics,
                    "semantic.duplicate_id",
                    f"duplicate semantic signal {definition.id!r}",
                    f"{path}.id",
                )
            seen.add(definition.id)
            if not math.isfinite(definition.minimum_confidence) or not (
                0.0 <= definition.minimum_confidence <= 1.0
            ):
                self._error(
                    diagnostics,
                    "semantic.confidence",
                    "minimum confidence must be finite and between 0 and 1",
                    f"{path}.minimumConfidence",
                )
            if not definition.allowed_speech_acts:
                self._error(
                    diagnostics,
                    "semantic.speech_acts",
                    "at least one speech act must be allowed",
                    f"{path}.allowedSpeechActs",
                )
            if (
                isinstance(definition.repeat_window, bool)
                or not isinstance(definition.repeat_window, int)
                or not 0 <= definition.repeat_window <= MAX_REPEAT_WINDOW
            ):
                self._error(
                    diagnostics,
                    "semantic.repeat_window",
                    f"repeatWindow must be between 0 and {MAX_REPEAT_WINDOW}",
                    f"{path}.repeatWindow",
                )
            if set(definition.effects_by_strength) != required_strengths:
                self._error(
                    diagnostics,
                    "semantic.strength_map",
                    "effectsByStrength must define weak, medium, and strong",
                    f"{path}.effectsByStrength",
                )
            for strength in SignalStrength:
                effects = definition.effects_by_strength.get(strength, ())
                effect_path = f"{path}.effectsByStrength.{strength.value}"
                if not effects:
                    self._error(
                        diagnostics,
                        "semantic.empty_effects",
                        "each signal strength must define at least one effect",
                        effect_path,
                    )
                self._validate_effects(
                    effects,
                    variables,
                    project.narrative_graph.by_id,
                    diagnostics,
                    effect_path,
                )
                for effect_index, effect in enumerate(effects):
                    target_path = f"{effect_path}[{effect_index}]"
                    if effect.op not in {"set", "increment"} or not effect.args:
                        self._error(
                            diagnostics,
                            "semantic.effect_operator",
                            "semantic signals may only set or increment metrics",
                            target_path,
                        )
                        continue
                    variable = variables.get(str(effect.args[0]))
                    if variable is None:
                        continue
                    if variable.scope != VariableScope.BRANCH:
                        self._error(
                            diagnostics,
                            "semantic.global_target",
                            "semantic signals may only target branch variables",
                            target_path,
                        )
                    if not variable.allow_semantic_input:
                        self._error(
                            diagnostics,
                            "semantic.target_disabled",
                            "target variable does not allow semantic input",
                            target_path,
                        )

    def _validate_registry(
        self,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        registry = project.character_registry
        characters = registry.by_id
        for index, character_id in enumerate(registry.initial_cast):
            if character_id not in characters:
                self._error(
                    diagnostics,
                    "cast.unknown_character",
                    f"character {character_id!r} is not registered",
                    f"$.cast.initialCast[{index}]",
                )
        if len(set(registry.initial_cast)) > registry.defaults.max_active:
            self._error(
                diagnostics,
                "cast.too_many_initial",
                "initialCast exceeds defaults.maxActive",
                "$.cast.initialCast",
            )
        for index, character in enumerate(registry.characters):
            path = f"$.cast.characters[{index}].source"
            if character.source.path and not is_portable_relative_path(
                character.source.path
            ):
                self._error(
                    diagnostics,
                    "character.path_escape",
                    "character source path must stay inside the story root",
                    f"{path}.path",
                )
            if (
                project.status == "published"
                and not character.source.path
                and not character.source.revision
                and not character.source.content_digest
            ):
                self._error(
                    diagnostics,
                    "character.unpinned",
                    "published library character must pin a revision or content digest",
                    path,
                )

    def _validate_cast_policy(
        self,
        policy: CastPolicy,
        characters: Mapping[str, Any],
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        required = set(policy.required)
        forbidden = set(policy.forbidden)
        for field_name, identifiers in (
            ("required", policy.required),
            ("forbidden", policy.forbidden),
        ):
            for index, identifier in enumerate(identifiers):
                if identifier not in characters:
                    self._error(
                        diagnostics,
                        "cast.unknown_character",
                        f"character {identifier!r} is not registered",
                        f"{path}.{field_name}[{index}]",
                    )
        if required & forbidden:
            self._error(
                diagnostics,
                "cast.required_forbidden",
                "a required character cannot also be forbidden",
                path,
            )
        constraints = policy.constraints
        if constraints.min_active > constraints.max_active:
            self._error(
                diagnostics,
                "cast.invalid_range",
                "minActive cannot exceed maxActive",
                f"{path}.constraints",
            )
        required_role_slots = sum(role.count for role in policy.required_roles)
        if len(required) + required_role_slots > constraints.max_active:
            self._error(
                diagnostics,
                "cast.required_overflow",
                "required characters and roles exceed maxActive",
                path,
            )
        for condition_index, condition in enumerate(policy.optional_query.conditions):
            self._validate_candidate_condition(
                condition,
                characters,
                diagnostics,
                f"{path}.optionalQuery.allConditions[{condition_index}]",
            )
        any_tags = set(policy.optional_query.any_tags)
        all_tags = set(policy.optional_query.all_tags)
        eligible_characters = {
            identifier: character
            for identifier, character in characters.items()
            if identifier not in forbidden
            and (not any_tags or any_tags.intersection(character.tags))
            and all_tags.issubset(character.tags)
        }
        for role_index, role in enumerate(policy.required_roles):
            role_path = f"{path}.requiredRoles[{role_index}]"
            for prefer_index, identifier in enumerate(role.prefer):
                if identifier not in characters:
                    self._error(
                        diagnostics,
                        "cast.unknown_character",
                        f"preferred character {identifier!r} is not registered",
                        f"{role_path}.prefer[{prefer_index}]",
                    )
            role_candidates = tuple(
                character
                for character in eligible_characters.values()
                if role.role in character.roles
            )
            if len(role_candidates) < role.count and (
                policy.fallback.on_missing_role == "error"
            ):
                self._error(
                    diagnostics,
                    "cast.unresolved_role",
                    f"role {role.role!r} requires {role.count} eligible character(s), "
                    f"but only {len(role_candidates)} remain after policy filters",
                    role_path,
                )
        if policy.mode == CastMode.FIXED and policy.required_roles:
            self._error(
                diagnostics,
                "cast.fixed_roles",
                "fixed cast cannot contain unresolved requiredRoles",
                f"{path}.requiredRoles",
            )

    def _validate_candidate_condition(
        self,
        condition: CandidateConditionSpec,
        characters: Mapping[str, Any],
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        if not isinstance(condition, CandidateConditionSpec):
            self._error(
                diagnostics,
                "cast.condition_context",
                "optionalQuery requires candidate conditions",
                path,
            )
            return
        if condition.op in {"available", "alive"}:
            value = condition.args[0] if len(condition.args) == 1 else None
            if len(condition.args) != 1 or not isinstance(value, bool):
                self._error(
                    diagnostics,
                    "cast.condition_value",
                    f"{condition.op} requires one boolean value",
                    path,
                )
            return
        if condition.op == "sameLocationAs":
            target = condition.args[0] if len(condition.args) == 1 else None
            if not isinstance(target, str) or not target:
                self._error(
                    diagnostics,
                    "cast.condition_value",
                    "sameLocationAs requires one non-empty actor identifier",
                    path,
                )
            elif target != "player" and target not in characters:
                self._error(
                    diagnostics,
                    "cast.condition_unknown_actor",
                    f"sameLocationAs actor {target!r} is not registered",
                    path,
                )
            return
        self._error(
            diagnostics,
            "cast.condition_operator",
            f"unsupported candidate predicate {condition.op!r}",
            path,
        )

    def _validate_condition(
        self,
        condition: ConditionSpec,
        variables: Mapping[str, Any],
        nodes: Mapping[str, Any],
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        if not isinstance(condition, ConditionSpec):
            self._error(
                diagnostics,
                "condition.context",
                "narrative fields require narrative state conditions",
                path,
            )
            return
        if condition.op in {"true", "false"}:
            if condition.args:
                self._error(
                    diagnostics,
                    "condition.arity",
                    f"{condition.op} does not accept arguments",
                    path,
                )
            return
        if condition.op in {"all", "any"}:
            for index, child in enumerate(condition.args):
                self._validate_condition(
                    child,
                    variables,
                    nodes,
                    diagnostics,
                    f"{path}.{condition.op}[{index}]",
                )
            return
        if condition.op == "not":
            if len(condition.args) != 1:
                self._error(
                    diagnostics,
                    "condition.arity",
                    "not requires one condition",
                    path,
                )
            if condition.args:
                self._validate_condition(
                    condition.args[0], variables, nodes, diagnostics, f"{path}.not"
                )
            return
        if condition.op == "completed":
            if len(condition.args) != 1:
                self._error(
                    diagnostics,
                    "condition.arity",
                    "completed requires one node identifier",
                    path,
                )
            node_id = condition.args[0] if condition.args else None
            if not isinstance(node_id, str):
                self._error(
                    diagnostics,
                    "condition.reference_type",
                    "completed requires a string node identifier",
                    path,
                )
            elif node_id not in nodes:
                self._error(
                    diagnostics,
                    "condition.unknown_node",
                    f"node {node_id!r} does not exist",
                    path,
                )
            return
        if condition.op == "flag":
            if len(condition.args) != 1:
                self._error(
                    diagnostics,
                    "condition.arity",
                    "flag requires one variable identifier",
                    path,
                )
            variable_id = condition.args[0] if condition.args else None
            variable = (
                variables.get(variable_id) if isinstance(variable_id, str) else None
            )
            if not isinstance(variable_id, str):
                self._error(
                    diagnostics,
                    "condition.reference_type",
                    "flag requires a string variable identifier",
                    path,
                )
            elif variable is None or variable.type != VariableType.BOOLEAN:
                self._error(
                    diagnostics,
                    "condition.invalid_flag",
                    f"flag {variable_id!r} must reference a boolean variable",
                    path,
                )
            return
        if condition.op in {"equals", "gte", "lte", "contains"}:
            if len(condition.args) != 2:
                self._error(
                    diagnostics,
                    "condition.arity",
                    f"{condition.op} requires two arguments",
                    path,
                )
            variable_id = condition.args[0] if condition.args else None
            variable = (
                variables.get(variable_id) if isinstance(variable_id, str) else None
            )
            if not isinstance(variable_id, str):
                self._error(
                    diagnostics,
                    "condition.reference_type",
                    f"{condition.op} requires a string variable identifier",
                    path,
                )
            elif variable is None:
                self._error(
                    diagnostics,
                    "condition.unknown_variable",
                    f"variable {variable_id!r} does not exist",
                    path,
                )
            elif (
                condition.op in {"gte", "lte"} and variable.type != VariableType.INTEGER
            ):
                self._error(
                    diagnostics,
                    "condition.invalid_numeric",
                    f"{condition.op} requires an integer variable",
                    path,
                )
            elif condition.op == "contains" and variable.type not in {
                VariableType.STRING_SET,
                VariableType.NODE_SET,
            }:
                self._error(
                    diagnostics,
                    "condition.invalid_collection",
                    "contains requires a set variable",
                    path,
                )
            elif condition.op in {"gte", "lte"}:
                expected = condition.args[1] if len(condition.args) > 1 else None
                if isinstance(expected, bool) or not isinstance(expected, int):
                    self._error(
                        diagnostics,
                        "condition.value_type",
                        f"{condition.op} comparison value must be an integer",
                        path,
                    )
            elif condition.op == "contains":
                expected = condition.args[1] if len(condition.args) > 1 else None
                if not isinstance(expected, str):
                    self._error(
                        diagnostics,
                        "condition.value_type",
                        "contains value must be a string",
                        path,
                    )
            elif condition.op == "equals":
                expected = condition.args[1] if len(condition.args) > 1 else None
                if not self._variable_accepts(variable, expected):
                    self._error(
                        diagnostics,
                        "condition.value_type",
                        f"comparison value is invalid for {variable.type.value}",
                        path,
                    )
            return
        self._error(
            diagnostics,
            "condition.operator",
            f"unsupported narrative condition operator {condition.op!r}",
            path,
        )

    def _validate_effects(
        self,
        effects: Iterable[EffectSpec],
        variables: Mapping[str, Any],
        nodes: Mapping[str, Any],
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        for index, effect in enumerate(effects):
            effect_path = f"{path}[{index}]"
            if effect.op in {"set", "increment", "add-set", "remove-set"}:
                variable_id = effect.args[0] if effect.args else None
                variable = (
                    variables.get(variable_id) if isinstance(variable_id, str) else None
                )
                if not isinstance(variable_id, str):
                    self._error(
                        diagnostics,
                        "effect.reference_type",
                        f"{effect.op} requires a string variable identifier",
                        effect_path,
                    )
                elif variable is None:
                    self._error(
                        diagnostics,
                        "effect.unknown_variable",
                        f"variable {variable_id!r} does not exist",
                        effect_path,
                    )
                elif effect.op == "increment" and variable.type != VariableType.INTEGER:
                    self._error(
                        diagnostics,
                        "effect.invalid_increment",
                        "increment requires an integer variable",
                        effect_path,
                    )
                elif effect.op == "increment":
                    amount = effect.args[1] if len(effect.args) > 1 else None
                    if isinstance(amount, bool) or not isinstance(amount, int):
                        self._error(
                            diagnostics,
                            "effect.value_type",
                            "increment amount must be an integer",
                            effect_path,
                        )
                elif effect.op in {"add-set", "remove-set"} and variable.type not in {
                    VariableType.STRING_SET,
                    VariableType.NODE_SET,
                }:
                    self._error(
                        diagnostics,
                        "effect.invalid_collection",
                        f"{effect.op} requires a set variable",
                        effect_path,
                    )
                elif effect.op in {"add-set", "remove-set"}:
                    item = effect.args[1] if len(effect.args) > 1 else None
                    if not isinstance(item, str):
                        self._error(
                            diagnostics,
                            "effect.value_type",
                            f"{effect.op} value must be a string",
                            effect_path,
                        )
                elif effect.op == "set":
                    value = effect.args[1] if len(effect.args) > 1 else None
                    if not self._variable_accepts(variable, value):
                        self._error(
                            diagnostics,
                            "effect.value_type",
                            f"set value is invalid for {variable.type.value}",
                            effect_path,
                        )
            elif effect.op == "unlock":
                target = effect.args[0] if effect.args else None
                if not isinstance(target, str):
                    self._error(
                        diagnostics,
                        "effect.reference_type",
                        "unlock requires a string node identifier",
                        effect_path,
                    )
                elif target not in nodes:
                    self._error(
                        diagnostics,
                        "effect.unknown_node",
                        f"node {target!r} does not exist",
                        effect_path,
                    )

    def _validate_rule_graph(
        self,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        graph = project.rule_graph
        nodes = graph.by_id
        incoming: dict[tuple[str, str], int] = {}
        adjacency: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
        for index, node in enumerate(graph.nodes):
            path = f"$.logicGraph.nodes[{index}]"
            self._validate_json_value(node.config, diagnostics, f"{path}.config")
            schema = self._node_schemas.get(node.type)
            if schema is None:
                self._error(
                    diagnostics,
                    "rule.unknown_type",
                    f"unknown rule node type {node.type!r}",
                    f"{path}.type",
                )
                continue
            self._validate_rule_config(node, project, diagnostics, f"{path}.config")
        for edge_index, edge in enumerate(graph.edges):
            edge_path = f"$.logicGraph.edges[{edge_index}]"
            source_node = nodes.get(edge.source.node_id)
            target_node = nodes.get(edge.target.node_id)
            if source_node is None:
                self._error(
                    diagnostics,
                    "rule.missing_node",
                    f"source node {edge.source.node_id!r} does not exist",
                    f"{edge_path}.from.nodeId",
                )
                continue
            if target_node is None:
                self._error(
                    diagnostics,
                    "rule.missing_node",
                    f"target node {edge.target.node_id!r} does not exist",
                    f"{edge_path}.to.nodeId",
                )
                continue
            source_schema = self._node_schemas.get(source_node.type)
            target_schema = self._node_schemas.get(target_node.type)
            if source_schema is None or target_schema is None:
                continue
            source_port = source_schema.outputs.get(edge.source.port)
            target_port = target_schema.inputs.get(edge.target.port)
            if source_port is None:
                self._error(
                    diagnostics,
                    "rule.missing_port",
                    f"output port {edge.source.port!r} does not exist",
                    f"{edge_path}.from.port",
                )
                continue
            if target_port is None:
                self._error(
                    diagnostics,
                    "rule.missing_port",
                    f"input port {edge.target.port!r} does not exist",
                    f"{edge_path}.to.port",
                )
                continue
            if (
                source_port.type != target_port.type
                and source_port.type != PortType.ANY
                and target_port.type != PortType.ANY
            ):
                self._error(
                    diagnostics,
                    "rule.port_type",
                    f"cannot connect {source_port.type.value} to {target_port.type.value}",
                    edge_path,
                )
            key = (target_node.id, edge.target.port)
            incoming[key] = incoming.get(key, 0) + 1
            if incoming[key] > 1 and not target_port.multiple:
                self._error(
                    diagnostics,
                    "rule.port_cardinality",
                    "input port does not allow multiple connections",
                    f"{edge_path}.to",
                )
            adjacency[source_node.id].add(target_node.id)
        for index, node in enumerate(graph.nodes):
            schema = self._node_schemas.get(node.type)
            if schema is None:
                continue
            for port_name, port in schema.inputs.items():
                if port.required and incoming.get((node.id, port_name), 0) == 0:
                    self._error(
                        diagnostics,
                        "rule.required_port",
                        f"required input port {port_name!r} is not connected",
                        f"$.logicGraph.nodes[{index}]",
                    )
        self._validate_rule_cycles(graph, adjacency, diagnostics)

    def _validate_rule_config(
        self,
        node: RuleNode,
        project: StoryProject,
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        variables = project.variables_by_id
        story_nodes = project.narrative_graph.by_id
        characters = project.character_registry.by_id
        if node.type in {
            "metric-ref",
            "flag-ref",
            "increment-metric",
            "set-variable",
            "add-set",
            "remove-set",
        }:
            variable_id = node.config.get("variable")
            variable = (
                variables.get(variable_id) if isinstance(variable_id, str) else None
            )
            if not isinstance(variable_id, str):
                self._error(
                    diagnostics,
                    "rule.invalid_config",
                    f"{node.type} requires a string variable identifier",
                    f"{path}.variable",
                )
            elif variable is None:
                self._error(
                    diagnostics,
                    "rule.unknown_variable",
                    f"variable {variable_id!r} does not exist",
                    f"{path}.variable",
                )
            elif (
                node.type in {"metric-ref", "increment-metric"}
                and variable.type != VariableType.INTEGER
            ):
                self._error(
                    diagnostics,
                    "rule.invalid_metric",
                    "metric node requires an integer variable",
                    f"{path}.variable",
                )
            elif node.type == "flag-ref" and variable.type != VariableType.BOOLEAN:
                self._error(
                    diagnostics,
                    "rule.invalid_flag",
                    "flag-ref requires a boolean variable",
                    f"{path}.variable",
                )
        if node.type in {"unlock", "enter-story-node"}:
            target = node.config.get("storyNodeId")
            if not isinstance(target, str):
                self._error(
                    diagnostics,
                    "rule.invalid_config",
                    f"{node.type} requires a string storyNodeId",
                    f"{path}.storyNodeId",
                )
            elif target not in story_nodes:
                self._error(
                    diagnostics,
                    "rule.unknown_story_node",
                    f"story node {target!r} does not exist",
                    f"{path}.storyNodeId",
                )
        if node.type in {"condition.gte", "condition.lte"}:
            value = node.config.get("value")
            if isinstance(value, bool) or not isinstance(value, int):
                self._error(
                    diagnostics,
                    "rule.invalid_config",
                    f"{node.type} requires an integer value",
                    f"{path}.value",
                )
        if node.type == "compare":
            operator = node.config.get("operator", "gte")
            if not isinstance(operator, str) or operator not in {
                "gte",
                "lte",
                "equals",
            }:
                self._error(
                    diagnostics,
                    "rule.invalid_config",
                    "compare operator must be gte, lte, or equals",
                    f"{path}.operator",
                )
            value = node.config.get("value")
            if isinstance(value, bool) or not isinstance(value, int):
                self._error(
                    diagnostics,
                    "rule.invalid_config",
                    "compare requires an integer value",
                    f"{path}.value",
                )
        if node.type.startswith("character-"):
            fields_to_validate = (
                ("fromCharacterId", "toCharacterId")
                if node.type == "character-replace"
                else ("characterId",)
            )
            for field_name in fields_to_validate:
                character_id = node.config.get(field_name)
                if not isinstance(character_id, str):
                    self._error(
                        diagnostics,
                        "rule.invalid_config",
                        f"{field_name} must be a string character identifier",
                        f"{path}.{field_name}",
                    )
                elif character_id not in characters:
                    self._error(
                        diagnostics,
                        "rule.unknown_character",
                        f"character {character_id!r} is not registered",
                        f"{path}.{field_name}",
                    )

    def _validate_rule_cycles(
        self,
        graph: RuleGraph,
        adjacency: Mapping[str, set[str]],
        diagnostics: list[StoryDiagnostic],
    ) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str, stack: list[str]) -> None:
            if node_id in visiting:
                cycle_start = stack.index(node_id) if node_id in stack else 0
                cycle = stack[cycle_start:] + [node_id]
                self._error(
                    diagnostics,
                    "rule.cycle",
                    "rule graph contains a cycle: " + " -> ".join(cycle),
                    "$.logicGraph.edges",
                )
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            stack.append(node_id)
            for target in sorted(adjacency.get(node_id, ())):
                visit(target, stack)
            stack.pop()
            visiting.remove(node_id)
            visited.add(node_id)

        for node in graph.nodes:
            visit(node.id, [])

    @staticmethod
    def _variable_accepts(variable: StoryVariableDefinition, value: Any) -> bool:
        if variable.type in {VariableType.STRING_SET, VariableType.NODE_SET}:
            if not isinstance(value, (list, tuple, set, frozenset)) or not all(
                isinstance(item, str) for item in value
            ):
                return False
            value = frozenset(value)
        else:
            value = freeze_value(value)
        return variable_value_is_valid(variable, value)

    @classmethod
    def _leaf_strings(cls, value: Any) -> set[str]:
        if isinstance(value, str):
            normalized = value.strip()
            return {normalized} if len(normalized) >= 4 else set()
        if isinstance(value, Mapping):
            result: set[str] = set()
            for item in value.values():
                result.update(cls._leaf_strings(item))
            return result
        if isinstance(value, (tuple, list, set, frozenset)):
            result = set()
            for item in value:
                result.update(cls._leaf_strings(item))
            return result
        return set()

    @classmethod
    def _validate_json_value(
        cls,
        value: Any,
        diagnostics: list[StoryDiagnostic],
        path: str,
    ) -> None:
        if value is None or isinstance(value, (bool, int, str)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                cls._error(
                    diagnostics,
                    "schema.json_value",
                    "JSON numbers must be finite",
                    path,
                )
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    cls._error(
                        diagnostics,
                        "schema.mapping_key",
                        "object keys must be strings",
                        f"{path}[{key!r}]",
                    )
                    continue
                cls._validate_json_value(item, diagnostics, f"{path}.{key}")
            return
        if isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                cls._validate_json_value(item, diagnostics, f"{path}[{index}]")
            return
        cls._error(
            diagnostics,
            "schema.json_value",
            f"unsupported JSON value of type {type(value).__name__}",
            path,
        )

    @staticmethod
    def _error(
        diagnostics: list[StoryDiagnostic],
        code: str,
        message: str,
        path: str,
    ) -> None:
        diagnostics.append(StoryDiagnostic(code=code, message=message, path=path))
