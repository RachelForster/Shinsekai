import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from application.characters.sprite.mouth_sync import build_bundle, mouth_frame_count, validate_manual
from application.runtime.tasks import _create_task, _update_task
from config.character_manager import CharacterManager
from config.schema import Character
from core.sprite.mouth.manifest import correction, read_manifest, valid_mouth_sync
from core.sprite.transitions import sprite_fingerprint
from application.characters.sprite import mouth_sync as bridge


def bundle(directory, source):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("closed", "half", "open"):
        Image.new("RGBA", (12, 8), (220, 150, 160, 220)).save(directory / f"mouth-{name}.png")
    Image.new("RGB", (80, 120), "white").save(directory / "reference.png")
    data = {
        "version": 1, "sourceFingerprint": sprite_fingerprint(source),
        "width": 80, "height": 120, "fps": 0, "duration": 0,
        "patchBox": [34, 30, 46, 38],
        "mouths": {name: f"mouth-{name}.png" for name in ("closed", "half", "open")},
        "track": [{"time": 0, "matrix": [1, 0, 0, 1, 0, 0]}],
        "correction": correction(),
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "data/sprite/mika/source.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (80, 120), "pink").save(source)
    character = Character(name="Mika", color="#fff", sprite_prefix="mika", sprites=[{"path": str(source), "voice_text": "keep me"}])
    store = SimpleNamespace(get_character_by_name=lambda name: character if name == "Mika" else None, save_characters_config=Mock(), reload=Mock())
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = store
    monkeypatch.setattr(bridge, "_local_file_access_roots", lambda _: (tmp_path,))
    return SimpleNamespace(config_manager=store, character_manager=manager, task_lock=threading.Lock(), tasks={}, project_root_dir=str(tmp_path)), character, source


def complete(state, source):
    task = _create_task(state, kind="character-sprite-mouth", title="mouth")
    directory = Path(state.project_root_dir) / "cache/sprite_generation" / f"{task['id']}-mouth"
    path, _ = bundle(directory, source)
    result = {"name": "Mika", "spritePath": str(source), "sourceFingerprint": sprite_fingerprint(source), "taskId": task["id"], "manifestPath": str(path), "ready": True}
    _update_task(state, task["id"], status="succeeded", result=result)
    return result


def test_save_binds_bundle_and_retains_sprite_voice_fields(state):
    current, character, source = state
    result = complete(current, source)
    saved = bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"], "correction": {"offsetX": 3, "scale": 1.2}}]})
    entry = character.sprites[0]
    assert entry["voice_text"] == "keep me"
    assert saved["sprites"][0]["mouth_sync"] == entry["mouth_sync"]
    assert Path(entry["mouth_sync"]).is_relative_to(source.parent / "mouth-sync")
    assert read_manifest(entry["mouth_sync"])["correction"]["offsetX"] == 3
    assert valid_mouth_sync(entry)
    current.config_manager.save_characters_config.assert_called_once()


def test_changed_source_cannot_receive_an_old_result(state):
    current, _, source = state
    result = complete(current, source)
    Image.new("RGB", (80, 120), "blue").save(source)
    with pytest.raises(ValueError, match="变化"):
        bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    assert not list((source.parent / "mouth-sync").glob("*/manifest.json"))


def test_eye_frames_can_be_saved_and_corrected_without_rebuilding_mouth_assets(state):
    current, character, source = state
    result = complete(current, source)
    original = Path(result["manifestPath"]).parent
    (original / "speech.mp4").write_bytes(b"clip")
    frames = original / "frames"
    frames.mkdir()
    for index in range(4):
        Image.new("RGB", (20, 20), "pink").save(frames / f"{index:03d}.jpg")
    def save_eyes(eyes, task=result):
        bridge.save_sprite_mouths(current, {
            "name": "Mika", "eyesOnly": True, "items": [{"taskId": task["taskId"], "eyeFrames": eyes}],
        })

    with pytest.raises(ValueError, match="先保存"):
        save_eyes({"closed": 2})
    bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    saved = Path(character.sprites[0]["mouth_sync"])
    assert "eyeFrames" not in bridge.describe_bundle(current, saved)
    eyes = {"open": 0, "half": 1, "closed": 3}
    save_eyes(eyes)
    assert Path(character.sprites[0]["mouth_sync"]) == saved
    assert bridge.describe_bundle(current, saved)["eyeFrames"] == eyes
    assert (saved.parent / "mouth-open.png").read_bytes() == (original / "mouth-open.png").read_bytes()
    with pytest.raises(ValueError, match="不同帧"):
        save_eyes({"open": 0, "closed": 0})
    assert bridge.describe_bundle(current, saved)["eyeFrames"] == eyes
    cached = {**result, "manifestPath": str(saved)}
    _update_task(current, result["taskId"], result=cached)
    bridge.save_sprite_mouths(current, {
        "name": "Mika", "items": [{"taskId": result["taskId"], "correction": {"offsetX": 3}}],
    })
    newer = Path(character.sprites[0]["mouth_sync"])
    assert bridge.describe_bundle(current, newer)["eyeFrames"] == eyes
    save_eyes({})
    assert "eyeFrames" not in bridge.describe_bundle(current, newer)
    assert read_manifest(newer)["correction"]["offsetX"] == 3
    assert Path(character.sprites[0]["mouth_sync"]) == newer
    bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    assert "eyeFrames" not in bridge.describe_bundle(current, character.sprites[0]["mouth_sync"])

    different = complete(current, source)
    Path(different["manifestPath"]).with_name("speech.mp4").write_bytes(b"different clip")
    with pytest.raises(ValueError, match="当前说话视频"):
        save_eyes({}, different)


@pytest.mark.parametrize("clear_manual", [False, True])
def test_retrying_frames_inherits_manual_placement_and_playback_correction(state, monkeypatch, clear_manual):
    current, _, source = state
    previous = complete(current, source)
    manual = {"mouthBox": [.4, .35, .6, .48], "chin": [.5, .55]}
    adjustments = correction({"offsetX": 3, "scale": 1.2})
    _update_task(current, previous["taskId"], result={**previous, "manual": manual, "profile": {"correction": adjustments}})
    monkeypatch.setattr(bridge.mouth_resources, "status", lambda *_: {"runtimeReady": True, "modelsReady": True})
    analyze = Mock(return_value={"ready": False})
    monkeypatch.setattr(bridge, "build_bundle", analyze)
    frames = {"closed": 7, "half": 1, "open": 18}
    task = _create_task(current, kind="character-sprite-mouth", title="mouth retry")
    payload = {"name": "Mika", "spritePath": str(source), "retryTaskId": previous["taskId"], "selectedFrames": frames}
    if clear_manual:
        payload["manual"] = None
    bridge.run_sprite_mouth(current, task["id"], payload)
    received = analyze.call_args.args[6]
    assert received["manual"] == (None if clear_manual else manual)
    assert received["correction"] == adjustments
    assert received["selectedFrames"] == frames


def test_save_failure_rolls_back_binding_and_new_bundle(state):
    current, character, source = state
    result = complete(current, source)
    current.config_manager.save_characters_config.side_effect = RuntimeError("disk unavailable")
    with pytest.raises(RuntimeError, match="disk unavailable"):
        bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    assert not character.sprites[0].get("mouth_sync")
    assert not list((source.parent / "mouth-sync").glob("*/manifest.json"))
    assert Path(result["manifestPath"]).is_file()


def test_remove_does_not_delete_source_or_saved_resources(state):
    current, character, source = state
    result = complete(current, source)
    bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    profile = character.sprites[0]["mouth_sync"]
    bridge.remove_sprite_mouth(current, {"name": "Mika", "spritePath": str(source)})
    assert character.sprites[0]["mouth_sync"] is None
    assert source.is_file() and Path(profile).is_file()


@pytest.mark.parametrize("change", [
    {"mouths": {"closed": "../../secret.png", "half": "mouth-half.png", "open": "mouth-open.png"}},
    {"track": [{"time": 0, "matrix": [0, 0, 0, 0, 0, 0]}]},
    {"track": [{"time": 0, "matrix": [1, 0, 0, 1, float("nan"), 0]}]},
    {"track": [{"time": 1, "matrix": [1, 0, 0, 1, 0, 0]}, {"time": 0, "matrix": [1, 0, 0, 1, 0, 0]}]},
    {"patchBox": [45, 30, 30, 38]},
])
def test_manifest_rejects_unsafe_or_unusable_data(state, change):
    current, _, source = state
    path, data = bundle(Path(current.project_root_dir) / "bundle", source)
    data.update(change)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_manifest(path)


def test_manifest_cannot_be_read_outside_owned_media_roots(state):
    current, _, source = state
    path, _ = bundle(Path(current.project_root_dir) / "unowned", source)
    with pytest.raises(PermissionError):
        bridge.describe_bundle(current, str(path))


@pytest.mark.parametrize("value", [
    {"mouthBox": [0, 0, .2, .1]},
    {"mouthBox": [0, 0, .2, .1], "chin": [0, float("nan")]},
    {"mouthBox": [.4, .3, .2, .4], "chin": [.5, .5]},
    {"mouthBox": [0, 0, 1, 1], "chin": [True, 0]},
])
def test_manual_coordinates_are_checked_before_worker(value):
    with pytest.raises(ValueError):
        validate_manual(value)


def test_closed_only_video_is_not_mislabeled_as_three_mouth_states():
    pytest.importorskip("cv2")
    from core.sprite.mouth.extraction import choose_frames
    with pytest.raises(ValueError, match="开合|幅度"):
        choose_frames([.01, .012, .015, .02, .025], [1] * 5)


def test_mouth_selection_uses_openness_instead_of_frame_order():
    pytest.importorskip("cv2")
    from core.sprite.mouth.extraction import choose_frames
    ratios = [.9, .01, .45, .91, .02, .43]
    selected = choose_frames(ratios, [1] * len(ratios))
    assert ratios[selected["closed"]] < .1
    assert .3 < ratios[selected["half"]] < .6
    assert ratios[selected["open"]] > .8


def test_mouth_selection_keeps_original_indices_when_some_frames_are_unreliable():
    pytest.importorskip("cv2")
    from core.sprite.mouth.extraction import choose_frames
    assert choose_frames([None, .03, None, .42, .83, None], [.9] * 6) == {"closed": 1, "half": 3, "open": 4}


def test_auto_mouth_extraction_skips_frames_crossing_the_nose_or_chin(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from core.sprite.mouth import extraction

    points = np.ones((28, 3), dtype=np.float32)
    points[11:17, :2], points[17:23, :2] = [37, 30], [83, 30]
    points[23, :2], points[2, :2] = [60, 45], [60, 92]
    points[24:28, :2] = [[47, 64], [60, 63], [73, 64], [60, 65]]
    bounds = [(63, 65), (39, 84), (61, 70), (57, 78), (57, 75)]
    images = [np.full((120, 120, 3), i, dtype=np.uint8) for i in range(len(bounds))]
    bbox = np.array([30, 20, 90, 100, 1])

    def detect(_detector, image, **_options):
        top, bottom = bounds[image[0, 0, 0]]
        frame = points.copy()
        frame[[25, 27], 1] = [top, bottom]
        return {"bbox": bbox, "keypoints": frame}

    def interior(image, _points):
        # A dark opening over the jaw can extend past the reported lower lip.
        if image[0, 0, 0] == 3:
            return 1.5, np.array([[47, 58], [73, 58], [73, 96], [47, 96]])
        return None, None

    monkeypatch.setattr(extraction, "detect", detect)
    monkeypatch.setattr(extraction, "_interior_opening", interior)
    result = extraction.extract(None, images, images[0], {"keypoints": points}, [0, 0, 120, 120], tmp_path)
    assert result["selectedFrames"] == {"closed": 0, "half": 2, "open": 4}
    assert result["openness"][1] is None and result["openness"][3] is None


def test_short_clip_keeps_transition_pose_when_wide_mouth_is_held_longer():
    pytest.importorskip("cv2")
    from core.sprite.mouth.extraction import choose_frames
    ratios = [.006] * 4 + [.637, .819, .865, .915, .947, .906] + [.858] * 10 + [.756, .006]
    selected = choose_frames(ratios, [1] * len(ratios))
    assert ratios[selected["closed"]] < .01
    assert ratios[selected["half"]] == .637
    assert ratios[selected["open"]] > .8


def test_config_and_image_changes_invalidate_saved_mouth(state):
    current, _, source = state
    result = complete(current, source)
    entry = {"path": str(source), "mouth_sync": result["manifestPath"]}
    assert valid_mouth_sync(entry)
    Image.new("RGB", (80, 120), "green").save(source)
    assert valid_mouth_sync(entry) == ""


def test_saved_profile_is_reused_without_loading_models_or_starting_generation(state, monkeypatch):
    current, character, source = state
    result = complete(current, source)
    directory = Path(result["manifestPath"]).parent
    keypoints = [[0, 0, 1]] * 24 + [[2, 46, 1], [14, 44, 1], [25, 46, 1], [14, 48, 1]]
    old_suggestion = {"mouthBox": [2 / 80, 42 / 120, 25 / 80, 50 / 120], "chin": [.2, .5]}
    (directory / "prepared.json").write_text(json.dumps({"keypoints": keypoints, "suggestedManual": old_suggestion}))
    bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    monkeypatch.setattr(bridge.mouth_resources, "status", Mock(side_effect=AssertionError("inference should not run")))
    cached = bridge.run_sprite_mouth(current, "cached-task", {"name": "Mika", "spritePath": str(source)})
    assert cached["ready"] and cached["cached"]
    assert Path(cached["manifestPath"]).resolve() == Path(character.sprites[0]["mouth_sync"])
    assert cached["suggestedManual"] == {"mouthBox": [0, 39 / 120, 30 / 80, 53 / 120], "chin": [.2, .5]}


def test_playback_resources_use_allowed_relative_media_paths(state):
    from frontend_bridge_core.routes.file_transport import resolve_media_path
    from application.chat.presentation.character_visual import resolve_character_visual
    current, character, source = state
    result = complete(current, source)
    bridge.save_sprite_mouths(current, {"name": "Mika", "items": [{"taskId": result["taskId"]}]})
    data = bridge.describe_bundle(current, character.sprites[0]["mouth_sync"])
    for path in data["profile"]["mouths"].values():
        assert not Path(path).is_absolute()
        assert resolve_media_path(current, path).is_file()
    assert bridge.read_profile(current, data["manifestPath"])["mouths"]["open"] == "mouth-open.png"
    visual = resolve_character_visual(character, 0, SimpleNamespace(media_url=lambda path: path))
    assert visual.mouth_sync == data["manifestPath"]


def test_mouth_bundle_survives_character_export_and_import(tmp_path, monkeypatch):
    from config.character_config import CharacterConfig
    from tools import file_util

    def configure(root):
        root.mkdir(parents=True)
        monkeypatch.chdir(root)
        for key, suffix in [("SPRITE_DIR", "sprite"), ("SPEECH_DIR", "speech"), ("MODEL_DIR", "models"), ("CONFIG_DIR", "config")]:
            directory = root / "data" / suffix
            directory.mkdir(parents=True)
            monkeypatch.setattr(file_util, key, directory)
        config = root / "data/config/characters.yaml"
        config.write_text("[]")
        monkeypatch.setattr(file_util, "CHARACTERS_CONFIG_PATH", config)

    configure(tmp_path / "source")
    source = file_util.SPRITE_DIR / "mika/source.png"
    source.parent.mkdir()
    Image.new("RGBA", (80, 120), "pink").save(source)
    manifest, _ = bundle(source.parent / "mouth-sync/test", source)
    config = CharacterConfig.parse_dic({"name": "Mika", "color": "#fff", "sprite_prefix": "mika", "sprites": [{"path": str(source), "mouth_sync": str(manifest)}]})
    package = tmp_path / "mouth.char"
    file_util.export_character([config], str(package), open_folder=False)
    configure(tmp_path / "destination")
    restored = file_util.import_character(str(package))[0]
    entry = restored.sprites[0]
    assert valid_mouth_sync(entry)
    assert Path(entry["mouth_sync"]).is_relative_to(tmp_path / "destination/data/sprite")
    assert Path(entry["mouth_sync"]).parent.joinpath("mouth-open.png").is_file()


@pytest.mark.parametrize("frame_count", [5, 22, 39])
def test_mouth_render_requests_selected_frames_and_reuses_first_reference_as_last(tmp_path, monkeypatch, frame_count):
    from ai.t2i.t2i_manager import T2IAdapterFactory, T2IManager
    from application.characters.sprite.generate_sprites import render_sprite

    video = tmp_path / "generated.mp4"
    video.write_bytes(b"video")
    adapter = Mock(supports_reference_images=True, last_video_path=str(video), last_video_frame_time=0.)
    adapter.workflow_template = {"1": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"length": 107, "first_frame": ["2", 0]}}, "3": {"class_type": "CreateVideo", "inputs": {"fps": 30}}}
    monkeypatch.setattr(T2IAdapterFactory, "create_adapter", Mock(return_value=adapter))
    def draw(_manager, _prompt, *, file_path, **kwargs):
        Image.new("RGB", (8, 8)).save(file_path)
        return file_path
    monkeypatch.setattr(T2IManager, "t2i", draw)
    api = SimpleNamespace(t2i_provider="comfyui", t2i_work_path="", t2i_api_url="local", t2i_default_workflow_path="workflow.json", t2i_prompt_node_id="1", t2i_output_node_id="3")
    store = SimpleNamespace(config=SimpleNamespace(api_config=api), merged_t2i_factory_kwargs=lambda _, values: values)
    result = render_sprite(store, {"prompt": "talk", "tagging": "口型"}, tmp_path / "result.png", tmp_path / "reference.png", require_h3_video=True, loop_reference=True, h3_frame_count=frame_count)
    assert adapter.workflow_template["1"]["inputs"]["length"] == frame_count
    assert adapter.workflow_template["1"]["inputs"]["last_frame"] == ["2", 0]
    assert adapter.workflow_template["3"]["inputs"]["fps"] == 24
    assert result["videoPath"] == video.as_posix()


