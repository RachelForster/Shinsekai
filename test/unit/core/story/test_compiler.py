from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from core.story import (
    CharacterSource,
    CharacterSourceType,
    ConditionSpec,
    EffectSpec,
    PortRef,
    RuleEdge,
    RuleGraph,
    RuleNode,
    StoryCompileError,
    StoryCompiler,
    load_story_project,
)
from core.story.compiler import story_program_json


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "stories" / "campus-mystery"
)


@pytest.fixture
def project():
    return load_story_project(FIXTURE_ROOT)


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


def test_published_unpinned_local_character_is_warning(project) -> None:
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

    assert result.ok
    warning = next(
        item for item in result.diagnostics if item.code == "character.unpinned"
    )
    assert warning.severity.value == "warning"


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
