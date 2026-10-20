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
        return_value='```json\n{"items":[{"prompt":"smile shyly with lowered eyes and hold both hands together in front of the chest","tagging":"立绘 1：害羞\n微笑"}]}\n```'.replace(
            "害羞\n微笑", "害羞\\n微笑"
        )
    )
    monkeypatch.setattr(generation, "chat_character_text", chat)
    result = generation.plan_sprites(
        object(),
        {
            "name": "Mika",
            "setting": "内向，喜欢绘画",
            "requirements": "害羞地微笑，双手在胸前交握",
            "count": 1,
            "referenceImage": "ref.png",
        },
    )
    user = json.loads(chat.call_args.args[2])
    assert user["setting"] == "内向，喜欢绘画"
    assert user["hasReference"] is True
    assert user["requirements"] == "害羞地微笑，双手在胸前交握"
    system = chat.call_args.args[1]
    assert "不要描述人物外貌" in system
    assert "始终保持站立，双脚着地" in system
    assert "每条 prompt 必须明确描述面部表情" in system
    assert "包含眉眼或视线变化，以及嘴形变化" in system
    assert "不描述五官固有长相或颜色" in system
    assert "必须同时说明左右手的姿势和位置" in system
    assert "仅在动作涉及道具时" in system
    assert "以下规则仅适用于 tagging 字段" in system
    assert result == {
        "items": [
            {
                "prompt": "make the character stand and smile shyly with lowered eyes and hold both hands together in front of the chest, full body, full scene, plain light, sprite",
                "tagging": "害羞, 微笑",
            }
        ]
    }


def test_planning_keeps_props_and_adds_the_action_template_only_once(monkeypatch):
    prompt = "make the character stand and smile gently with relaxed eyes, hold a small sketchbook in the left hand at chest height and point to it with the right index finger, full body, full scene, plain light, sprite"
    monkeypatch.setattr(
        generation,
        "chat_character_text",
        lambda *_: json.dumps({"items": [{"prompt": prompt, "tagging": "思考，指向"}]}),
    )
    result = generation.plan_sprites(object(), {"setting": "喜欢绘画", "count": 1})
    assert result["items"][0]["prompt"] == prompt


def test_manually_edited_prompts_are_preserved():
    prompt = "custom action, custom framing"
    assert (
        generation.prompt_pair({"prompt": prompt, "tagging": "挥手"})["prompt"]
        == prompt
    )


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


def test_recapture_uses_trusted_video_and_a_new_result_that_imports_once(
    sprite_state, monkeypatch
):
    state, character = sprite_state
    source_id = completed_sprite(state)
    original = state.tasks[source_id]["result"]
    video = Path(original["path"]).with_suffix(".mp4")
    video.write_bytes(b"trusted video")
    original["videoPath"] = str(video)
    original_path = original["path"]

    def capture(source, video_path, output, seconds):
        assert video_path == video
        Image.new("RGB", (8, 8), "blue").save(output)
        return {**source, "path": output.as_posix(), "frameTime": seconds}

    monkeypatch.setattr(bridge, "capture_sprite_frame", capture)
    task = _create_task(state, kind="character-sprite-frame", title="frame")
    result = bridge.run_sprite_frame(
        state,
        task["id"],
        {
            "name": "Mika",
            "taskId": source_id,
            "seconds": 1.25,
            "removeBackground": False,
        },
    )
    assert result["taskId"] == task["id"]
    assert result["frameTime"] == 1.25
    assert result["prompt"] == original["prompt"]
    assert original["path"] == original_path
    _update_task(state, task["id"], status="succeeded", result=result)
    payload = {"name": "Mika", "items": [{"taskId": task["id"], "tagging": "选帧标签"}]}
    bridge.import_generated_sprites(state, payload)
    bridge.import_generated_sprites(state, payload)
    assert len(character.sprites) == 2
    assert "选帧标签" in character.emotion_tags


@pytest.mark.parametrize(
    "mutation",
    [
        "outside",
        "wrong-character",
        "missing-video",
        "failed",
        "wrong-kind",
        "missing-time",
    ],
)
def test_recapture_rejects_untrusted_results_without_running_decoder(
    sprite_state, monkeypatch, mutation
):
    state, _ = sprite_state
    source_id = completed_sprite(state)
    source = state.tasks[source_id]
    video = Path(source["result"]["path"]).with_suffix(".mp4")
    video.write_bytes(b"video")
    source["result"]["videoPath"] = str(video)
    payload = {"name": "Mika", "taskId": source_id, "seconds": 1}
    if mutation == "outside":
        outside = Path(state.project_root_dir) / "outside.mp4"
        outside.write_bytes(b"outside")
        source["result"]["videoPath"] = str(outside)
    elif mutation == "wrong-character":
        source["result"]["name"] = "Other"
    elif mutation == "missing-video":
        source["result"].pop("videoPath")
    elif mutation == "failed":
        source["status"] = "failed"
    elif mutation == "wrong-kind":
        source["kind"] = "unrelated"
    else:
        payload.pop("seconds")
    decoder = Mock()
    monkeypatch.setattr(bridge, "capture_sprite_frame", decoder)
    task = _create_task(state, kind="character-sprite-frame", title="frame")
    with pytest.raises((ValueError, PermissionError)):
        bridge.run_sprite_frame(state, task["id"], payload)
    decoder.assert_not_called()


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
            "removeBackground": False,
        },
    )
    assert result["taskId"] == task["id"]
    assert renderer.call_args.args[3] == ref


