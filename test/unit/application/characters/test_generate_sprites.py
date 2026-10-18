import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from application.characters import generate_sprites as generation
from application.runtime.tasks import _create_task, _update_task
from config.character_manager import CharacterManager
from config.schema import Character
from frontend_bridge_core import sprite_generation as bridge


def test_planning_uses_draft_personality_and_returns_prompt_tag_pairs(monkeypatch):
    chat = Mock(
        return_value='```json\n{"items":[{"prompt":"consistent full body, shy smile","tagging":"立绘 1：害羞\n微笑"}]}\n```'.replace(
            "害羞\n微笑", "害羞\\n微笑"
        )
    )
    monkeypatch.setattr(generation, "chat_character_text", chat)
    result = generation.plan_sprites(
        object(),
        {
            "name": "Mika",
            "setting": "内向，喜欢绘画",
            "requirements": "赛璐璐",
            "count": 1,
            "referenceImage": "ref.png",
        },
    )
    user = json.loads(chat.call_args.args[2])
    assert user["setting"] == "内向，喜欢绘画"
    assert user["hasReference"] is True
    assert user["requirements"] == "赛璐璐"
    assert result == {
        "items": [
            {"prompt": "consistent full body, shy smile", "tagging": "害羞, 微笑"}
        ]
    }


@pytest.mark.parametrize("count", [0, 13, 1.5, True, "2"])
def test_plan_rejects_invalid_count(count):
    with pytest.raises(ValueError, match="1–12"):
        generation.plan_sprites(object(), {"setting": "quiet", "count": count})


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"items":[]}',
        '{"items":[{"prompt":"x"}]}',
        '{"items":[{"prompt":"","tagging":"happy"}]}',
    ],
)
def test_plan_rejects_missing_or_malformed_pairs(monkeypatch, raw):
    monkeypatch.setattr(generation, "chat_character_text", lambda *_: raw)
    with pytest.raises(ValueError):
        generation.plan_sprites(object(), {"setting": "quiet", "count": 1})


def test_plan_requires_personality():
    with pytest.raises(ValueError, match="性格"):
        generation.plan_sprites(object(), {})


def test_plan_explains_missing_llm_configuration(monkeypatch):
    monkeypatch.setattr(
        generation,
        "chat_character_text",
        Mock(side_effect=ValueError("llm_incomplete")),
    )
    with pytest.raises(ValueError, match="API 设置"):
        generation.plan_sprites(object(), {"setting": "quiet", "count": 1})


def test_render_uses_manager_unique_outputs_references_and_fresh_seeds(
    tmp_path, monkeypatch
):
    from ai.t2i.t2i_manager import T2IAdapterFactory

    adapter = Mock(supports_reference_images=True)

    def draw(**kwargs):
        Image.new("RGB", (8, 8), "blue").save(kwargs["file_path"])
        return kwargs["file_path"]

    adapter.generate_image.side_effect = draw
    factory = Mock(return_value=adapter)
    monkeypatch.setattr(T2IAdapterFactory, "create_adapter", factory)
    api = SimpleNamespace(
        t2i_provider="comfyui",
        t2i_work_path="",
        t2i_api_url="local",
        t2i_default_workflow_path="workflow.json",
        t2i_prompt_node_id="1",
        t2i_output_node_id="2",
    )
    store = SimpleNamespace(
        config=SimpleNamespace(api_config=api),
        merged_t2i_factory_kwargs=lambda _, values: values,
    )
    for i in range(12):
        output = tmp_path / f"{i}.png"
        result = generation.render_sprite(
            store,
            {"name": "Mika", "prompt": "smile", "tagging": "开心"},
            output,
            tmp_path / "ref.png",
        )
        assert result["path"] == output.as_posix()
    calls = adapter.generate_image.call_args_list
    assert len({call.kwargs["file_path"] for call in calls}) == 12
    assert len({call.kwargs["seed"] for call in calls}) == 12
    assert calls[0].kwargs["reference_image_path"] == str(tmp_path / "ref.png")
    assert factory.call_args.kwargs["workflow_path"] == "workflow.json"


