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
    assert "始终保持站立姿态" in system
    assert "半身像保持半身" in system
    assert "不必让双手都入镜" in system
    assert "双脚着地并可见" not in system
    assert "每条 prompt 必须明确描述面部表情" in system
    assert "包含眉眼或视线变化，以及嘴形变化" in system
    assert "不描述五官固有长相或颜色" in system
    assert "必须同时说明左右手的姿势和位置" in system
    assert "仅在动作涉及道具时" in system
    assert "以下规则仅适用于 tagging 字段" in system
    assert result == {
        "items": [
            {
                "prompt": "make the character stand and smile shyly with lowered eyes and hold both hands together in front of the chest, preserve the reference image's exact framing, crop, camera angle, character scale and screen position throughout, keep all pose changes within the original frame, locked-off static camera, fixed viewpoint and focal length throughout, plain light, sprite",
                "tagging": "害羞, 微笑",
            }
        ]
    }


def test_planning_keeps_props_and_adds_the_action_template_only_once(monkeypatch):
    prompt = "make the character stand and smile gently with relaxed eyes, hold a small sketchbook in the left hand at chest height and point to it with the right index finger, full body, full scene, locked-off static camera, fixed viewpoint and focal length throughout, plain light, sprite"
    monkeypatch.setattr(
        generation,
        "chat_character_text",
        lambda *_: json.dumps({"items": [{"prompt": prompt, "tagging": "思考，指向"}]}),
    )
    result = generation.plan_sprites(object(), {"setting": "喜欢绘画", "count": 1})
    assert result["items"][0]["prompt"] == prompt


