from __future__ import annotations

from copy import deepcopy

import pytest

from core.story import (
    AdvanceStoryTurn,
    StartStory,
    StoryCompiler,
    StoryCompileError,
    StoryEventReplayer,
    StoryEventType,
    StoryRuntime,
    StoryRuntimeError,
    StoryValidationError,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


def simple_story_source() -> dict:
    source = deepcopy(campus_mystery_source())
    source["narrativeGraph"] = {
        "startNodeId": "opening",
        "nodes": [
            {
                "id": "opening",
                "title": "雨中的约定",
                "type": "limited_turn_node",
                "instruction": "绫邀请玩家一起调查旧校舍。",
                "maxRounds": 2,
                "transitions": [
                    {"to": "lobby", "when": "玩家愿意继续交谈"},
                    {"to": "ending", "when": "玩家决定结束调查"},
                ],
                "defaultTo": "lobby",
            },
            {
                "id": "lobby",
                "title": "旧校舍大厅",
                "type": "free_chat_node",
                "instruction": "围绕旧校舍的传闻自由交谈。",
                "transitions": [{"to": "ending", "when": "玩家明确表示离开"}],
            },
            {
                "id": "ending",
                "title": "离开旧校舍",
                "type": "ending_node",
            },
        ],
    }
    source["logicGraph"] = {"version": 1, "nodes": [], "edges": []}
    return source


def _program():
    return StoryCompiler().compile(parse_story_project(simple_story_source()))


def test_simple_node_schema_compiles_natural_language_routes() -> None:
    program = _program()
    opening = program.nodes_by_id["opening"]

    assert opening.instruction == "绫邀请玩家一起调查旧校舍。"
    assert opening.max_rounds == 2
    assert opening.default_to == "lobby"
    assert opening.transitions[0].to_node_id == "lobby"


def test_simple_nodes_retain_generated_backgrounds() -> None:
    source = simple_story_source()
    source["metadata"]["backgrounds"] = ["旧校舍门口", "旧校舍大厅"]
    source["narrativeGraph"]["nodes"][0]["background"] = "旧校舍门口"
    source["narrativeGraph"]["nodes"][1]["background"] = "旧校舍大厅"
    source["narrativeGraph"]["nodes"][2]["background"] = "旧校舍门口"

    program = StoryCompiler().compile(parse_story_project(source))

    assert program.backgrounds == ("旧校舍门口", "旧校舍大厅")
    assert program.nodes_by_id["opening"].background == "旧校舍门口"
    assert program.nodes_by_id["lobby"].background == "旧校舍大厅"


def test_compiler_accepts_location_hints_outside_story_catalog() -> None:
    source = simple_story_source()
    source["metadata"]["backgrounds"] = ["旧校舍门口"]
    source["narrativeGraph"]["nodes"][0]["background"] = "不存在的地点"

    assert StoryCompiler().compile(parse_story_project(source)).nodes_by_id["opening"].background == "不存在的地点"


def test_compiler_allows_nodes_without_background_when_catalog_is_present() -> None:
    source = simple_story_source()
    source["metadata"]["backgrounds"] = ["旧校舍门口"]

    assert StoryCompiler().compile(parse_story_project(source)).nodes_by_id["opening"].background is None


def test_limited_node_uses_default_target_at_round_limit() -> None:
    runtime = StoryRuntime(_program())
    started = runtime.start(StartStory("start"))
    first = runtime.execute(
        started.state,
        AdvanceStoryTurn(
            command_id="round-1",
            expected_revision=started.state.revision,
            expected_node_id="opening",
        ),
    )

    assert first.state.current_node_id == "opening"
    assert first.state.node_turn_count == 1
    second = runtime.execute(
        first.state,
        AdvanceStoryTurn(
            command_id="round-2",
            expected_revision=first.state.revision,
            expected_node_id="opening",
        ),
    )

    assert second.state.current_node_id == "lobby"
    assert second.state.node_turn_count == 0
    assert "opening" in second.state.completed_node_ids
    assert StoryEventType.NODE_TURN_COMPLETED in {event.type for event in second.events}


def test_free_chat_can_stay_or_move_to_an_allowed_target() -> None:
    runtime = StoryRuntime(_program())
    started = runtime.start(StartStory("start"))
    lobby = runtime.execute(
        started.state,
        AdvanceStoryTurn(
            command_id="go-lobby",
            expected_revision=started.state.revision,
            expected_node_id="opening",
            next_node_id="lobby",
        ),
    )
    stayed = runtime.execute(
        lobby.state,
        AdvanceStoryTurn(
            command_id="stay",
            expected_revision=lobby.state.revision,
            expected_node_id="lobby",
        ),
    )
    ended = runtime.execute(
        stayed.state,
        AdvanceStoryTurn(
            command_id="leave",
            expected_revision=stayed.state.revision,
            expected_node_id="lobby",
            next_node_id="ending",
        ),
    )

    assert stayed.state.current_node_id == "lobby"
    assert stayed.state.node_turn_count == 1
    assert ended.state.current_node_id == "ending"
    assert ended.state.node_turn_count == 0


def test_runtime_rejects_undeclared_transition_target() -> None:
    runtime = StoryRuntime(_program())
    started = runtime.start(StartStory("start"))

    with pytest.raises(StoryRuntimeError, match="cannot transition"):
        runtime.execute(
            started.state,
            AdvanceStoryTurn(
                command_id="invalid",
                expected_revision=started.state.revision,
                expected_node_id="opening",
                next_node_id="missing",
            ),
        )


def test_simple_node_turns_are_replayable() -> None:
    runtime = StoryRuntime(_program())
    started = runtime.start(StartStory("start"))
    advanced = runtime.execute(
        started.state,
        AdvanceStoryTurn(
            command_id="round-1",
            expected_revision=started.state.revision,
            expected_node_id="opening",
        ),
    )

    replayed = StoryEventReplayer().replay(
        runtime.initial_state(),
        (*started.events, *advanced.events),
        program=runtime.program,
    )

    assert replayed == advanced.state


def test_compiler_rejects_missing_limited_node_round_limit() -> None:
    source = simple_story_source()
    source["narrativeGraph"]["nodes"][0].pop("maxRounds")

    with pytest.raises(StoryCompileError, match="requires maxRounds"):
        StoryCompiler().compile(parse_story_project(source))


def test_simple_nodes_reject_legacy_choices() -> None:
    source = simple_story_source()
    source["narrativeGraph"]["nodes"][0]["choices"] = [
        {"id": "legacy", "label": "旧选项", "goto": "lobby"}
    ]

    with pytest.raises(StoryValidationError, match="not valid for simple story nodes"):
        parse_story_project(source)


def test_simple_nodes_reject_per_node_character_assignment() -> None:
    source = simple_story_source()
    source["narrativeGraph"]["nodes"][0]["castPolicy"] = {}

    with pytest.raises(StoryValidationError, match="castPolicy is not valid"):
        parse_story_project(source)
