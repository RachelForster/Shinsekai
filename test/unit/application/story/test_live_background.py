from types import SimpleNamespace

import pytest

from application.story import StorySession
from application.story.coordinator import publish_story_transition, story_snapshot_patch
from core.story import AdvanceStoryTurn, StoryCompiler, StoryRuntime, parse_story_project
from test.unit.application.story.test_chat_integration import _state
from test.unit.core.story.test_simple_nodes import simple_story_source


def test_transition_and_rollback_leave_template_background_untouched():
    state = _state(enabled=True)
    source = simple_story_source()
    source["metadata"]["backgrounds"] = ["门口", "大厅"]
    for node, background in zip(source["narrativeGraph"]["nodes"], ["门口", "大厅", "门口"]):
        node["background"] = background
    program = StoryCompiler().compile(parse_story_project(source))
    session = StorySession.create(
        StoryRuntime(program), state.config_manager.feature_flags, command_id="start"
    )
    state.story_session = session
    state.config_manager.get_background_by_name = lambda name: SimpleNamespace(
        sprites=[SimpleNamespace(path=f"media/{name}.png")]
    )
    state.chat_stream.media_url = lambda path: f"/api/media/{path}"
    # A connected stage consumes events; it does not hydrate HTTP snapshots.
    state.chat_stream.update_session_snapshot = lambda *_: None
    initial_generation = session.active_branch.generation
    session.execute(AdvanceStoryTurn(
        command_id="advance", expected_revision=session.active_branch.state.revision,
        expected_node_id="opening", next_node_id="lobby",
    ))

    publish_story_transition(state, story_snapshot_patch(state))
    session.restore_generation(initial_generation)
    publish_story_transition(state, story_snapshot_patch(state))

    backgrounds = [e for e in state.chat_stream.published if e["type"] == "background.change"]
    assert backgrounds == []
    assert sum(e["type"] == "story.state.replace" for e in state.chat_stream.published) == 2


@pytest.mark.parametrize("patch,expected", [({}, []), ({"backgroundPath": ""}, [])])
def test_background_event_distinguishes_omission_from_clearing(patch, expected):
    state = _state(enabled=True)
    publish_story_transition(state, patch)
    assert [e["url"] for e in state.chat_stream.published if e["type"] == "background.change"] == expected
