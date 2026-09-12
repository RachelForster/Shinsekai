import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.story.coordinator import (
    start_or_recover_story_session,
    clear_story_session,
)
from application.story.generation import StoryGenerationError, StoryPatchApplier
from application.story.library import list_story_library, prepare_story_launch
from application.story.selection import generation_selection
from config.schema import Character
from core.story import AdvanceStoryTurn
from frontend_bridge_core.routes.router import ApiRequest
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from test.unit.application.story.test_generation import (
    ScriptedModel,
    service_at,
    stage_artifacts,
)


def selected_story(tmp_path):
    characters = [
        Character(
            name="小玲",
            color="#ffffff",
            sprite_prefix="",
            character_setting="小玲的完整设定",
            character_brief="小玲简介",
        ),
        Character(
            name="小晴",
            color="#ffffff",
            sprite_prefix="",
            character_setting="小晴的完整设定",
            character_brief="小晴简介",
        ),
    ]
    manager = SimpleNamespace(
        get_character_by_name=lambda name: next(
            (item for item in characters if item.name == name), None
        ),
        get_background_by_name=lambda name: SimpleNamespace(
            sprites=[SimpleNamespace(path="school.png")]
        )
        if name == "旧校舍"
        else None,
        config=SimpleNamespace(characters=characters),
    )
    state = SimpleNamespace(
        project_root_dir=tmp_path,
        history_dir=tmp_path / "data/chat_history",
        config_manager=manager,
        template_generator=SimpleNamespace(
            generate_chat_template=Mock(return_value=("人物系统提示词", []))
        ),
    )
    options, catalog = generation_selection(
        state,
        {
            "characters": ["小玲", "小晴"],
            "primaryCharacters": ["小玲"],
            "characterPromptMode": "compact",
            "backgroundName": "旧校舍",
        },
    )
    artifacts = stage_artifacts()
    artifacts["characters"]["characters"] = [
        {**item, "responsibility": "陪玩家调查校舍"} for item in catalog["characters"]
    ]
    for node in artifacts["narrative"]["nodes"]:
        node["background"] = "旧校舍"
    model = ScriptedModel(artifacts)
    service, repository = service_at(tmp_path / "data/stories/.generation", model)
    manager.feature_flags = service.flags
    state.story_generation_service = service
    task = service.create("一起调查旧校舍", options=options, resource_catalog=catalog)
    result = service.run(task["id"])
    return state, result, model, repository


def test_selection_reaches_author_and_runtime_with_primary_and_secondary_settings(
    tmp_path,
):
    state, task, model, _ = selected_story(tmp_path)
    assert task["status"] == "succeeded"
    selected = model.requests[0]["resourceCatalog"]["characters"]
    assert [item["characterSetting"] for item in selected] == [
        "小玲的完整设定",
        "小晴简介",
    ]
    route = next(item for item in STORY_ROUTES if item.name == "story.launch-payload")
    response = route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path=route.pattern,
            query={},
            params={},
            body={"storyPath": task["draftPath"]},
        )
    )
    payload = response.data
    assert payload["templateId"] == ""
    assert payload["characters"] == ["小玲", "小晴"]
    assert payload["backgroundName"] == "旧校舍"
    assert payload["resetHistory"] is True
    assert state.template_generator.generate_chat_template.call_args.kwargs[
        "primary_characters"
    ] == ["小玲"]
    state.chat_session = {"historyPath": (state.history_dir / "save").as_posix()}
    session = start_or_recover_story_session(
        state, task["draftPath"], command_id="start"
    )
    assert state.story_cast_service is None
    assert state.story_scene_service is None
    assert payload["system"] == "人物系统提示词"
    assert session.active_branch.state.current_node_id == "school-gate"


