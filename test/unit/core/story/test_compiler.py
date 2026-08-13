from __future__ import annotations

from dataclasses import replace
import json

import pytest

from core.story import (
    CandidateConditionSpec,
    CharacterSource,
    CharacterSourceType,
    ConditionSpec,
    EffectSpec,
    PortRef,
    RuleEdge,
    RuleGraph,
    RuleNode,
    SignalStrength,
    StoryCompileError,
    StoryCompiler,
    parse_story_project,
)
from core.story.compiler import story_program_json

from .story_fixtures import campus_mystery_source


@pytest.fixture
def project():
    return parse_story_project(campus_mystery_source())


def test_compile_produces_stable_program_and_source_map(project) -> None:
    compiler = StoryCompiler()

    first = compiler.compile(project)
    second = compiler.compile(project)

    assert first == second
    assert len(first.source_hash) == 64
    assert first.start_node_id == "transfer-day"
    assert first.source_map["node:old-school-gate"].endswith("nodes[1]")
    assert first.source_map["choice:old-school-gate/enter-with-key"].endswith(
        "nodes[1].choices[0]"
    )
    assert story_program_json(first) == story_program_json(second)
    assert json.loads(story_program_json(first))["story_id"] == "campus-mystery"
    assert first.semantic_signals_by_id["respect-boundary"].effects_by_strength[
        SignalStrength.MEDIUM
    ] == (
        EffectSpec("increment", ("trust.ling", 2)),
    )


def test_semantic_definitions_contribute_to_source_hash() -> None:
    original_source = campus_mystery_source()
    changed_source = campus_mystery_source()
    changed_source["semanticSignals"][0]["effectsByStrength"]["medium"] = [
        {"increment": ["trust.ling", 3]}
    ]

    original = StoryCompiler().compile(parse_story_project(original_source))
    changed = StoryCompiler().compile(parse_story_project(changed_source))

    assert original.source_hash != changed.source_hash


def test_compiled_program_is_deeply_immutable_and_detached(project) -> None:
    mutable_config = {
        "variable": "trust.ling",
        "display": {"labels": ["before"]},
    }
    changed_rule = replace(project.rule_graph.nodes[0], config=mutable_config)
    changed = replace(
        project,
        rule_graph=replace(
            project.rule_graph,
            nodes=(changed_rule,) + project.rule_graph.nodes[1:],
        ),
    )
    program = StoryCompiler().compile(changed)
    serialized = story_program_json(program)
    source_hash = program.source_hash

    mutable_config["display"]["labels"].append("after")

    assert program.rule_graph is not changed.rule_graph
    assert program.rule_graph.nodes[0].config is not changed_rule.config
    assert story_program_json(program) == serialized
    assert program.source_hash == source_hash
    with pytest.raises(TypeError):
        changed.rule_graph.nodes[0].config["variable"] = "other"
    with pytest.raises(TypeError):
        program.rule_graph.nodes[0].config["variable"] = "other"
    with pytest.raises(TypeError):
        program.source_map["node:transfer-day"] = "changed"
    with pytest.raises(TypeError):
        program.semantic_signals_by_id["respect-boundary"].effects_by_strength[
            SignalStrength.MEDIUM
        ] = ()


def test_compiled_program_keeps_only_exposed_context(project) -> None:
    start = replace(
        project.narrative_graph.nodes[0],
        exposed_context={"summary": "Visible", "facts": ["one"]},
        locked_context={"secret": "Hidden"},
    )
    changed = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(start,) + project.narrative_graph.nodes[1:],
        ),
    )

    program = StoryCompiler().compile(changed)
    serialized_node = json.loads(story_program_json(program))["nodes"][0]

    assert serialized_node["exposed_context"] == {
        "summary": "Visible",
        "facts": ["one"],
    }
    assert "locked_context" not in serialized_node
    assert program.nodes[0].exposed_context["facts"] == ("one",)


def test_compile_rejects_missing_start_node(project) -> None:
    broken_graph = replace(project.narrative_graph, start_node_id="missing")
    broken = replace(project, narrative_graph=broken_graph)

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert not result.ok
    assert "narrative.missing_start" in {item.code for item in result.diagnostics}
    with pytest.raises(StoryCompileError):
        StoryCompiler().compile(broken)


def test_compile_rejects_missing_choice_target(project) -> None:
    start = project.narrative_graph.nodes[0]
    broken_choice = replace(start.choices[0], goto="missing")
    broken_start = replace(start, choices=(broken_choice,))
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(broken_start,) + project.narrative_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "narrative.missing_target" in {item.code for item in result.diagnostics}