def test_reference_planning_replaces_legacy_full_body_framing(monkeypatch):
    chat = Mock(
        return_value=json.dumps(
            {
                "items": [
                    {
                        "prompt": "make the character stand and smile with relaxed eyebrows and hold both hands together at chest height, full body, full scene, plain light, sprite",
                        "tagging": "微笑，合手",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(generation, "chat_character_text", chat)
    result = generation.plan_sprites(
        object(), {"setting": "温柔", "count": 1, "referenceImage": "half-body.png"}
    )
    prompt = result["items"][0]["prompt"]
    assert "full body" not in prompt
    assert "full scene" not in prompt
    assert "reference image's exact framing, crop" in prompt
    assert "character scale and screen position throughout" in prompt
    assert "keep all pose changes within the original frame" in prompt
    assert "locked-off static camera" in prompt
    assert prompt.count("make the character stand and") == 1

    monkeypatch.setattr(
        generation,
        "chat_character_text",
        lambda *_: json.dumps(result),
    )
    assert (
        generation.plan_sprites(
            object(), {"setting": "温柔", "count": 1, "referenceImage": "half-body.png"}
        )
        == result
    )


def test_planning_without_reference_keeps_full_body_and_a_fixed_camera(monkeypatch):
    chat = Mock(
        return_value='{"items":[{"prompt":"smile warmly with relaxed eyes and rest both hands at the sides","tagging":"微笑，站立"}]}'
    )
    monkeypatch.setattr(generation, "chat_character_text", chat)
    prompt = generation.plan_sprites(object(), {"setting": "开朗", "count": 1})[
        "items"
    ][0]["prompt"]
    assert "full body, full scene" in prompt
    assert "locked-off static camera" in prompt
    assert "reference image" not in prompt
    assert "双脚着地并可见" in chat.call_args.args[1]


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


@pytest.mark.parametrize("animation", [False, True])
def test_generated_replacement_keeps_position_voice_original_file_and_is_idempotent(
    sprite_state, monkeypatch, animation
):
    state, character = sprite_state
    root = Path(state.project_root_dir)
    old = root / "sprites" / "mika" / "one.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"original image must remain")
    character.sprites = [
        {
            "path": str(old),
            "voice_text": "hello",
            "voice_path": "voice.wav",
            "voice_type": "reference",
        },
        {"path": "second.png"},
    ]
    character.emotion_tags = "立绘 1：旧标签\n立绘 2：保留标签\n"
    task_id = completed_sprite(state)
    verifier = Mock(return_value=5)
    monkeypatch.setattr(bridge, "verify_transparent_animation", verifier)
    if animation:
        video = root / "cache" / "sprite_generation" / "one.webm"
        video.write_bytes(b"verified alpha video")
        state.tasks[task_id]["result"].update(
            path=str(video), animation=True, alphaVerified=True
        )
    payload = {
        "name": "Mika",
        "items": [{"taskId": task_id, "tagging": "微笑，挥手"}],
        "replace": {"index": 0, "path": str(old)},
    }
    result = bridge.import_generated_sprites(state, payload)
    assert len(result["sprites"]) == 2
    assert result["sprites"][0]["path"] != str(old)
    assert Path(result["sprites"][0]["path"]).is_file()
    assert result["sprites"][0]["voice_text"] == "hello"
    assert result["sprites"][0]["voice_path"] == "voice.wav"
    assert result["sprites"][0]["voice_type"] == "reference"
    assert result["sprites"][1]["path"] == "second.png"
    assert result["emotion_tags"] == "立绘 1：微笑, 挥手\n立绘 2：保留标签\n"
    assert old.read_bytes() == b"original image must remain"
    assert verifier.call_count == int(animation)
    bridge.import_generated_sprites(state, payload)
    state.config_manager.save_characters_config.assert_called_once()


@pytest.mark.parametrize(
    "target",
    [
        {"index": -1, "path": "old.png"},
        {"index": 10, "path": "old.png"},
        {"index": True, "path": "old.png"},
        {"index": 0, "path": "changed.png"},
    ],
)
def test_replacement_rejects_invalid_or_changed_target_without_importing(
    sprite_state, target
):
    state, character = sprite_state
    task_id = completed_sprite(state)
    with pytest.raises(ValueError):
        bridge.import_generated_sprites(
            state, {"name": "Mika", "items": [{"taskId": task_id}], "replace": target}
        )
    assert len(character.sprites) == 1
    state.config_manager.save_characters_config.assert_not_called()
    assert not state.tasks[task_id]["result"].get("imported")


def test_replacement_save_failure_rolls_back_collection_and_allows_retry(sprite_state):
    state, character = sprite_state
    task_id = completed_sprite(state)
    original = character.sprites
    tags = character.emotion_tags
    state.config_manager.save_characters_config.side_effect = RuntimeError(
        "save failed"
    )
    payload = {
        "name": "Mika",
        "items": [{"taskId": task_id}],
        "replace": {"index": 0, "path": "old.png"},
    }
    with pytest.raises(RuntimeError, match="save failed"):
        bridge.import_generated_sprites(state, payload)
    assert character.sprites is original and character.emotion_tags == tags
    assert not state.tasks[task_id]["result"].get("imported")
    state.config_manager.save_characters_config.side_effect = None
    result = bridge.import_generated_sprites(state, payload)
    assert len(result["sprites"]) == 1


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


def test_idle_animation_prompt_keeps_framing_pose_and_no_appearance():
    from application.characters.animate_sprites import animation_prompt

    pair = animation_prompt({"breeze": True, "tagging": "平静，站立"})
    assert "body and relaxed limbs sway very slightly and slowly" in pair["prompt"]
    assert "hair sway very gently" in pair["prompt"] and "blink" in pair["prompt"]
    assert "hair tips" in pair["prompt"]
    assert "original hand gesture" in pair["prompt"]
    assert "locked-off static camera" in pair["prompt"]
    assert "exact framing" in pair["prompt"]
    assert "full body" not in pair["prompt"]
    assert pair["tagging"] == "平静, 站立"


@pytest.mark.parametrize("loop", [False, True])
def test_animation_render_rebuilds_body_sway_instead_of_reusing_old_prompt(
    tmp_path, monkeypatch, loop
):
    from application.characters import animate_sprites

    renderer = Mock(return_value={"videoPath": str(tmp_path / "idle.mp4")})
    monkeypatch.setattr(animate_sprites, "render_sprite", renderer)
    reference = tmp_path / "half-body.png"
    output = tmp_path / "poster.png"
    store = object()
    result = animate_sprites.render_animation(
        store,
        {
            "prompt": "old shoulder rise and fall, return to the starting pose",
            "breathing": True,
            "blinking": True,
            "breeze": False,
            "loop": loop,
            "tagging": "平静，站立",
        },
        output,
        reference,
    )
    args, kwargs = renderer.call_args
    assert args[0] is store and args[2:] == (output, reference)
    prompt = args[1]["prompt"]
    assert "body and relaxed limbs sway very slightly and slowly" in prompt
    assert "head, neck and torso" in prompt
    for term in ("breath", "respirat", "chest", "abdomen", "inhale", "exhale"):
        assert term not in prompt.lower()
    assert "reference shoulder line almost motionless" in prompt
    assert "original relaxed resting height and slope" in prompt
    assert "ear-to-shoulder clearance" in prompt
    assert "original neck length" in prompt and "chin-to-collar" in prompt
    assert "soft delay" in prompt and "over the whole shot" in prompt
    assert "fixed height" not in prompt
    assert "rise and fall" not in prompt
    assert "pose changes" not in prompt and "return to the starting pose" not in prompt
    assert ("continuous idle rhythm across the loop seam" in prompt) is loop
    assert "full body" not in prompt
    assert kwargs == {
        "require_h3_video": True,
        "loop_reference": loop,
        "stabilize_pose": True,
    }
    assert result["path"] == str(tmp_path / "idle.mp4")
    assert result["playbackSpeed"] == 0.75


def test_blinking_only_keeps_pose_stable_without_adding_body_sway():
    from application.characters.animate_sprites import animation_prompt

    prompt = animation_prompt({"breathing": False, "blinking": True})["prompt"]
    assert "one smooth eyelid-only blink" in prompt
    assert "original head tilt" in prompt
    assert "limbs sway" not in prompt and "hair sway" not in prompt
    assert "original neck length" in prompt
    assert "ear-to-shoulder clearance" in prompt


@pytest.mark.parametrize(
    "payload",
    [
        {"breathing": "true"},
        {"loop": "true"},
        {"motion": 4},
        {"playbackSpeed": True},
        {"playbackSpeed": 0.4},
        {"playbackSpeed": float("nan")},
        {"breathing": False, "blinking": False, "breeze": False},
    ],
)
def test_idle_animation_rejects_invalid_controls(payload):
    from application.characters.animate_sprites import animation_prompt

    with pytest.raises(ValueError):
        animation_prompt(payload)


def test_animation_requires_h3_service_before_requesting_generation(tmp_path):
    store = SimpleNamespace(
        config=SimpleNamespace(
            api_config=SimpleNamespace(t2i_provider="stable diffusion")
        )
    )
    with pytest.raises(ValueError, match="MiniMax H3"):
        generation.render_sprite(
            store,
            {"prompt": "idle", "tagging": "平静"},
            tmp_path / "unused.png",
            tmp_path / "ref.png",
            require_h3_video=True,
        )


def test_animation_matting_failure_can_retry_without_rerender_and_cannot_be_imported(
    sprite_state, monkeypatch
):
    from core.media import alpha_video

    state, character = sprite_state
    root = Path(state.project_root_dir)
    ref = root / "ref.png"
    Image.new("RGB", (8, 8), "white").save(ref)
    monkeypatch.setattr(bridge, "_local_file_access_roots", lambda _: (root,))
    video = root / "cache" / "sprite_generation" / "source.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"mock video")
    renderer = Mock(
        return_value={
            "name": "Mika",
            "prompt": "idle",
            "tagging": "平静",
            "path": str(video),
            "videoPath": str(video),
            "animation": True,
            "playbackSpeed": 0.5,
        }
    )
    monkeypatch.setattr(bridge, "render_animation", renderer)
    matting = Mock(side_effect=RuntimeError("matting failed"))
    monkeypatch.setattr(alpha_video, "remove_video_background", matting)
    task = _create_task(state, kind="character-sprite-animate", title="animate")
    result = bridge.run_sprite_animation(
        state,
        task["id"],
        {"name": "Mika", "referenceImage": str(ref), "tagging": "平静"},
    )
    assert result["alphaVerified"] is False
    assert Path(result["path"]) == video
    assert "matting failed" in result["backgroundRemovalError"]
    assert matting.call_args.kwargs["playback_speed"] == 0.5
    _update_task(state, task["id"], status="succeeded", result=result)
    with pytest.raises(ValueError, match="透明处理"):
        bridge.import_generated_sprites(
            state, {"name": "Mika", "items": [{"taskId": task["id"]}]}
        )

    def finish(source, output, **kwargs):
        output.write_bytes(b"verified alpha")
        return {"alphaVerified": True, "frameCount": 5, "duration": 0.5}

    matting.side_effect = finish
    retry = _create_task(state, kind="character-sprite-cutout", title="retry")
    done = bridge.run_sprite_cutout(
        state, retry["id"], {"name": "Mika", "taskId": task["id"]}
    )
    assert done["alphaVerified"] and done["backgroundRemoved"]
    assert done["path"].endswith("-alpha.webm")
    assert done["videoPath"] == str(video)
    assert "backgroundRemovalError" not in done
    assert renderer.call_count == 1
    assert matting.call_args.kwargs["playback_speed"] == 0.5
    _update_task(state, retry["id"], status="succeeded", result=done)
    verified = Mock(return_value=5)
    monkeypatch.setattr(alpha_video, "verify_alpha_video", verified)
    saved = bridge.import_generated_sprites(
        state, {"name": "Mika", "items": [{"taskId": retry["id"]}]}
    )
    assert saved["sprites"][-1]["path"].endswith("-alpha.webm")
    verified.assert_called_once()


@pytest.mark.parametrize(
    "custom_prompt", [None, "make the character gently sway one sleeve, fixed camera"]
)
def test_h3_animation_anchors_last_frame_to_the_same_reference(
    tmp_path, monkeypatch, custom_prompt
):
    from ai.t2i.t2i_manager import T2IAdapterFactory
    from application.characters.animate_sprites import render_animation

    node = {
        "class_type": "MiniMaxH3ImageToVideo",
        "inputs": {"first_frame": ["114", 0], "vae": ["119", 0], "length": 107},
    }
    video = tmp_path / "original.mp4"
    video.write_bytes(b"source video")
    adapter = Mock(
        supports_reference_images=True,
        workflow_template={
            "131": node,
            "126": {
                "class_type": "BasicGuider",
                "inputs": {"conditioning": ["131", 0]},
            },
        },
        last_video_path=str(video),
        last_video_frame_time=1.0,
    )

    def draw(**kwargs):
        Image.new("RGB", (8, 8), "blue").save(kwargs["file_path"])
        return kwargs["file_path"]

    adapter.generate_image.side_effect = draw
    monkeypatch.setattr(T2IAdapterFactory, "create_adapter", Mock(return_value=adapter))
    api = SimpleNamespace(
        t2i_provider="comfyui",
        t2i_work_path="",
        t2i_api_url="local",
        t2i_default_workflow_path="workflow.json",
        t2i_prompt_node_id="131",
        t2i_output_node_id="92",
    )
    store = SimpleNamespace(
        config=SimpleNamespace(api_config=api),
        merged_t2i_factory_kwargs=lambda _, kwargs: kwargs,
    )
    result = render_animation(
        store,
        {
            "name": "Mika",
            "prompt": "idle",
            "tagging": "平静",
            **({"customPrompt": custom_prompt} if custom_prompt else {}),
        },
        tmp_path / "sprite.png",
        tmp_path / "ref.png",
    )
    assert node["inputs"]["last_frame"] == node["inputs"]["first_frame"]
    assert Path(result["videoPath"]) == video
    if custom_prompt:
        assert adapter.generate_image.call_args.kwargs["prompt"] == custom_prompt
    guides = [
        (key, item)
        for key, item in adapter.workflow_template.items()
        if item["class_type"] == "MiniMaxH3AddGuide"
    ]
    assert len(guides) == 2
    assert adapter.workflow_template["126"]["inputs"]["conditioning"] == [
        guides[-1][0],
        0,
    ]


@pytest.mark.parametrize(
    "length,frames",
    [(5, []), (106, [10, 96]), (124, [12, 111])],
)
def test_idle_pose_guides_preserve_reference_sampler_graph_and_source_workflow(
    length, frames
):
    from application.characters.h3_idle_workflow import stabilize_idle_workflow

    path = (
        Path(generation.__file__).resolve().parents[2]
        / "ai/t2i/workflows/minimax_h3_i2v_api.json"
    )
    workflow = json.loads(path.read_text(encoding="utf-8"))
    workflow["131"]["inputs"]["length"] = length
    original = json.loads(json.dumps(workflow))
    prepared = stabilize_idle_workflow(workflow)
    guides = [
        (key, value["inputs"]) for key, value in prepared.items() if key not in workflow
    ]
    assert [inputs["frame_idx"] for _, inputs in guides] == frames
    assert not guides or guides[0][1]["positive"] == ["131", 0]
    for (previous, _), (_, inputs) in zip(guides, guides[1:]):
        assert inputs["positive"] == [previous, 0]
    assert prepared["126"]["inputs"]["conditioning"] == (
        [guides[-1][0], 0] if guides else ["131", 0]
    )
    for key, inputs in guides:
        assert prepared[key]["class_type"] == "MiniMaxH3AddGuide"
        assert inputs["image"] == workflow["131"]["inputs"]["first_frame"]
        assert inputs["vae"] == workflow["131"]["inputs"]["vae"]
        assert inputs["latent"] == ["131", 1]
    assert workflow == original
    for key in original.keys() - {"126"}:
        assert prepared[key] == original[key]


@pytest.mark.parametrize("length", [True, 4, ["length-node", 0]])
def test_idle_pose_guides_reject_unresolved_or_invalid_length(length):
    from application.characters.h3_idle_workflow import stabilize_idle_workflow

    with pytest.raises(ValueError, match="整数配置 length"):
        stabilize_idle_workflow(
            {
                "h3": {
                    "class_type": "MiniMaxH3ImageToVideo",
                    "inputs": {"length": length},
                }
            }
        )


def test_manual_animation_prompt_replaces_presets_without_rewriting_the_text():
    from application.characters.animate_sprites import animation_prompt

    text = "保持原图取景，左手缓慢挥动，头发轻轻晃动，镜头固定。"
    result = animation_prompt(
        {
            "customPrompt": f"  {text}  ",
            "tagging": "微笑，挥手",
            "breathing": False,
            "blinking": False,
            "breeze": False,
            "motion": "This preset supplement must not be appended",
            "loop": False,
        }
    )
    assert result == {"prompt": text, "tagging": "微笑, 挥手"}


@pytest.mark.parametrize("custom", [None, "", "   ", 2, "x" * 12001])
def test_manual_animation_rejects_invalid_prompt_instead_of_falling_back(custom):
    from application.characters.animate_sprites import animation_prompt

    with pytest.raises(ValueError):
        animation_prompt({"customPrompt": custom})
