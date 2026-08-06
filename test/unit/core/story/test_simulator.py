from __future__ import annotations

from pathlib import Path

from core.story import (
    CastResolutionContext,
    CharacterRuntimeStatus,
    StartStory,
    StoryCompiler,
    StoryRuntime,
    StorySimulator,
    StubSceneRenderer,
    load_story_project,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "stories" / "campus-mystery"
)


def _runtime() -> StoryRuntime:
    program = StoryCompiler().compile(load_story_project(FIXTURE_ROOT))
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


def test_stub_renderer_is_deterministic_and_system_scoped() -> None:
    runtime = _runtime()
    result = runtime.start(StartStory("start-1"))
    renderer = StubSceneRenderer()

    first = renderer.render(result.state, result.events)
    second = renderer.render(result.state, result.events)

    assert first == second
    assert all(event.speaker_id == "SYSTEM" for event in first)
    assert first[-1].payload["currentNodeId"] == "transfer-day"
