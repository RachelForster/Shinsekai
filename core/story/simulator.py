"""Bounded deterministic path exploration for compiled story programs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cast import CastResolutionContext, CastResolutionError
from .commands import EnterNode, PerformIntent, SelectChoice, StartStory
from .compiler import canonical_json
from .runtime import StoryRuntime, StoryRuntimeError
from .state import StoryState


@dataclass(frozen=True, slots=True)
class SimulationReport:
    explored_states: int
    reachable_node_ids: frozenset[str]
    ending_paths: Mapping[str, tuple[str, ...]]
    dead_end_node_ids: frozenset[str]
    cast_resolution_failures: Mapping[str, str]
    truncated: bool


class StorySimulator:
    def __init__(
        self,
        runtime: StoryRuntime,
        *,
        max_states: int = 1_000,
        max_depth: int = 100,
    ) -> None:
        if max_states < 1 or max_depth < 1:
            raise ValueError("simulation limits must be positive")
        self.runtime = runtime
        self.max_states = max_states
        self.max_depth = max_depth

    def simulate(
        self,
        *,
        cast_context: CastResolutionContext | None = None,
    ) -> SimulationReport:
        resolution_context = cast_context or CastResolutionContext(
            current_cast=self.runtime.program.character_registry.initial_cast
        )
        cast_failures = self._check_cast_resolution(resolution_context)
        started = self.runtime.start(
            StartStory("simulation-start"),
            cast_context=resolution_context,
        )
        queue = deque([(started.state, tuple(), 0)])
        visited: set[str] = set()
        reachable: set[str] = set()
        endings: dict[str, tuple[str, ...]] = {}
        dead_ends: set[str] = set()
        truncated = False

        while queue:
            state, path, depth = queue.popleft()
            signature = self._state_signature(state)
            if signature in visited:
                continue
            if len(visited) >= self.max_states:
                truncated = True
                break
            visited.add(signature)
            reachable.add(state.current_node_id)
            node = self.runtime.program.nodes_by_id[state.current_node_id]
            if node.type == "ending":
                endings.setdefault(node.id, path)
                continue
            if depth >= self.max_depth:
                truncated = True
                continue

            next_states: list[tuple[StoryState, tuple[str, ...], int]] = []
            for index, choice in enumerate(node.choices):
                command = SelectChoice(
                    command_id=f"sim-{len(visited)}-choice-{index}",
                    expected_revision=state.revision,
                    choice_id=choice.id,
                    expected_node_id=state.current_node_id,
                )
                result = self._try_execute(state, command, cast_context)
                if result is not None:
                    next_states.append(
                        (result, (*path, f"choice:{node.id}/{choice.id}"), depth + 1)
                    )
            for index, intent in enumerate(node.freeform_intents):
                command = PerformIntent(
                    command_id=f"sim-{len(visited)}-intent-{index}",
                    expected_revision=state.revision,
                    intent_id=intent.id,
                    expected_node_id=state.current_node_id,
                )
                result = self._try_execute(state, command, cast_context)
                if result is not None:
                    next_states.append(
                        (result, (*path, f"intent:{node.id}/{intent.id}"), depth + 1)
                    )
            enterable_node_ids = sorted(
                state.unlocked_node_ids.difference({state.current_node_id})
            )
            for index, node_id in enumerate(enterable_node_ids):
                command = EnterNode(
                    command_id=f"sim-{len(visited)}-enter-{index}",
                    expected_revision=state.revision,
                    node_id=node_id,
                )
                result = self._try_execute(state, command, cast_context)
                if result is not None:
                    next_states.append((result, (*path, f"enter:{node_id}"), depth + 1))
            if not next_states:
                dead_ends.add(node.id)
            queue.extend(next_states)

        return SimulationReport(
            explored_states=len(visited),
            reachable_node_ids=frozenset(reachable),
            ending_paths=MappingProxyType(endings),
            dead_end_node_ids=frozenset(dead_ends),
            cast_resolution_failures=MappingProxyType(cast_failures),
            truncated=truncated,
        )

    def _check_cast_resolution(
        self,
        context: CastResolutionContext,
    ) -> dict[str, str]:
        failures: dict[str, str] = {}
        registry = self.runtime.program.character_registry
        for node in self.runtime.program.nodes:
            try:
                self.runtime.cast_resolver.resolve(
                    registry,
                    node.cast_policy,
                    context,
                )
            except CastResolutionError as error:
                failures[node.id] = error.code
        return failures

    def _try_execute(
        self,
        state: StoryState,
        command: SelectChoice | PerformIntent | EnterNode,
        cast_context: CastResolutionContext | None,
    ) -> StoryState | None:
        try:
            return self.runtime.execute(
                state,
                command,
                cast_context=cast_context,
            ).state
        except StoryRuntimeError:
            return None

    @staticmethod
    def _state_signature(state: StoryState) -> str:
        return canonical_json(
            {
                "node": state.current_node_id,
                "variables": state.variables,
                "completed": sorted(state.completed_node_ids),
                "unlocked": sorted(state.unlocked_node_ids),
                "activeCast": state.cast_state.active_character_ids,
                "roles": state.cast_state.role_bindings,
                "semanticSequence": state.semantic_signal_state.sequence,
            }
        )
