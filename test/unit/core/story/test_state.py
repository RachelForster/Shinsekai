from __future__ import annotations

import pytest

from core.story import CastState, SemanticSignalState, StoryState


def test_runtime_state_construction_deep_freezes_mutable_inputs() -> None:
    variables = {"inventory": ["key"], "metadata": {"values": [1]}}
    active_character_ids = ["ling"]
    role_bindings = {"companion": "ling"}
    usage = {"turn:trust.ling": 1}
    fingerprints = [["respect-boundary:fingerprint", 1]]
    cause_groups = ["message-1:ling:boundary"]
    semantic_state = SemanticSignalState(
        usage=usage,
        recent_fingerprints=fingerprints,
        accepted_cause_groups=cause_groups,
    )
    cast_state = CastState(
        registered_story_character_ids=["ling"],
        active_character_ids=active_character_ids,
        role_bindings=role_bindings,
    )
    state = StoryState(
        schema_version=1,
        story_id="story",
        story_version=1,
        program_source_hash="hash",
        revision=1,
        current_node_id="start",
        variables=variables,
        semantic_signal_state=semantic_state,
        cast_state=cast_state,
    )

    variables["inventory"].append("forged")
    variables["metadata"]["values"].append(2)
    active_character_ids.append("forged")
    role_bindings["companion"] = "forged"
    usage["turn:trust.ling"] = 99
    fingerprints.append(["forged", 2])
    cause_groups.append("forged")

    assert state.variables["inventory"] == ("key",)
    assert state.variables["metadata"]["values"] == (1,)
    assert state.cast_state.registered_story_character_ids == {"ling"}
    assert state.cast_state.active_character_ids == ("ling",)
    assert state.cast_state.role_bindings == {"companion": "ling"}
    assert state.semantic_signal_state.usage == {"turn:trust.ling": 1}
    assert state.semantic_signal_state.recent_fingerprints == (
        ("respect-boundary:fingerprint", 1),
    )
    assert state.semantic_signal_state.accepted_cause_groups == (
        "message-1:ling:boundary",
    )
    with pytest.raises(TypeError):
        state.variables["inventory"] = ()