def test_library_survives_restart_and_continues_saved_node(tmp_path):
    state, task, _, _ = selected_story(tmp_path)
    rows = list_story_library(state)
    assert len(rows) == 1
    assert rows[0]["characters"] == ["小玲", "小晴"]
    assert not rows[0]["historyPath"]
    history = state.history_dir / "save"
    history.mkdir(parents=True)
    (history / "active.json").write_text("{}", encoding="utf-8")
    state.chat_session = {"historyPath": history.as_posix()}
    session = start_or_recover_story_session(
        state, task["draftPath"], command_id="start"
    )
    session.execute(
        AdvanceStoryTurn(
            command_id="advance",
            expected_revision=session.active_branch.state.revision,
            expected_node_id="school-gate",
            next_node_id="school-lobby",
        )
    )
    revision = session.active_branch.state.revision
    clear_story_session(state)
    rows = list_story_library(state)
    assert rows[0]["historyPath"] == history.as_posix()
    assert rows[0]["currentNodeTitle"] == "School lobby"
    payload = prepare_story_launch(state, rows[0]["storyPath"], rows[0]["historyPath"])
    assert payload["resetHistory"] is False
    recovered = start_or_recover_story_session(
        state, rows[0]["storyPath"], command_id="recover"
    )
    assert recovered.active_branch.state.current_node_id == "school-lobby"
    assert recovered.active_branch.state.revision == revision


def test_library_ignores_broken_and_incomplete_projects_and_rejects_wrong_save(
    tmp_path,
):
    state, task, _, _ = selected_story(tmp_path)
    (tmp_path / "data/stories/broken.yaml").write_text("invalid: [", encoding="utf-8")
    history = state.history_dir / "wrong"
    history.mkdir(parents=True)
    (history / "active.json").write_text("{}", encoding="utf-8")
    (history / "story-v2.json").write_text(
        json.dumps({"version": 2, "storyId": "other"}), encoding="utf-8"
    )
    assert len(list_story_library(state)) == 1
    with pytest.raises(ValueError, match="不匹配"):
        prepare_story_launch(state, task["draftPath"], history.as_posix())
    path = Path(task["draftPath"]).with_name("task.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["status"] = "failed"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert list_story_library(state) == []


def test_generation_route_uses_installed_resources_and_allows_empty_synopsis(tmp_path):
    state, task, _, _ = selected_story(tmp_path)
    route = next(item for item in STORY_ROUTES if item.name == "story.generation.start")
    response = route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path=route.pattern,
            query={},
            params={},
            body={
                "synopsis": "",
                "options": task["options"],
                "resourceCatalog": {"characters": [{"name": "错误人物"}]},
            },
        )
    )
    generated = response.task_updates["generationTask"]
    assert "小玲" in generated["synopsis"]
    assert (
        generated["resourceCatalog"]["characters"][1]["characterSetting"] == "小晴简介"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"characters": []},
        {"characters": ["不存在"]},
        {"primaryCharacters": []},
        {"primaryCharacters": ["不存在"]},
        {"backgroundName": "不存在"},
    ],
)
def test_invalid_selections_are_rejected(tmp_path, change):
    state, task, _, _ = selected_story(tmp_path)
    with pytest.raises(ValueError):
        generation_selection(state, {**task["options"], **change})


def test_story_characters_are_repairable_without_changing_template_settings(tmp_path):
    state, task, _, repository = selected_story(tmp_path)
    source = repository.load_draft(task["id"])
    replacement = {
        **source["cast"]["characters"][0],
        "source": {"type": "local-library", "characterId": "别人"},
    }
    patched = StoryPatchApplier().apply(
        source,
        {
            "baseVersion": 1,
            "operations": [
                {
                    "op": "replace-character",
                    "characterId": "selected-1",
                    "value": replacement,
                },
            ],
        },
        base_version=1,
    )
    assert patched["cast"]["characters"][0]["source"]["characterId"] == "别人"
    with pytest.raises(StoryGenerationError):
        StoryPatchApplier().apply(
            source,
            {
                "baseVersion": 1,
                "operations": [
                    {
                        "op": "replace",
                        "path": "/metadata/resourceBindings/characterSettings/selected-2",
                        "value": "完整设定",
                    },
                ],
            },
            base_version=1,
        )