@pytest.mark.parametrize("value", [True, None, "22", 22.0, 0, 21, 56])
def test_mouth_frame_count_rejects_invalid_choices(value):
    with pytest.raises(ValueError, match="5、22 或 39"):
        mouth_frame_count({"frameCount": value})


@pytest.mark.parametrize("options, expected", [({}, 22), ({"frameCount": 5}, 5), ({"frameCount": 39}, 39), ({"includeBlink": True}, 22)])
def test_bundle_passes_selected_length_to_generator(tmp_path, monkeypatch, options, expected):
    from application.characters.sprite import mouth_sync

    source = tmp_path / "reference.png"
    Image.new("RGB", (80, 120), "pink").save(source)
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"video")
    worker = Mock(side_effect=[{"suggestedManual": None}, {"ready": False}])
    renderer = Mock(return_value={"videoPath": str(video)})
    monkeypatch.setattr(mouth_sync, "invoke_worker", worker)
    monkeypatch.setattr(mouth_sync, "render_sprite", renderer)
    build_bundle(tmp_path, None, source, source, tmp_path / "mouth", sprite_fingerprint(source), {"name": "Mika", **options}, Mock())
    assert renderer.call_args.kwargs["h3_frame_count"] == expected
    prompt = renderer.call_args.args[1]["prompt"]
    assert ("eyelids fully closed" in prompt) == options.get("includeBlink", False)
