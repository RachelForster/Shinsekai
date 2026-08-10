from __future__ import annotations

from dataclasses import replace

import pytest

from core.story import (
    ApplySemanticSignals,
    EnterNode,
    EffectSpec,
    PerformIntent,
    SelectChoice,
    SemanticSignalCandidate,
    SemanticSignalContext,
    SignalStrength,
    SpeechAct,
    StartStory,
    StoryCompiler,
    StoryCompileError,
    StoryEventType,
    StoryEvent,
    StoryEventReplayError,
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
    return StoryRuntime(program)


def test_start_story_initializes_authoritative_state_and_cast(runtime) -> None:
    result = runtime.start(StartStory("start-1"))

    assert result.state.revision == 1
    assert result.state.current_node_id == "transfer-day"
    assert result.state.variables["trust.ling"] == 0
    assert result.state.variables["inventory"] == frozenset({"old_school_key"})
    assert result.state.cast_state.active_character_ids == ("ling",)
    assert result.state.cast_state.resolved_for_node_id == "transfer-day"
    assert result.cast_plans[0].required_character_ids == ("ling",)
    assert [event.type for event in result.events] == [
        StoryEventType.STORY_STARTED,
        StoryEventType.NODE_UNLOCKED,
        StoryEventType.CAST_RESOLVED,
        StoryEventType.NODE_ENTERED,
    ]
    with pytest.raises(TypeError):
        runtime.semantic_definitions["respect-boundary"] = None


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
        program=runtime.program,
    )

    assert replayed == ending.state


def test_repeated_command_is_rejected_by_revision_boundary(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    command = SelectChoice(
        command_id="choice-1",
        expected_revision=started.state.revision,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )
    first = runtime.execute(started.state, command)

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(first.state, command)

    assert exc_info.value.code == "runtime.revision_conflict"


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


def test_runtime_commands_are_rejected_before_story_started(runtime) -> None:
    initial = runtime.initial_state()

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(
            initial,
            SelectChoice(
                command_id="choice-before-start",
                expected_revision=0,
                choice_id="prepare-investigation",
                expected_node_id="transfer-day",
            ),
        )

    assert exc_info.value.code == "runtime.not_started"


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
        program=runtime.program,
    )
    assert replayed == result.state


def test_semantic_effect_cannot_target_unpublished_metric() -> None:
    source = campus_mystery_source()
    for effects in source["semanticSignals"][0]["effectsByStrength"].values():
        effects[:] = [{"set": ["flags.arrived_old_school", True]}]

    with pytest.raises(StoryCompileError) as exc_info:
        StoryCompiler().compile(parse_story_project(source))

    assert {item.code for item in exc_info.value.diagnostics} == {
        "semantic.target_disabled"
    }


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
        program=runtime.program,
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


def test_direct_enter_rejects_locked_ending(runtime) -> None:
    started = runtime.start(StartStory("start-1"))

    with pytest.raises(StoryRuntimeError) as exc_info:
        runtime.execute(
            started.state,
            EnterNode(
                command_id="skip-ending",
                expected_revision=started.state.revision,
                node_id="truth-ending",
            ),
        )

    assert exc_info.value.code == "runtime.node_locked"
    assert started.state.current_node_id == "transfer-day"


def test_replay_rejects_undeclared_variable(runtime) -> None:
    started = runtime.start(StartStory("start-1"))
    next_cursor = started.state.event_cursor + 1
    corrupted = StoryEvent(
        id=f"event-2-{next_cursor}",
        revision=2,
        type=StoryEventType.VARIABLE_CHANGED,
        payload={"variableId": "invented", "previous": None, "current": "bad"},
        cause_command_id="corrupt",
    )

    with pytest.raises(StoryEventReplayError, match="undeclared branch variable"):
        StoryEventReplayer().replay(
            started.state,
            (corrupted,),
            program=runtime.program,
        )


def test_replay_rejects_runtime_events_before_story_started(runtime) -> None:
    event = StoryEvent(
        id="event-1-1",
        revision=1,
        type=StoryEventType.COMMAND_PROCESSED,
        payload={},
        cause_command_id="before-start",
    )

    with pytest.raises(StoryEventReplayError, match="StoryStarted"):
        StoryEventReplayer().replay(
            runtime.initial_state(),
            (event,),
            program=runtime.program,
        )


def test_replay_rejects_incomplete_startup_revision(runtime) -> None:
    event = StoryEvent(
        id="event-1-1",
        revision=1,
        type=StoryEventType.STORY_STARTED,
        payload={"storyId": runtime.program.story_id},
        cause_command_id="incomplete-start",
    )

    with pytest.raises(StoryEventReplayError, match="startup revision"):
        StoryEventReplayer().replay(
            runtime.initial_state(),
            (event,),
            program=runtime.program,
        )


def test_global_effects_are_planned_without_entering_branch_state() -> None:
    source = campus_mystery_source()
    source["semanticSignals"] = []
    source["variables"]["trust.ling"]["scope"] = "global"
    program = StoryCompiler().compile(parse_story_project(source))
    runtime = StoryRuntime(program)
    started = runtime.start(
        StartStory("start-1"),
        global_variables={"trust.ling": 0},
    )

    result = runtime.execute(
        started.state,
        SelectChoice(
            command_id="choice-1",
            expected_revision=started.state.revision,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        ),
        global_variables={"trust.ling": 0},
    )

    assert "trust.ling" not in result.state.variables
    assert result.global_effects == (EffectSpec("increment", ("trust.ling", 10)),)
    assert result.state.current_node_id == "old-school-gate"


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
