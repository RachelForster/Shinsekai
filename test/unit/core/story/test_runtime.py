from __future__ import annotations

from dataclasses import replace

import pytest

from core.story import (
    ApplySemanticSignals,
    EffectSpec,
    PerformIntent,
    SelectChoice,
    SemanticSignalCandidate,
    SemanticSignalContext,
    SemanticSignalDefinition,
    SignalStrength,
    SpeechAct,
    StartStory,
    StoryCompiler,
    StoryEventType,
    StoryEventReplayer,
    StoryRuntime,
    StoryRuntimeError,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


@pytest.fixture
def program():
    return StoryCompiler().compile(parse_story_project(campus_mystery_source()))


@pytest.fixture
def runtime(program):
    definition = SemanticSignalDefinition(
        id="respect-boundary",
        effects_by_strength={
            SignalStrength.MEDIUM: (EffectSpec("increment", ("trust.ling", 2)),)
        },
    )
    return StoryRuntime(program, semantic_definitions={definition.id: definition})


def test_start_story_initializes_authoritative_state_and_cast(runtime) -> None:
    result = runtime.start(StartStory("start-1"))

    assert result.state.revision == 1
    assert result.state.current_node_id == "transfer-day"
    assert result.state.variables["trust.ling"] == 0
    assert result.state.variables["inventory"] == frozenset({"old_school_key"})
    assert result.state.cast_state.active_character_ids == ("ling",)
    assert result.state.cast_state.resolved_for_node_id == "transfer-day"
    assert [event.type for event in result.events] == [
        StoryEventType.STORY_STARTED,
        StoryEventType.NODE_UNLOCKED,
        StoryEventType.CAST_RESOLVED,
        StoryEventType.NODE_ENTERED,
    ]


def test_choice_transaction_applies_effect_unlocks_and_enters_target(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    command = SelectChoice(
        command_id="choice-1",
        expected_revision=started.state.revision,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )

    result = runtime.execute(started.state, command)

    assert result.state.revision == 2
    assert result.state.variables["trust.ling"] == 10
    assert result.state.variables["flags.arrived_old_school"] is True
    assert result.state.current_node_id == "old-school-gate"
    assert "transfer-day" in result.state.completed_node_ids
    assert "old-school-gate" in result.state.unlocked_node_ids
    assert result.state.cast_state.active_character_ids == (
        "ling",
        "detective-zhou",
    )
    assert result.state.cast_state.role_bindings == {"authority": "detective-zhou"}
    assert StoryEventType.NODE_UNLOCKED in {event.type for event in result.events}


def test_choice_can_reach_ending_and_consume_item(runtime) -> None:
    gate = _reach_gate(runtime)
    command = SelectChoice(
        command_id="choice-ending",
        expected_revision=gate.revision,
        choice_id="enter-with-key",
        expected_node_id="old-school-gate",
    )

    result = runtime.execute(gate, command)

    assert result.state.current_node_id == "truth-ending"
    assert result.state.variables["inventory"] == frozenset()
    assert result.state.cast_state.active_character_ids == ("ling",)
    assert StoryEventType.ENDING_REACHED in {event.type for event in result.events}


def test_domain_events_replay_to_identical_ending_state(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    gate = runtime.execute(
        started.state,
        SelectChoice(
            command_id="choice-1",
            expected_revision=started.state.revision,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        ),
    )
    ending = runtime.execute(
        gate.state,
        SelectChoice(
            command_id="choice-ending",
            expected_revision=gate.state.revision,
            choice_id="enter-with-key",
            expected_node_id="old-school-gate",
        ),
    )

    replayed = StoryEventReplayer().replay(
        runtime.initial_state(),
        (*started.events, *gate.events, *ending.events),
    )

    assert replayed == ending.state


def test_duplicate_command_is_idempotent(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    command = SelectChoice(
        command_id="choice-1",
        expected_revision=started.state.revision,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )
    first = runtime.execute(started.state, command)

    duplicate = runtime.execute(first.state, command)

    assert duplicate.duplicate
    assert duplicate.state is first.state
    assert duplicate.events == ()


def test_stale_revision_is_rejected_without_mutating_state(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    command = SelectChoice(
        command_id="stale-choice",
        expected_revision=0,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(started.state, command)

    assert exc_info.value.code == "runtime.revision_conflict"
    assert started.state.variables["trust.ling"] == 0
    assert started.state.revision == 1


def test_failed_transition_rolls_back_all_pending_effects(program) -> None:
    start = program.nodes[0]
    choice = replace(start.choices[0], effects=())
    broken_start = replace(start, choices=(choice,))
    broken_program = replace(program, nodes=(broken_start,) + program.nodes[1:])
    runtime = StoryRuntime(broken_program)
    started = runtime.start(StartStory("start-1"))
    command = SelectChoice(
        command_id="choice-1",
        expected_revision=started.state.revision,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(started.state, command)

    assert exc_info.value.code == "runtime.enter_condition"
    assert started.state.variables["trust.ling"] == 0
    assert started.state.completed_node_ids == frozenset()
    assert started.state.revision == 1


def test_freeform_intent_executes_registered_effect(runtime) -> None:
    gate = _reach_gate(runtime)
    command = PerformIntent(
        command_id="intent-1",
        expected_revision=gate.revision,
        intent_id="reassure-ling",
        expected_node_id="old-school-gate",
    )

    result = runtime.execute(gate, command)

    assert result.state.variables["trust.ling"] == 15
    assert result.state.current_node_id == "old-school-gate"
    assert StoryEventType.INTENT_PERFORMED in {event.type for event in result.events}


def test_semantic_signal_changes_only_published_metric(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    candidate = SemanticSignalCandidate(
        signal_id="respect-boundary",
        strength=SignalStrength.MEDIUM,
        confidence=0.95,
        speech_act=SpeechAct.ENDORSEMENT,
        fingerprint="accepts-no",
        source_message_id="message-1",
        cause_group="message-1:ling:boundary",
    )
    command = ApplySemanticSignals(
        command_id="signals-1",
        expected_revision=started.state.revision,
        candidates=(candidate,),
        context=SemanticSignalContext("turn-1", "transfer-day", "chapter-1"),
    )

    result = runtime.execute(started.state, command)

    assert result.state.variables["trust.ling"] == 2
    assert StoryEventType.SEMANTIC_SIGNAL_ACCEPTED in {
        event.type for event in result.events
    }
    assert StoryEventType.METRIC_CHANGED in {event.type for event in result.events}
    replayed = StoryEventReplayer().replay(
        runtime.initial_state(),
        (*started.events, *result.events),
    )
    assert replayed == result.state


def test_semantic_effect_cannot_modify_non_semantic_variable(program) -> None:
    definition = SemanticSignalDefinition(
        id="invented-flag",
        effects_by_strength={
            SignalStrength.MEDIUM: (
                EffectSpec("set", ("flags.arrived_old_school", True)),
            )
        },
    )
    runtime = StoryRuntime(program, semantic_definitions={definition.id: definition})
    started = runtime.start(StartStory("start-1"))
    candidate = SemanticSignalCandidate(
        signal_id=definition.id,
        strength=SignalStrength.MEDIUM,
        confidence=0.95,
        speech_act=SpeechAct.ENDORSEMENT,
        fingerprint="flag",
        source_message_id="message-1",
        cause_group="message-1:flag",
    )
    command = ApplySemanticSignals(
        command_id="signals-1",
        expected_revision=started.state.revision,
        candidates=(candidate,),
        context=SemanticSignalContext("turn-1", "transfer-day", "chapter-1"),
    )

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(started.state, command)

    assert exc_info.value.code == "runtime.semantic_target"
    assert started.state.variables["flags.arrived_old_school"] is False
    assert started.state.semantic_signal_state.sequence == 0


def test_no_effect_command_emits_replayable_revision_event(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    command = ApplySemanticSignals(
        command_id="signals-empty",
        expected_revision=started.state.revision,
        candidates=(),
        context=SemanticSignalContext("turn-1", "transfer-day", "chapter-1"),
    )

    result = runtime.execute(started.state, command)
    replayed = StoryEventReplayer().replay(
        runtime.initial_state(),
        (*started.events, *result.events),
    )

    assert [event.type for event in result.events] == [StoryEventType.COMMAND_PROCESSED]
    assert replayed == result.state


def test_state_from_different_program_is_rejected(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    mismatched = replace(started.state, program_source_hash="different")
    command = PerformIntent(
        command_id="intent-1",
        expected_revision=mismatched.revision,
        intent_id="missing",
        expected_node_id="transfer-day",
    )

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(mismatched, command)

    assert exc_info.value.code == "runtime.program_mismatch"


def _reach_gate(runtime: StoryRuntime):
    started = runtime.start(StartStory("start-1"))
    return runtime.execute(
        started.state,
        SelectChoice(
            command_id="choice-1",
            expected_revision=started.state.revision,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        ),
    ).state
