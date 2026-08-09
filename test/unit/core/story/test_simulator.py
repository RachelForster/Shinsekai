from __future__ import annotations

from core.story import (
    CastResolutionContext,
    CharacterRuntimeStatus,
    StartStory,
    StoryCompiler,
    StoryRuntime,
    StorySimulator,
    StubSceneRenderer,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


def _runtime() -> StoryRuntime:
    program = StoryCompiler().compile(parse_story_project(campus_mystery_source()))
    return StoryRuntime(program)


def test_simulator_reaches_fixed_ending_without_llm() -> None:
    report = StorySimulator(_runtime()).simulate()

    assert report.truncated is False
    assert report.reachable_node_ids == {
        "transfer-day",
        "old-school-gate",
        "truth-ending",
    }
    assert report.ending_paths["truth-ending"] == (
        "choice:transfer-day/prepare-investigation",
        "choice:old-school-gate/enter-with-key",
    )
    assert report.dead_end_node_ids == frozenset()
    assert report.cast_resolution_failures == {}


def test_simulator_reports_unresolvable_scene_cast() -> None:
    report = StorySimulator(_runtime()).simulate(
        cast_context=CastResolutionContext(
            statuses={
                "detective-zhou": CharacterRuntimeStatus(available=False),
            }
        )
    )

    assert report.cast_resolution_failures == {"old-school-gate": "cast.missing_role"}
    assert report.dead_end_node_ids == {"transfer-day"}


def test_simulator_reports_truncation_at_depth_limit() -> None:
    report = StorySimulator(_runtime(), max_depth=1).simulate()

    assert report.truncated is True
    assert "truth-ending" not in report.ending_paths


def test_simulator_explores_nodes_entered_after_unlock() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][0]["choices"][0].pop("goto")
    runtime = StoryRuntime(StoryCompiler().compile(parse_story_project(source)))

    report = StorySimulator(runtime).simulate()

    assert report.truncated is False
    assert report.reachable_node_ids == {
        "transfer-day",
        "old-school-gate",
        "truth-ending",
    }
    assert "enter:old-school-gate" in report.ending_paths["truth-ending"]


def test_stub_renderer_is_deterministic_and_system_scoped() -> None:
    runtime = _runtime()
    result = runtime.start(StartStory("start-1"))
    renderer = StubSceneRenderer()

    first = renderer.render(result.state, result.events)
    second = renderer.render(result.state, result.events)

    assert first == second
    assert all(event.speaker_id == "SYSTEM" for event in first)
    assert first[-1].payload["currentNodeId"] == "transfer-day"