def test_compile_rejects_unknown_variable_in_inline_effect(project) -> None:
    start = project.narrative_graph.nodes[0]
    broken_choice = replace(
        start.choices[0],
        effects=(EffectSpec("increment", ("missing.metric", 1)),),
    )
    broken_start = replace(start, choices=(broken_choice,))
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(broken_start,) + project.narrative_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "effect.unknown_variable" in {item.code for item in result.diagnostics}


def test_compile_rejects_invalid_rule_port_type(project) -> None:
    metric = project.rule_graph.nodes[0]
    unlock = project.rule_graph.nodes[2]
    broken_graph = RuleGraph(
        nodes=(metric, unlock),
        edges=(
            RuleEdge(
                source=PortRef(metric.id, "value"),
                target=PortRef(unlock.id, "when"),
            ),
        ),
    )
    broken = replace(project, rule_graph=broken_graph)

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "rule.port_type" in {item.code for item in result.diagnostics}


@pytest.mark.parametrize(
    "config",
    (
        {"operator": "gt", "value": 10},
        {"operator": "gte", "value": "10"},
    ),
)
def test_compile_rejects_invalid_compare_config(project, config) -> None:
    metric = project.rule_graph.nodes[0]
    compare = RuleNode("compare-threshold", "compare", config)
    unlock = project.rule_graph.nodes[2]
    graph = RuleGraph(
        nodes=(metric, compare, unlock),
        edges=(
            RuleEdge(
                PortRef(metric.id, "value"),
                PortRef(compare.id, "input"),
            ),
            RuleEdge(
                PortRef(compare.id, "result"),
                PortRef(unlock.id, "when"),
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(
        replace(project, rule_graph=graph)
    )

    assert not result.ok
    assert "rule.invalid_config" in {item.code for item in result.diagnostics}


def test_compile_rejects_rule_cycle(project) -> None:
    left = RuleNode("left", "not", {})
    right = RuleNode("right", "not", {})
    cycle = RuleGraph(
        nodes=(left, right),
        edges=(
            RuleEdge(PortRef("left", "result"), PortRef("right", "input")),
            RuleEdge(PortRef("right", "result"), PortRef("left", "input")),
        ),
    )
    broken = replace(project, rule_graph=cycle)

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "rule.cycle" in {item.code for item in result.diagnostics}


def test_compile_rejects_unregistered_required_character(project) -> None:
    gate = project.narrative_graph.nodes[1]
    broken_policy = replace(gate.cast_policy, required=("ghost",))
    broken_gate = replace(gate, cast_policy=broken_policy)
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "cast.unknown_character" in {item.code for item in result.diagnostics}


def test_compile_rejects_embedded_character_path_escape(project) -> None:
    character = project.character_registry.characters[1]
    broken_character = replace(
        character,
        source=CharacterSource(
            type=CharacterSourceType.EMBEDDED,
            path="../outside.yaml",
        ),
    )
    broken_registry = replace(
        project.character_registry,
        characters=(project.character_registry.characters[0], broken_character),
    )
    broken = replace(project, character_registry=broken_registry)

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "character.path_escape" in {item.code for item in result.diagnostics}


def test_compile_rejects_windows_drive_character_path(project) -> None:
    character = project.character_registry.characters[1]
    broken_character = replace(
        character,
        source=CharacterSource(
            type=CharacterSourceType.EMBEDDED,
            path=r"C:\outside.yaml",
        ),
    )
    broken_registry = replace(
        project.character_registry,
        characters=(project.character_registry.characters[0], broken_character),
    )

    result = StoryCompiler().compile_with_diagnostics(
        replace(project, character_registry=broken_registry)
    )

    assert "character.path_escape" in {item.code for item in result.diagnostics}


def test_published_unpinned_local_character_is_error(project) -> None:
    character = project.character_registry.characters[0]
    broken_character = replace(
        character,
        source=replace(character.source, revision=None),
    )
    changed = replace(
        project,
        character_registry=replace(
            project.character_registry,
            characters=(broken_character, project.character_registry.characters[1]),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert not result.ok
    diagnostic = next(
        item for item in result.diagnostics if item.code == "character.unpinned"
    )
    assert diagnostic.severity.value == "error"
    with pytest.raises(StoryCompileError):
        StoryCompiler().compile(changed)


def test_published_local_character_accepts_content_digest_pin(project) -> None:
    character = project.character_registry.characters[0]
    pinned_character = replace(
        character,
        source=replace(
            character.source,
            revision=None,
            content_digest="sha256:test-ling",
        ),
    )
    changed = replace(
        project,
        character_registry=replace(
            project.character_registry,
            characters=(pinned_character, project.character_registry.characters[1]),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert result.ok


def test_compile_rejects_forbidden_only_required_role_candidate(project) -> None:
    gate = project.narrative_graph.nodes[1]
    broken_policy = replace(gate.cast_policy, forbidden=("detective-zhou",))
    broken_gate = replace(gate, cast_policy=broken_policy)
    changed = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert "cast.unresolved_role" in {item.code for item in result.diagnostics}


def test_compile_validates_required_role_candidate_count(project) -> None:
    gate = project.narrative_graph.nodes[1]
    required_role = replace(gate.cast_policy.required_roles[0], count=2)
    broken_policy = replace(gate.cast_policy, required_roles=(required_role,))
    broken_gate = replace(gate, cast_policy=broken_policy)
    changed = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert "cast.unresolved_role" in {item.code for item in result.diagnostics}


def test_compile_diagnoses_non_string_rule_config_keys(project) -> None:
    broken_rule = replace(project.rule_graph.nodes[0], config={1: "a", "x": "b"})
    changed = replace(
        project,
        rule_graph=replace(
            project.rule_graph,
            nodes=(broken_rule,) + project.rule_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert not result.ok
    assert "schema.mapping_key" in {item.code for item in result.diagnostics}
    with pytest.raises(StoryCompileError) as exc_info:
        StoryCompiler().compile(changed)
    assert "schema.mapping_key" in {item.code for item in exc_info.value.diagnostics}


def test_compile_rejects_candidate_predicate_in_narrative_condition(project) -> None:
    start = replace(
        project.narrative_graph.nodes[0],
        enter_when=ConditionSpec("available", (True,)),
    )
    changed = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(start,) + project.narrative_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert "condition.operator" in {item.code for item in result.diagnostics}


def test_compile_rejects_narrative_condition_in_candidate_query(project) -> None:
    gate = project.narrative_graph.nodes[1]
    query = replace(
        gate.cast_policy.optional_query,
        conditions=(CandidateConditionSpec("gte", ("missing.metric", 1)),),
    )
    broken_gate = replace(
        gate,
        cast_policy=replace(gate.cast_policy, optional_query=query),
    )
    changed = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert "cast.condition_operator" in {item.code for item in result.diagnostics}


def test_compile_validates_condition_variable_type(project) -> None:
    gate = project.narrative_graph.nodes[1]
    broken_gate = replace(
        gate,
        enter_when=ConditionSpec("gte", ("flags.arrived_old_school", 1)),
    )
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "condition.invalid_numeric" in {item.code for item in result.diagnostics}


def test_compile_validates_effect_value_type(project) -> None:
    start = project.narrative_graph.nodes[0]
    broken_choice = replace(
        start.choices[0],
        effects=(EffectSpec("increment", ("trust.ling", "a lot")),),
    )
    broken_start = replace(start, choices=(broken_choice,))
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(broken_start,) + project.narrative_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "effect.value_type" in {item.code for item in result.diagnostics}


def test_compile_rejects_set_value_outside_variable_bounds(project) -> None:
    start = project.narrative_graph.nodes[0]
    broken_choice = replace(
        start.choices[0],
        effects=(EffectSpec("set", ("trust.ling", 101)),),
    )
    broken_start = replace(start, choices=(broken_choice,))
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(broken_start,) + project.narrative_graph.nodes[1:],
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert not result.ok
    assert "effect.value_type" in {item.code for item in result.diagnostics}


def test_compile_rejects_repeat_window_larger_than_retained_history(project) -> None:
    definition = replace(project.semantic_signals[0], repeat_window=257)
    changed = replace(project, semantic_signals=(definition,))

    result = StoryCompiler().compile_with_diagnostics(changed)

    assert not result.ok
    assert "semantic.repeat_window" in {item.code for item in result.diagnostics}


def test_compile_rejects_locked_context_copied_to_exposed_context(project) -> None:
    gate = project.narrative_graph.nodes[1]
    secret = "绫的姐姐曾在旧校舍失踪"
    broken_gate = replace(
        gate,
        exposed_context={"summary": secret},
        locked_context={"secrets": [secret]},
    )
    broken = replace(
        project,
        narrative_graph=replace(
            project.narrative_graph,
            nodes=(
                project.narrative_graph.nodes[0],
                broken_gate,
                project.narrative_graph.nodes[2],
            ),
        ),
    )

    result = StoryCompiler().compile_with_diagnostics(broken)

    assert "narrative.secret_leak" in {item.code for item in result.diagnostics}