@pytest.fixture
def sprite_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "config.character_manager.UPLOAD_DIR", str(tmp_path / "sprites")
    )
    character = Character(
        name="Mika",
        sprite_prefix="mika",
        color="#fff",
        sprites=[{"path": "old.png", "voice_text": "hello"}],
        emotion_tags="立绘 1：已有标签",
    )
    store = SimpleNamespace(
        get_character_by_name=lambda name: character if name == "Mika" else None,
        save_characters_config=Mock(),
        reload=Mock(),
    )
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = store
    state = SimpleNamespace(
        config_manager=store,
        character_manager=manager,
        task_lock=threading.Lock(),
        tasks={},
        project_root_dir=str(tmp_path),
    )
    return state, character


def completed_sprite(state, filename="one", name="Mika"):
    task = _create_task(state, kind="character-sprite-render", title="render")
    path = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{filename}.png"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8)).save(path)
    _update_task(
        state,
        task["id"],
        status="succeeded",
        result={
            "path": str(path),
            "name": name,
            "prompt": "happy pose",
            "tagging": "开心",
        },
    )
    return task["id"]


def test_import_appends_only_selected_pairs_and_is_idempotent(sprite_state):
    state, character = sprite_state
    first = completed_sprite(state)
    completed_sprite(state, "unselected")
    payload = {
        "name": "Mika",
        "items": [{"taskId": first, "tagging": "微笑，日常"}, {"taskId": first}],
    }
    result = bridge.import_generated_sprites(state, payload)
    assert len(result["sprites"]) == 2
    assert result["sprites"][0]["voice_text"] == "hello"
    assert result["emotion_tags"] == "立绘 1：已有标签\n立绘 2：微笑, 日常\n"
    bridge.import_generated_sprites(state, payload)
    assert len(character.sprites) == 2
    state.config_manager.save_characters_config.assert_called_once()


def test_import_validates_entire_selection_before_persistence(sprite_state):
    state, character = sprite_state
    first = completed_sprite(state)
    second = completed_sprite(state, "wrong-character", "Other")
    with pytest.raises(ValueError, match="不属于"):
        bridge.import_generated_sprites(
            state, {"name": "Mika", "items": [{"taskId": first}, {"taskId": second}]}
        )
    assert len(character.sprites) == 1
    state.config_manager.save_characters_config.assert_not_called()


def test_failed_save_can_be_retried_without_duplicating_sprites(sprite_state):
    state, character = sprite_state
    task_id = completed_sprite(state)
    payload = {"name": "Mika", "items": [{"taskId": task_id}]}
    state.config_manager.save_characters_config.side_effect = OSError("disk full")
    with pytest.raises(OSError, match="disk full"):
        bridge.import_generated_sprites(state, payload)
    assert len(character.sprites) == 1
    assert not state.tasks[task_id]["result"].get("imported")
    state.config_manager.save_characters_config.side_effect = None
    bridge.import_generated_sprites(state, payload)
    assert len(character.sprites) == 2


@pytest.mark.parametrize("mutation", ["outside", "failed", "wrong-kind", "missing"])
def test_import_rejects_untrusted_or_unavailable_results(sprite_state, mutation):
    state, character = sprite_state
    task_id = completed_sprite(state)
    task = state.tasks[task_id]
    if mutation == "outside":
        path = Path(state.project_root_dir) / "outside.png"
        Image.new("RGB", (1, 1)).save(path)
        task["result"]["path"] = str(path)
    elif mutation == "failed":
        task["status"] = "failed"
    elif mutation == "wrong-kind":
        task["kind"] = "other"
    else:
        state.tasks.clear()
    with pytest.raises((PermissionError, ValueError)):
        bridge.import_generated_sprites(
            state, {"name": "Mika", "items": [{"taskId": task_id}]}
        )
    assert len(character.sprites) == 1


def test_render_bridge_validates_reference_and_keeps_pair(sprite_state, monkeypatch):
    state, _ = sprite_state
    ref = Path(state.project_root_dir) / "reference.png"
    Image.new("RGB", (8, 8)).save(ref)
    monkeypatch.setattr(
        bridge, "_local_file_access_roots", lambda _: (Path(state.project_root_dir),)
    )
    renderer = Mock(
        return_value={
            "prompt": "pose",
            "tagging": "微笑",
            "path": "preview.png",
            "name": "Mika",
        }
    )
    monkeypatch.setattr(bridge, "render_sprite", renderer)
    task = _create_task(state, kind="character-sprite-render", title="render")
    result = bridge.run_sprite_render(
        state,
        task["id"],
        {
            "name": "Mika",
            "referenceImage": str(ref),
            "prompt": "pose",
            "tagging": "微笑",
        },
    )
    assert result["taskId"] == task["id"]
    assert renderer.call_args.args[3] == ref
