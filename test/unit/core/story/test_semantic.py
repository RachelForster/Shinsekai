from __future__ import annotations

import math

from core.story import (
    EffectSpec,
    SemanticSignalCandidate,
    SemanticSignalContext,
    SemanticSignalDefinition,
    SemanticSignalPolicy,
    SemanticSignalState,
    SignalStrength,
    SpeechAct,
)


def _definition(**overrides) -> SemanticSignalDefinition:
    values = {
        "id": "respect-boundary",
        "effects_by_strength": {
            SignalStrength.WEAK: (EffectSpec("increment", ("trust.ling", 1)),),
            SignalStrength.MEDIUM: (EffectSpec("increment", ("trust.ling", 2)),),
            SignalStrength.STRONG: (EffectSpec("increment", ("trust.ling", 4)),),
        },
        "minimum_confidence": 0.8,
        "repeat_window": 20,
        "max_per_turn": 1,
        "max_per_scene": 3,
        "max_per_chapter": 10,
    }
    values.update(overrides)
    return SemanticSignalDefinition(**values)


def _candidate(**overrides) -> SemanticSignalCandidate:
    values = {
        "signal_id": "respect-boundary",
        "strength": SignalStrength.MEDIUM,
        "confidence": 0.95,
        "speech_act": SpeechAct.ENDORSEMENT,
        "fingerprint": "accepts-no",
        "source_message_id": "message-1",
        "cause_group": "message-1:ling:boundary",
    }
    values.update(overrides)
    return SemanticSignalCandidate(**values)


def _context(**overrides) -> SemanticSignalContext:
    values = {"turn_id": "turn-1", "scene_id": "gate", "chapter_id": "chapter-1"}
    values.update(overrides)
    return SemanticSignalContext(**values)


def test_accepts_registered_signal_and_maps_strength_to_effects() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (_candidate(),),
        _context(),
    )

    decision = result.decisions[0]
    assert decision.accepted
    assert decision.effects == (EffectSpec("increment", ("trust.ling", 2)),)
    assert result.state.sequence == 1


def test_rejects_unknown_signal_without_inventing_effects() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {},
        (_candidate(signal_id="invented"),),
        _context(),
    )

    assert not result.decisions[0].accepted
    assert result.decisions[0].reason_code == "unknown-signal"
    assert result.state.sequence == 0


def test_rejects_question_speech_act() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (_candidate(speech_act=SpeechAct.QUESTION),),
        _context(),
    )

    assert result.decisions[0].reason_code == "speech-act-rejected"


def test_rejects_duplicate_fingerprint_in_repeat_window() -> None:
    policy = SemanticSignalPolicy()
    first = policy.evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (_candidate(),),
        _context(),
    )
    second = policy.evaluate(
        first.state,
        {"respect-boundary": _definition()},
        (_candidate(source_message_id="message-2", cause_group="message-2:boundary"),),
        _context(turn_id="turn-2"),
    )

    assert second.decisions[0].reason_code == "duplicate-fingerprint"


def test_rejects_suppressed_cause_group() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (_candidate(),),
        _context(suppressed_cause_groups=frozenset({"message-1:ling:boundary"})),
    )

    assert result.decisions[0].reason_code == "duplicate-cause-group"


def test_enforces_per_turn_limit_within_one_batch() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (
            _candidate(),
            _candidate(
                fingerprint="different",
                source_message_id="message-2",
                cause_group="message-2:boundary",
            ),
        ),
        _context(),
    )

    assert [decision.reason_code for decision in result.decisions] == [
        "accepted",
        "rate-limited",
    ]


def test_rejects_non_finite_confidence() -> None:
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        {"respect-boundary": _definition()},
        (_candidate(confidence=math.nan),),
        _context(),
    )

    assert result.decisions[0].reason_code == "invalid-confidence"
    assert result.state.sequence == 0


def test_limits_different_signals_that_target_the_same_metric() -> None:
    definitions = {
        signal_id: _definition(id=signal_id)
        for signal_id in ("respect-boundary", "protect-friend")
    }
    result = SemanticSignalPolicy().evaluate(
        SemanticSignalState(),
        definitions,
        (
            _candidate(),
            _candidate(
                signal_id="protect-friend",
                fingerprint="protects-friend",
                source_message_id="message-2",
                cause_group="message-2:protect",
            ),
        ),
        _context(),
    )

    assert [decision.reason_code for decision in result.decisions] == [
        "accepted",
        "rate-limited",
    ]


def test_usage_remains_bounded_when_context_ids_change() -> None:
    policy = SemanticSignalPolicy()
    definition = _definition(
        repeat_window=0,
        max_per_turn=100,
        max_per_scene=100,
        max_per_chapter=100,
    )
    state = SemanticSignalState()
    for index in range(20):
        state = policy.evaluate(
            state,
            {definition.id: definition},
            (
                _candidate(
                    fingerprint=f"fingerprint-{index}",
                    source_message_id=f"message-{index}",
                    cause_group=f"cause-{index}",
                ),
            ),
            _context(turn_id=f"turn-{index}", scene_id=f"scene-{index}"),
        ).state

    assert state.usage == {
        "turn:trust.ling": 1,
        "scene:trust.ling": 1,
        "chapter:trust.ling": 20,
    }


def test_definition_deep_freezes_strength_effects() -> None:
    effects = {
        SignalStrength.WEAK: (EffectSpec("increment", ("trust.ling", 1)),),
        SignalStrength.MEDIUM: (EffectSpec("increment", ("trust.ling", 2)),),
        SignalStrength.STRONG: (EffectSpec("increment", ("trust.ling", 4)),),
    }
    definition = _definition(effects_by_strength=effects)
    effects[SignalStrength.MEDIUM] = (EffectSpec("increment", ("trust.ling", 99)),)

    assert definition.effects_by_strength[SignalStrength.MEDIUM] == (
        EffectSpec("increment", ("trust.ling", 2)),
    )
