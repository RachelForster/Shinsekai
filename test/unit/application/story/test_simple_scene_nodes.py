from __future__ import annotations

from application.story import (
    CharacterResourceManager,
    CharacterSourceResolver,
    SceneOrchestrator,
    StoryCastApplicationService,
    StorySession,
)
from application.story.persistence import (
    story_state_from_payload,
    story_state_to_payload,
)
from core.story import StoryCompiler, StoryRuntime, parse_story_project
from test.unit.application.story.test_scene import (
    _Library,
    _Model,
    _flags,
    _library_digest,
)
from test.unit.core.story.test_simple_nodes import simple_story_source


def _simple_scene(*responses):
    flags = _flags()
    source = simple_story_source()
    source["cast"]["characters"][0]["source"]["revision"] = _library_digest("ling")
    program = StoryCompiler().compile(parse_story_project(source))
    resources = CharacterResourceManager(
        flags,
        registry=program.character_registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id=program.story_id,
            story_root=".",
            local_library=_Library(),
        ),
    )
    cast_service = StoryCastApplicationService(flags, resources)
    session = StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start",
        cast_plan_preparer=cast_service.prepare,
        cast_plan_committed=cast_service.committed,
    )
    model = _Model(*responses)
    scene = SceneOrchestrator(
        flags,
        program=program,
        session=session,
        cast_service=cast_service,
        model=model,
    )
    return session, model, scene


def _dialogue(text: str, next_node_id=None) -> dict:
    return {
        "dialogue": [{"characterId": "ling", "text": text}],
        "nextNodeId": next_node_id,
    }


def test_scene_response_advances_limited_node_at_its_round_limit() -> None:
    session, model, scene = _simple_scene(
        _dialogue("我们先在门口看看。"),
        _dialogue("那就进去吧。"),
    )

    first = scene.handle_free_text(
        "这里安全吗？", command_id="turn-1", message_id="m-1"
    )
    second = scene.handle_free_text("继续吧。", command_id="turn-2", message_id="m-2")

    assert first.next_node_id is None
    assert second.next_node_id == "lobby"
    assert session.active_branch.state.current_node_id == "lobby"
    first_scene = model.requests[0]["scene"]
    assert first_scene["nodeType"] == "limited_turn_node"
    assert first_scene["currentRound"] == 1
    assert model.requests[0]["tools"] == []
    assert "visibleVariables" not in first_scene
    assert first_scene["transitions"][0] == {
        "to": "lobby",
        "when": "玩家愿意继续交谈",
    }


def test_scene_repairs_an_undeclared_next_node() -> None:
    session, _, scene = _simple_scene(
        _dialogue("去一个不存在的地方。", "invented-node"),
        _dialogue("那就进入大厅。", "lobby"),
    )

    result = scene.handle_free_text("进去吧。", command_id="turn-1", message_id="m-1")

    assert result.next_node_id == "lobby"
    assert result.diagnostic == "scene.transition_target"
    assert session.active_branch.state.current_node_id == "lobby"


def test_free_chat_checks_for_a_transition_on_every_round() -> None:
    session, _, scene = _simple_scene(
        _dialogue("进入大厅。", "lobby"),
        _dialogue("我们再聊一会儿。"),
        _dialogue("该离开了。", "ending"),
    )
    scene.handle_free_text("进去吧。", command_id="turn-1", message_id="m-1")

    stayed = scene.handle_free_text("讲讲传闻。", command_id="turn-2", message_id="m-2")
    ended = scene.handle_free_text(
        "我们离开吧。", command_id="turn-3", message_id="m-3"
    )

    assert stayed.next_node_id is None
    assert ended.next_node_id == "ending"
    assert session.active_branch.state.current_node_id == "ending"


def test_simple_node_turn_count_round_trips_through_persistence() -> None:
    session, _, scene = _simple_scene(_dialogue("再观察一轮。"))
    scene.handle_free_text("先等等。", command_id="turn-1", message_id="m-1")

    state = session.active_branch.state
    restored = story_state_from_payload(
        story_state_to_payload(state),
        program=session.runtime.program,
    )

    assert restored == state
    assert restored.node_turn_count == 1
