"""Pure command/event runtime for compiled Shinsekai story programs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from .cast import (
    CastResolutionContext,
    CastResolutionError,
    CastResolutionPlan,
    CastResolver,
)
from .commands import (
    ApplySemanticSignals,
    CompleteNode,
    EnterNode,
    PerformIntent,
    RuntimeCommand,
    SelectChoice,
    StartStory,
)
from .events import StoryEvent, StoryEventType
from .models import (
    EffectSpec,
    StoryProgram,
    StoryVariableDefinition,
    VariableScope,
    VariableType,
)
from .rules import ConditionEvaluator, RuleEvaluator
from .semantic import SemanticSignalDefinition, SemanticSignalPolicy
from .state import (
    CanonFact,
    CastState,
    SemanticSignalState,
    StoryState,
    freeze_mapping,
    freeze_value,
    variable_value_is_valid,
)


class StoryRuntimeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    state: StoryState
    events: tuple[StoryEvent, ...]
    global_effects: tuple[EffectSpec, ...] = ()
    cast_plans: tuple[CastResolutionPlan, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingEvent:
    type: StoryEventType
    payload: Mapping[str, Any]


class _Transaction:
    def __init__(
        self,
        *,
        program: StoryProgram,
        state: StoryState,
        global_variables: Mapping[str, Any],
        command_id: str,
        cast_resolver: CastResolver,
        cast_context: CastResolutionContext,
        condition_evaluator: ConditionEvaluator,
        rule_evaluator: RuleEvaluator,
    ) -> None:
        self.program = program
        self.original = state
        self.global_variables = dict(global_variables)
        self.command_id = command_id
        self.cast_resolver = cast_resolver
        self.cast_context = cast_context
        self.condition_evaluator = condition_evaluator
        self.rule_evaluator = rule_evaluator
        self.variables = dict(state.variables)
        self.completed = set(state.completed_node_ids)
        self.failed = set(state.failed_node_ids)
        self.unlocked = set(state.unlocked_node_ids)
        self.current_node_id = state.current_node_id
        self.canon = list(state.canon)
        self.semantic_state = state.semantic_signal_state
        self.active_cast = list(state.cast_state.active_character_ids)
        self.role_bindings = dict(state.cast_state.role_bindings)
        self.cast_changed = False
        self.global_effects: list[EffectSpec] = []
        self.cast_plans: list[CastResolutionPlan] = []
        self.pending: list[_PendingEvent] = []

    def emit(self, event_type: StoryEventType, **payload: Any) -> str:
        self.pending.append(_PendingEvent(event_type, freeze_mapping(payload)))
        return self._event_id(len(self.pending) - 1)

    def evaluate(self, condition: Any) -> bool:
        variables = {**self.global_variables, **self.variables}
        return self.condition_evaluator.evaluate(
            condition,
            variables=variables,
            completed_node_ids=frozenset(self.completed),
        )

    def apply_effects(
        self,
        effects: tuple[EffectSpec, ...],
        *,
        semantic: bool = False,
    ) -> None:
        for effect in effects:
            self._apply_effect(effect, semantic=semantic)

    def _apply_effect(self, effect: EffectSpec, *, semantic: bool) -> None:
        if effect.op == "noop":
            return
        if effect.op in {"set", "increment", "add-set", "remove-set"}:
            variable_id = str(effect.args[0])
            definition = self._variable_definition(variable_id)
            if semantic and not definition.allow_semantic_input:
                raise StoryRuntimeError(
                    "runtime.semantic_target",
                    f"variable {variable_id!r} does not allow semantic input",
                )
            target_variables = (
                self.global_variables
                if definition.scope == VariableScope.GLOBAL
                else self.variables
            )
            previous = target_variables[variable_id]
            operand = effect.args[1]
            if effect.op == "set":
                current = self._normalize_value(definition, operand)
            elif effect.op == "increment":
                if isinstance(operand, bool) or not isinstance(operand, int):
                    raise StoryRuntimeError(
                        "runtime.effect_value",
                        "increment amount must be an integer",
                    )
                current = int(previous) + operand
                if definition.minimum is not None:
                    current = max(definition.minimum, current)
                if definition.maximum is not None:
                    current = min(definition.maximum, current)
            else:
                values = set(previous)
                if not isinstance(operand, str):
                    raise StoryRuntimeError(
                        "runtime.effect_value",
                        f"{effect.op} value must be a string",
                    )
                if effect.op == "add-set":
                    values.add(operand)
                else:
                    values.discard(operand)
                current = frozenset(values)
            target_variables[variable_id] = current
            if current == previous:
                return
            if definition.scope == VariableScope.GLOBAL:
                self.global_effects.append(effect)
                return
            if effect.op == "add-set":
                event_type = StoryEventType.SET_VALUE_ADDED
            elif effect.op == "remove-set":
                event_type = StoryEventType.SET_VALUE_REMOVED
            elif semantic and definition.allow_semantic_input:
                event_type = StoryEventType.METRIC_CHANGED
            else:
                event_type = StoryEventType.VARIABLE_CHANGED
            self.emit(
                event_type,
                variableId=variable_id,
                previous=previous,
                current=current,
            )
            return
        if effect.op == "append-canon":
            raw_value = effect.args[0]
            text = (
                str(raw_value.get("text", ""))
                if isinstance(raw_value, Mapping)
                else str(raw_value)
            )
            if not text:
                raise StoryRuntimeError(
                    "effect.invalid_canon", "canon text cannot be empty"
                )
            canon_id = f"canon-{self.original.event_cursor + len(self.pending) + 1}"
            event_id = self.emit(
                StoryEventType.CANON_APPENDED,
                canonId=canon_id,
                text=text,
            )
            self.canon.append(
                CanonFact(
                    id=canon_id,
                    text=text,
                    source_event_id=event_id,
                )
            )
            return
        if effect.op == "unlock":
            self.unlock_node(str(effect.args[0]))
            return
        raise StoryRuntimeError(
            "effect.unsupported",
            f"unsupported runtime effect {effect.op!r}",
        )

    def unlock_node(self, node_id: str) -> None:
        if node_id not in self.program.nodes_by_id:
            raise StoryRuntimeError(
                "runtime.unknown_node",
                f"node {node_id!r} does not exist",
            )
        if node_id in self.unlocked:
            return
        self.unlocked.add(node_id)
        self.emit(StoryEventType.NODE_UNLOCKED, nodeId=node_id)

    def recompute_unlocks(self) -> None:
        transient_state = self._preview_state()
        variables = {**self.global_variables, **transient_state.variables}
        for node_id in sorted(
            self.rule_evaluator.evaluate_unlocks(
                self.program,
                variables,
            )
        ):
            self.unlock_node(node_id)

    def enter_node(self, node_id: str, *, require_unlocked: bool = False) -> None:
        node = self.program.nodes_by_id.get(node_id)
        if node is None:
            raise StoryRuntimeError(
                "runtime.unknown_node",
                f"node {node_id!r} does not exist",
            )
        if require_unlocked and node_id not in self.unlocked:
            raise StoryRuntimeError(
                "runtime.node_locked",
                f"node {node_id!r} is not unlocked",
            )
        if not self.evaluate(node.enter_when):
            raise StoryRuntimeError(
                "runtime.enter_condition",
                f"enter condition for node {node_id!r} is not satisfied",
            )
        self.current_node_id = node_id
        self.unlock_node(node_id)
        self.apply_effects(node.on_enter)
        resolution_context = replace(
            self.cast_context,
            current_cast=tuple(self.active_cast) or self.cast_context.current_cast,
        )
        try:
            resolution = self.cast_resolver.resolve(
                self.program.character_registry,
                node.cast_policy,
                resolution_context,
            )
        except CastResolutionError as error:
            raise StoryRuntimeError(error.code, str(error)) from error
        self.active_cast = list(resolution.active_character_ids)
        self.role_bindings = dict(resolution.role_bindings)
        self.cast_changed = True
        self.cast_plans.append(resolution)
        self.emit(
            StoryEventType.CAST_RESOLVED,
            nodeId=node_id,
            activeCharacterIds=tuple(self.active_cast),
            roleBindings=self.role_bindings,
            unresolvedRoles=resolution.unresolved_roles,
        )
        self.emit(StoryEventType.NODE_ENTERED, nodeId=node_id)
        if node.type == "ending":
            self.emit(StoryEventType.ENDING_REACHED, nodeId=node_id)
        self.recompute_unlocks()

    def complete_node(self, node_id: str) -> None:
        if node_id in self.completed:
            return
        self.completed.add(node_id)
        self.emit(StoryEventType.NODE_COMPLETED, nodeId=node_id)

    def commit(self) -> RuntimeResult:
        self._validate_state()
        if not self.pending:
            self.emit(StoryEventType.COMMAND_PROCESSED)
        new_revision = self.original.revision + 1
        events = tuple(
            StoryEvent(
                id=self._event_id(index),
                revision=new_revision,
                type=pending.type,
                payload=pending.payload,
                cause_command_id=self.command_id,
            )
            for index, pending in enumerate(self.pending)
        )
        registered = frozenset(self.program.character_registry.by_id)
        active = tuple(self.active_cast)
        cast_state = CastState(
            registered_story_character_ids=registered,
            active_character_ids=active,
            offstage_character_ids=registered.difference(active),
            story_scoped_character_ids=self.original.cast_state.story_scoped_character_ids,
            ad_hoc_character_ids=self.original.cast_state.ad_hoc_character_ids,
            role_bindings=freeze_mapping(self.role_bindings),
            resolved_for_node_id=self.current_node_id,
            cast_revision=(
                self.original.cast_state.cast_revision + 1
                if self.cast_changed
                else self.original.cast_state.cast_revision
            ),
        )
        state = StoryState(
            schema_version=1,
            story_id=self.program.story_id,
            story_version=self.program.story_version,
            program_source_hash=self.program.source_hash,
            revision=new_revision,
            current_node_id=self.current_node_id,
            variables=freeze_mapping(self.variables),
            completed_node_ids=frozenset(self.completed),
            failed_node_ids=frozenset(self.failed),
            unlocked_node_ids=frozenset(self.unlocked),
            canon=tuple(self.canon),
            semantic_signal_state=self.semantic_state,
            cast_state=cast_state,
            event_cursor=self.original.event_cursor + len(events),
        )
        return RuntimeResult(
            state=state,
            events=events,
            global_effects=tuple(self.global_effects),
            cast_plans=tuple(self.cast_plans),
        )

    def _preview_state(self) -> StoryState:
        return replace(
            self.original,
            current_node_id=self.current_node_id,
            variables=freeze_mapping(self.variables),
            completed_node_ids=frozenset(self.completed),
            unlocked_node_ids=frozenset(self.unlocked),
        )

    def _event_id(self, pending_index: int) -> str:
        return (
            f"event-{self.original.revision + 1}-"
            f"{self.original.event_cursor + pending_index + 1}"
        )

    def _variable_definition(self, variable_id: str) -> StoryVariableDefinition:
        for definition in self.program.variables:
            if definition.id == variable_id:
                return definition
        raise StoryRuntimeError(
            "runtime.unknown_variable",
            f"variable {variable_id!r} does not exist",
        )

    @staticmethod
    def _normalize_value(definition: StoryVariableDefinition, value: Any) -> Any:
        if definition.type in {VariableType.STRING_SET, VariableType.NODE_SET}:
            return frozenset(str(item) for item in value)
        return freeze_value(value)

    def _validate_state(self) -> None:
        branch_definitions = {
            definition.id: definition
            for definition in self.program.variables
            if definition.scope == VariableScope.BRANCH
        }
        global_definitions = {
            definition.id: definition
            for definition in self.program.variables
            if definition.scope == VariableScope.GLOBAL
        }
        if set(self.variables) != set(branch_definitions):
            raise StoryRuntimeError(
                "runtime.variable_schema",
                "runtime variables no longer match StoryProgram schema",
            )
        if set(self.global_variables) != set(global_definitions):
            raise StoryRuntimeError(
                "runtime.global_variable_schema",
                "global variables no longer match StoryProgram schema",
            )
        for values, definitions in (
            (self.variables, branch_definitions),
            (self.global_variables, global_definitions),
        ):
            for variable_id, value in values.items():
                if variable_value_is_valid(definitions[variable_id], value):
                    continue
                raise StoryRuntimeError("runtime.variable_type", variable_id)
        registered = set(self.program.character_registry.by_id)
        if not set(self.active_cast).issubset(registered):
            raise StoryRuntimeError(
                "runtime.cast_schema",
                "active cast contains an unregistered character",
            )


class StoryRuntime:
    def __init__(
        self,
        program: StoryProgram,
        *,
        semantic_definitions: Mapping[str, SemanticSignalDefinition] | None = None,
        cast_resolver: CastResolver | None = None,
        semantic_policy: SemanticSignalPolicy | None = None,
    ) -> None:
        self.program = program
        self.semantic_definitions = dict(semantic_definitions or {})
        self.cast_resolver = cast_resolver or CastResolver()
        self.semantic_policy = semantic_policy or SemanticSignalPolicy()
        self.condition_evaluator = ConditionEvaluator()
        self.rule_evaluator = RuleEvaluator()

    def start(
        self,
        command: StartStory,
        *,
        cast_context: CastResolutionContext | None = None,
        global_variables: Mapping[str, Any] | None = None,
    ) -> RuntimeResult:
        if not command.command_id:
            raise StoryRuntimeError("runtime.command_id", "command_id cannot be empty")
        initial = self.initial_state()
        transaction = self._transaction(
            initial,
            command.command_id,
            cast_context
            or CastResolutionContext(
                current_cast=self.program.character_registry.initial_cast
            ),
            self._prepare_global_variables(global_variables),
        )
        transaction.emit(StoryEventType.STORY_STARTED, storyId=self.program.story_id)
        transaction.unlock_node(self.program.start_node_id)
        transaction.enter_node(self.program.start_node_id)
        return transaction.commit()

    def initial_state(self) -> StoryState:
        """Create the revision-zero snapshot used before StoryStarted is applied."""
        variables = {
            definition.id: self._initial_value(definition)
            for definition in self.program.variables
            if definition.scope == VariableScope.BRANCH
        }
        registered = frozenset(self.program.character_registry.by_id)
        return StoryState(
            schema_version=1,
            story_id=self.program.story_id,
            story_version=self.program.story_version,
            program_source_hash=self.program.source_hash,
            revision=0,
            current_node_id=self.program.start_node_id,
            variables=freeze_mapping(variables),
            unlocked_node_ids=frozenset(),
            cast_state=CastState(
                registered_story_character_ids=registered,
                active_character_ids=(),
                offstage_character_ids=registered,
            ),
        )

    def execute(
        self,
        state: StoryState,
        command: RuntimeCommand,
        *,
        cast_context: CastResolutionContext | None = None,
        global_variables: Mapping[str, Any] | None = None,
    ) -> RuntimeResult:
        self._validate_command(state, command)
        transaction = self._transaction(
            state,
            command.command_id,
            cast_context or CastResolutionContext(),
            self._prepare_global_variables(global_variables),
        )
        if isinstance(command, SelectChoice):
            self._select_choice(transaction, command)
        elif isinstance(command, PerformIntent):
            self._perform_intent(transaction, command)
        elif isinstance(command, ApplySemanticSignals):
            self._apply_semantic_signals(transaction, command)
        elif isinstance(command, EnterNode):
            transaction.enter_node(command.node_id, require_unlocked=True)
        elif isinstance(command, CompleteNode):
            if command.node_id != state.current_node_id:
                raise StoryRuntimeError(
                    "runtime.node_mismatch",
                    "cannot complete a node that is not current",
                )
            transaction.complete_node(command.node_id)
        else:
            raise StoryRuntimeError("runtime.command", "unsupported command")
        transaction.recompute_unlocks()
        return transaction.commit()

    def _select_choice(
        self,
        transaction: _Transaction,
        command: SelectChoice,
    ) -> None:
        self._require_current_node(transaction.original, command.expected_node_id)
        node = self.program.nodes_by_id[transaction.current_node_id]
        choice = next(
            (item for item in node.choices if item.id == command.choice_id), None
        )
        if choice is None:
            raise StoryRuntimeError(
                "runtime.unknown_choice",
                f"choice {command.choice_id!r} is not available",
            )
        if not transaction.evaluate(choice.when):
            raise StoryRuntimeError(
                "runtime.choice_condition",
                f"choice {command.choice_id!r} is locked",
            )
        transaction.emit(
            StoryEventType.CHOICE_SELECTED,
            nodeId=node.id,
            choiceId=choice.id,
        )
        transaction.apply_effects(choice.effects)
        transaction.recompute_unlocks()
        if choice.goto is not None:
            transaction.complete_node(node.id)
            transaction.enter_node(choice.goto)

    def _perform_intent(
        self,
        transaction: _Transaction,
        command: PerformIntent,
    ) -> None:
        self._require_current_node(transaction.original, command.expected_node_id)
        node = self.program.nodes_by_id[transaction.current_node_id]
        intent = next(
            (item for item in node.freeform_intents if item.id == command.intent_id),
            None,
        )
        if intent is None:
            raise StoryRuntimeError(
                "runtime.unknown_intent",
                f"intent {command.intent_id!r} is not available",
            )
        if not transaction.evaluate(intent.when):
            raise StoryRuntimeError(
                "runtime.intent_condition",
                f"intent {command.intent_id!r} is locked",
            )
        transaction.emit(
            StoryEventType.INTENT_PERFORMED,
            nodeId=node.id,
            intentId=intent.id,
        )
        transaction.apply_effects(intent.effects)

    def _apply_semantic_signals(
        self,
        transaction: _Transaction,
        command: ApplySemanticSignals,
    ) -> None:
        policy_result = self.semantic_policy.evaluate(
            transaction.semantic_state,
            self.semantic_definitions,
            command.candidates,
            command.context,
        )
        transaction.semantic_state = policy_result.state
        for decision in policy_result.decisions:
            event_type = (
                StoryEventType.SEMANTIC_SIGNAL_ACCEPTED
                if decision.accepted
                else StoryEventType.SEMANTIC_SIGNAL_REJECTED
            )
            transaction.emit(
                event_type,
                signalId=decision.candidate.signal_id,
                reasonCode=decision.reason_code,
                sourceMessageId=decision.candidate.source_message_id,
                causeGroup=decision.candidate.cause_group,
                fingerprint=decision.candidate.fingerprint,
                turnId=command.context.turn_id,
                sceneId=command.context.scene_id,
                chapterId=command.context.chapter_id,
            )
            if decision.accepted:
                transaction.apply_effects(decision.effects, semantic=True)

    def _transaction(
        self,
        state: StoryState,
        command_id: str,
        cast_context: CastResolutionContext,
        global_variables: Mapping[str, Any],
    ) -> _Transaction:
        return _Transaction(
            program=self.program,
            state=state,
            global_variables=global_variables,
            command_id=command_id,
            cast_resolver=self.cast_resolver,
            cast_context=cast_context,
            condition_evaluator=self.condition_evaluator,
            rule_evaluator=self.rule_evaluator,
        )

    def _validate_command(self, state: StoryState, command: RuntimeCommand) -> None:
        if not command.command_id:
            raise StoryRuntimeError("runtime.command_id", "command_id cannot be empty")
        if (
            state.story_id != self.program.story_id
            or state.story_version != self.program.story_version
            or state.program_source_hash != self.program.source_hash
        ):
            raise StoryRuntimeError(
                "runtime.program_mismatch",
                "StoryState does not belong to this StoryProgram",
            )
        if command.expected_revision != state.revision:
            raise StoryRuntimeError(
                "runtime.revision_conflict",
                f"expected revision {command.expected_revision}, current revision is {state.revision}",
            )

    def _prepare_global_variables(
        self,
        supplied: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        definitions = {
            definition.id: definition
            for definition in self.program.variables
            if definition.scope == VariableScope.GLOBAL
        }
        values = (
            {
                definition.id: self._initial_value(definition)
                for definition in definitions.values()
            }
            if supplied is None
            else {str(key): freeze_value(value) for key, value in supplied.items()}
        )
        if set(values) != set(definitions):
            raise StoryRuntimeError(
                "runtime.global_variable_schema",
                "global variables no longer match StoryProgram schema",
            )
        for variable_id, value in values.items():
            if not variable_value_is_valid(definitions[variable_id], value):
                raise StoryRuntimeError("runtime.variable_type", variable_id)
        return freeze_mapping(values)

    @staticmethod
    def _require_current_node(state: StoryState, expected_node_id: str) -> None:
        if expected_node_id != state.current_node_id:
            raise StoryRuntimeError(
                "runtime.node_mismatch",
                f"expected node {expected_node_id!r}, current node is {state.current_node_id!r}",
            )

    @staticmethod
    def _initial_value(definition: StoryVariableDefinition) -> Any:
        if definition.type in {VariableType.STRING_SET, VariableType.NODE_SET}:
            return frozenset(str(item) for item in definition.initial)
        return freeze_value(definition.initial)