def test_auto_cutout_failure_keeps_render_and_can_retry_without_generating(
    sprite_state, monkeypatch
):
    state, character = sprite_state
    source_id = completed_sprite(state)
    source = dict(state.tasks[source_id]["result"])
    remover = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setattr(bridge, "remove_sprite_background", remover)
    failed = bridge._finish_sprite(state, source_id, source, True)
    assert failed["path"] == source["path"]
    assert failed["backgroundRemoved"] is False
    assert failed["backgroundRemovalError"] == "model unavailable"
    assert Path(source["path"]).is_file()
    state.tasks[source_id]["result"] = failed

    def cutout(source, original, output):
        Image.new("RGBA", (8, 8), (0, 0, 255, 128)).save(output)
        return {**source, "path": output.as_posix(), "backgroundRemoved": True}

    remover.side_effect = cutout
    retry = _create_task(state, kind="character-sprite-cutout", title="cutout")
    result = bridge.run_sprite_cutout(
        state, retry["id"], {"name": "Mika", "taskId": source_id}
    )
    assert result["path"] != source["path"]
    assert remover.call_args.args[1] == Path(source["path"])
    _update_task(state, retry["id"], status="succeeded", result=result)
    bridge.import_generated_sprites(
        state, {"name": "Mika", "items": [{"taskId": retry["id"]}]}
    )
    with Image.open(character.sprites[-1]["path"]) as image:
        assert image.getchannel("A").getextrema() == (128, 128)


def test_cutout_keeps_geometry_tags_and_video_but_not_import_state(
    tmp_path, monkeypatch
):
    from tools import remove_bg

    original = tmp_path / "raw.png"
    Image.new("RGB", (24, 32), "white").save(original)
    output = tmp_path / "cutout.png"

    def cutout(source, target):
        with Image.open(source) as image:
            image.convert("RGBA").save(target)

    monkeypatch.setattr(remove_bg, "ai_remove_background", cutout)
    source = {
        "prompt": "pose",
        "tagging": "开心，挥手",
        "name": "Mika",
        "videoPath": "video.mp4",
        "frameTime": 1.25,
        "imported": True,
        "backgroundRemovalError": "old error",
    }
    result = generation.remove_sprite_background(source, original, output)
    assert result["tagging"] == "开心, 挥手"
    assert result["originalPath"] == original.as_posix()
    assert result["videoPath"] == "video.mp4"
    assert result["frameTime"] == 1.25
    assert "imported" not in result and "backgroundRemovalError" not in result
    with Image.open(output) as image:
        assert image.size == (24, 32)


@pytest.mark.parametrize("invalid", ["false", 1, None])
def test_invalid_cutout_option_is_rejected_before_expensive_generation(
    sprite_state, monkeypatch, invalid
):
    state, _ = sprite_state
    render = Mock()
    monkeypatch.setattr(bridge, "render_sprite", render)
    with pytest.raises(ValueError, match="布尔"):
        bridge.run_sprite_render(
            state, "invalid", {"name": "Mika", "removeBackground": invalid}
        )
    render.assert_not_called()


def test_cutout_disabled_leaves_the_render_untouched(sprite_state, monkeypatch):
    state, _ = sprite_state
    task_id = completed_sprite(state)
    source = dict(state.tasks[task_id]["result"])
    remover = Mock()
    monkeypatch.setattr(bridge, "remove_sprite_background", remover)
    result = bridge._finish_sprite(state, task_id, source, False)
    assert result["path"] == source["path"]
    assert result["backgroundRemoved"] is False
    remover.assert_not_called()


def test_generated_images_and_video_are_approved_for_preview_without_exposing_other_files(
    sprite_state,
):
    state, _ = sprite_state
    task_id = completed_sprite(state)
    source = dict(state.tasks[task_id]["result"])
    video = Path(source["path"]).with_suffix(".mp4")
    video.write_bytes(b"video")
    source["videoPath"] = video.as_posix()
    approve = Mock()
    state.chat_stream = SimpleNamespace(approve_external_media_path=approve)
    bridge._finish_sprite(state, task_id, source, False)
    assert {call.args[0] for call in approve.call_args_list} == {
        Path(source["path"]).as_posix(),
        video.as_posix(),
    }
    unrelated = Path(state.project_root_dir) / "unrelated.png"
    Image.new("RGB", (8, 8)).save(unrelated)
    with pytest.raises(PermissionError):
        bridge._approve_sprite_media(state, {"path": unrelated.as_posix()})


@pytest.mark.parametrize(
    "mutation", ["outside", "wrong-character", "failed", "wrong-kind"]
)
def test_cutout_rejects_untrusted_sources(sprite_state, monkeypatch, mutation):
    state, _ = sprite_state
    task_id = completed_sprite(state)
    task = state.tasks[task_id]
    if mutation == "outside":
        path = Path(state.project_root_dir) / "outside.png"
        Image.new("RGB", (8, 8)).save(path)
        task["result"]["originalPath"] = str(path)
    elif mutation == "wrong-character":
        task["result"]["name"] = "Other"
    elif mutation == "failed":
        task["status"] = "failed"
    else:
        task["kind"] = "unrelated"
    remover = Mock()
    monkeypatch.setattr(bridge, "remove_sprite_background", remover)
    with pytest.raises((ValueError, PermissionError)):
        bridge.run_sprite_cutout(state, "cutout", {"name": "Mika", "taskId": task_id})
    remover.assert_not_called()
