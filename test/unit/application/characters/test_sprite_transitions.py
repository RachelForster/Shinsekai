import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from application.characters import transition_sprites as generation
from application.chat.presentation.character_visual import resolve_character_visual
from application.media.resource_urls import UnconfiguredResourceUrls
from application.runtime.tasks import _create_task, _update_task
from config.character_manager import CharacterManager
from config.schema import Character, SpriteTransition
from core.sprite.transitions import sprite_fingerprint, valid_transitions
from application.characters.generate_sprites import boundary_frame
from frontend_bridge_core import sprite_generation, sprite_transitions as bridge


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = [tmp_path / "first.png", tmp_path / "last.png"]
    for path, color in zip(paths, ["red", "blue"]):
        Image.new("RGBA", (64, 96), color).save(path)
    character = Character(
        name="Mika",
        color="#fff",
        sprite_prefix="mika",
        sprites=[{"path": str(path)} for path in paths],
    )
    store = SimpleNamespace(
        get_character_by_name=lambda name: character if name == "Mika" else None,
        save_characters_config=Mock(),
        reload=Mock(),
    )
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = store
    monkeypatch.setattr(
        "config.character_manager.UPLOAD_DIR", str(tmp_path / "data/sprite")
    )
    monkeypatch.setattr(bridge, "_local_file_access_roots", lambda _: (tmp_path,))
    state = SimpleNamespace(
        config_manager=store,
        character_manager=manager,
        task_lock=threading.Lock(),
        tasks={},
        project_root_dir=str(tmp_path),
    )
    return state, character, paths


def completed(state, paths, *, kind="character-sprite-transition"):
    task = _create_task(state, kind=kind, title="transition")
    root = Path(state.project_root_dir) / "cache/sprite_generation"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{task['id']}.webm"
    path.write_bytes(b"alpha video")
    identity = generation.transition_identity(
        state.config_manager.get_character_by_name("Mika"), *map(str, paths)
    )
    _update_task(
        state,
        task["id"],
        status="succeeded",
        result={
            **identity,
            "taskId": task["id"],
            "path": str(path),
            "alphaVerified": True,
            "frameCount": 22,
        },
    )
    return task["id"]


@pytest.mark.parametrize("experimental", [False, True])
def test_render_forces_twenty_two_frames_distinct_anchors_and_coordinated_hair(
    tmp_path, monkeypatch, experimental
):
    from ai.t2i.t2i_manager import T2IAdapterFactory

    workflow = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "ai/t2i/workflows/minimax_h3_i2v_api.json"
        ).read_text()
    )
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    for path, size, color in ((first, (128, 192), "red"), (last, (64, 96), "blue")):
        anchor = Image.new("RGBA", size)
        ImageDraw.Draw(anchor).rectangle(
            (16, 16, size[0] - 16, size[1] - 16), fill=color
        )
        anchor.save(path)
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    adapter = Mock(
        supports_reference_images=True,
        workflow_template=workflow,
        last_video_path=str(video),
        last_video_frame_time=0,
    )

    def draw(**kwargs):
        Image.new("RGB", (64, 96)).save(kwargs["file_path"])
        return kwargs["file_path"]

    adapter.generate_image.side_effect = draw
    monkeypatch.setattr(T2IAdapterFactory, "create_adapter", Mock(return_value=adapter))
    api = SimpleNamespace(
        t2i_provider="comfyui",
        t2i_work_path="",
        t2i_api_url="local",
        t2i_default_workflow_path="workflow",
        t2i_prompt_node_id="131",
        t2i_output_node_id="92",
    )
    store = SimpleNamespace(
        config=SimpleNamespace(api_config=api),
        merged_t2i_factory_kwargs=lambda _, kwargs: kwargs,
    )
    result = generation.render_transition(
        store,
        {
            "name": "Mika",
            **({"autoScreen": True, "alphaMatting": True} if experimental else {}),
        },
        tmp_path / "out.png",
        first,
        last,
    )
    inputs = workflow["131"]["inputs"]
    assert inputs["length"] == 22
    assert inputs["first_frame"] == ["114", 0]
    assert inputs["last_frame"] == ["shinsekai_last_frame", 0]
    assert inputs["width"] / inputs["height"] == pytest.approx(2 / 3, abs=0.03)
    assert workflow["130"]["inputs"]["fps"] == 24
    assert adapter.reference_node_id == "114"
    assert adapter.generate_image.call_args.kwargs["last_reference_image_path"] == str(
        last
    )
    if experimental:
        assert adapter.generate_image.call_args.kwargs[
            "reference_background_color"
        ] == (0, 255, 0)
        assert (
            "uniform solid green chroma-key background"
            in adapter.generate_image.call_args.kwargs["prompt"]
        )
        assert result["matting"]["screenColor"] == [0, 255, 0]
        assert result["matting"]["alphaMatting"] is True
    else:
        assert (
            "reference_background_color" not in adapter.generate_image.call_args.kwargs
        )
        assert "chroma-key" not in adapter.generate_image.call_args.kwargs["prompt"]
        assert result["matting"] == {
            "method": "ai",
            "alphaMatting": False,
            "model": "toonout",
        }
    assert not any(
        node["class_type"] == "MiniMaxH3AddGuide" for node in workflow.values()
    )
    assert result["playbackSpeed"] == 1
    assert "locked-off static camera" in result["prompt"]
    assert "full body" not in result["prompt"]
    assert "begin changing pose immediately" in result["prompt"]
    assert "by the final frame" in result["prompt"]
    assert "tiny" not in result["prompt"]
    assert "hair roots follow the head and torso motion" in result["prompt"]
    assert "natural inertia and coordinated follow-through" in result["prompt"]
    assert result["requestedFrames"] == 22


def test_saving_is_separate_directed_idempotent_and_invalidated_on_source_change(
    state, monkeypatch
):
    state, character, paths = state
    monkeypatch.setattr(bridge, "verify_transparent_animation", Mock(return_value=22))
    ids = [completed(state, paths), completed(state, paths[::-1])]
    payload = {"name": "Mika", "items": [{"taskId": value} for value in ids]}
    saved = bridge.save_sprite_transitions(state, payload)
    assert len(saved["sprite_transitions"]) == 2
    assert len(character.sprites) == 2 and character.emotion_tags == ""
    assert len(list(valid_transitions(character))) == 2
    for edge in character.sprite_transitions:
        assert Path(edge.path).read_bytes() == b"alpha video"
        assert edge.frame_count == 22
    bridge.save_sprite_transitions(state, payload)
    assert state.config_manager.save_characters_config.call_count == 1
    character.sprites.reverse()
    visual = resolve_character_visual(character, 0, UnconfiguredResourceUrls())
    assert visual.event_fields()["transitions"][0]["fromUrl"] == str(paths[0])
    assert "transitions" not in visual.snapshot_fields()
    from application.chat.presentation import character_visual

    calibration = {"from": {"luma": 100}, "first": {"luma": 96}}
    prepare = Mock(return_value=calibration)
    monkeypatch.setattr(character_visual, "transition_presentation", prepare)
    calibrated = resolve_character_visual(character, 0, UnconfiguredResourceUrls())
    assert calibrated.event_fields()["transitions"][0]["presentation"] == calibration
    prepare.assert_called_once()
    assert "transitions" not in calibrated.snapshot_fields()
    Image.new("RGBA", (64, 96), "green").save(paths[0])
    assert not list(valid_transitions(character))
    assert (
        "transitions"
        not in resolve_character_visual(
            character, 0, UnconfiguredResourceUrls()
        ).event_fields()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-kind",
        "wrong-character",
        "opaque",
        "changed",
        "removed",
        "outside",
        "frames",
    ],
)
def test_save_rejects_untrusted_stale_or_non_twenty_two_frame_results(
    state, monkeypatch, mutation
):
    state, character, paths = state
    verify = Mock(return_value=5 if mutation == "frames" else 22)
    monkeypatch.setattr(bridge, "verify_transparent_animation", verify)
    task_id = completed(state, paths)
    task = state.tasks[task_id]
    result = task["result"]
    if mutation == "wrong-kind":
        task["kind"] = "character-sprite-animate"
    if mutation == "wrong-character":
        result["name"] = "Other"
    if mutation == "opaque":
        result["alphaVerified"] = False
    if mutation == "changed":
        paths[0].write_bytes(b"changed")
    if mutation == "removed":
        character.sprites.pop()
    if mutation == "outside":
        result["path"] = str(paths[0])
    with pytest.raises((ValueError, PermissionError)):
        bridge.save_sprite_transitions(
            state, {"name": "Mika", "items": [{"taskId": task_id}]}
        )
    assert not character.sprite_transitions
    state.config_manager.save_characters_config.assert_not_called()


def test_save_rolls_back_copies_and_can_retry(state, monkeypatch):
    state, character, paths = state
    monkeypatch.setattr(bridge, "verify_transparent_animation", Mock(return_value=22))
    task_id = completed(state, paths)
    payload = {"name": "Mika", "items": [{"taskId": task_id}]}
    state.config_manager.save_characters_config.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        bridge.save_sprite_transitions(state, payload)
    assert not character.sprite_transitions
    assert not list((Path(state.project_root_dir) / "data/sprite").rglob("*.webm"))
    assert not state.tasks[task_id]["result"].get("imported")
    state.config_manager.save_characters_config.side_effect = None
    bridge.save_sprite_transitions(state, payload)
    assert len(character.sprite_transitions) == 1


def test_matting_retry_does_not_generate_again_and_saved_pairs_reuse_cache(
    state, monkeypatch
):
    state, character, paths = state
    root = Path(state.project_root_dir) / "cache/sprite_generation"
    root.mkdir(parents=True)
    video = root / "raw.mp4"
    video.write_bytes(b"raw")
    render = Mock(
        return_value={
            "videoPath": str(video),
            "playbackSpeed": 1,
            "prompt": "transition",
            "tagging": "过渡",
            "requestedFrames": 22,
        }
    )
    monkeypatch.setattr(bridge, "render_transition", render)
    matte = Mock(side_effect=RuntimeError("matting failed"))
    monkeypatch.setattr(sprite_generation, "make_transparent_animation", matte)
    payload = {"name": "Mika", "fromPath": str(paths[0]), "toPath": str(paths[1])}
    first = _create_task(state, kind="character-sprite-transition", title="transition")
    result = bridge.run_sprite_transition(state, first["id"], payload)
    assert result["alphaVerified"] is False
    assert matte.call_args.kwargs["playback_speed"] == 1
    _update_task(state, first["id"], status="succeeded", result=result)

    def finish(source, output, **kwargs):
        output.write_bytes(b"alpha video")
        return {"alphaVerified": True, "frameCount": 22}

    matte.side_effect = finish
    retry = _create_task(state, kind="character-sprite-transition", title="retry")
    result = bridge.run_sprite_transition(
        state, retry["id"], {**payload, "retryTaskId": first["id"]}
    )
    assert result["alphaVerified"] and "backgroundRemovalError" not in result
    assert render.call_count == 1
    _update_task(state, retry["id"], status="succeeded", result=result)
    monkeypatch.setattr(bridge, "verify_transparent_animation", Mock(return_value=22))
    bridge.save_sprite_transitions(
        state, {"name": "Mika", "items": [{"taskId": retry["id"]}]}
    )
    cached = bridge.run_sprite_transition(state, "cached", payload)
    assert cached["cached"] and render.call_count == 1


def test_legacy_five_frame_transition_still_plays_but_generation_rebuilds_it(
    state, monkeypatch
):
    state, character, paths = state
    task_id = completed(state, paths)
    result = state.tasks[task_id]["result"]
    character.sprite_transitions = [
        SpriteTransition(
            from_path=str(paths[0]),
            to_path=str(paths[1]),
            path=result["path"],
            from_fingerprint=result["fromFingerprint"],
            to_fingerprint=result["toFingerprint"],
        )
    ]
    assert character.sprite_transitions[0].frame_count == 5
    assert (
        "transitions"
        in resolve_character_visual(
            character, 1, UnconfiguredResourceUrls()
        ).event_fields()
    )
    render = Mock(return_value={"videoPath": result["path"], "requestedFrames": 22})
    monkeypatch.setattr(bridge, "render_transition", render)
    monkeypatch.setattr(
        bridge,
        "_finish_animation",
        Mock(return_value={"alphaVerified": True, "frameCount": 22}),
    )
    task = _create_task(state, kind="character-sprite-transition", title="upgrade")
    upgraded = bridge.run_sprite_transition(
        state,
        task["id"],
        {"name": "Mika", "fromPath": str(paths[0]), "toPath": str(paths[1])},
    )
    render.assert_called_once()
    assert upgraded["frameCount"] == 22 and not upgraded.get("cached")
    assert (
        character.sprite_transitions[0].frame_count == 5
    )  # Replaced only after explicit save.


def alpha_clip(path, frames=22):
    import av
    import numpy as np

    with av.open(str(path), "w", format="webm") as container:
        stream = container.add_stream("libvpx-vp9", rate=24)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuva420p"
        stream.options = {"lossless": "1", "auto-alt-ref": "0"}
        for color in ["red"] + ["green"] * (frames - 2) + ["blue"]:
            image = Image.new("RGBA", (32, 32), color)
            image.paste((0, 0, 0, 0), (0, 0, 8, 32))
            for packet in stream.encode(
                av.VideoFrame.from_ndarray(np.asarray(image), format="rgba")
            ):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_video_endpoints_preserve_alpha_and_first_last_direction(tmp_path):
    source = tmp_path / "alpha.webm"
    alpha_clip(source)
    for last, channel in [(False, 0), (True, 2)]:
        output = boundary_frame(source, tmp_path / f"{last}.png", last=last)
        with Image.open(output) as image:
            assert image.mode == "RGBA"
            assert image.getpixel((0, 0))[3] == 0
            assert image.getpixel((16, 16))[3] == 255
            assert image.getpixel((16, 16))[channel] > 200


@pytest.mark.parametrize("transparent", [False, True])
def test_animation_from_saved_video_uses_first_frame_and_preserves_alpha(
    state, tmp_path, monkeypatch, transparent
):
    from core.media.chroma_key import choose_screen_color

    app, character, _ = state
    source = tmp_path / ("saved-alpha.webm" if transparent else "saved.mp4")
    if transparent:
        alpha_clip(source)
    else:
        import av

        with av.open(str(source), "w") as container:
            stream = container.add_stream("mpeg4", rate=24)
            stream.width = stream.height = 32
            stream.pix_fmt = "yuv420p"
            for color in ["red", "green", "blue"]:
                for packet in stream.encode(
                    av.VideoFrame.from_image(Image.new("RGB", (32, 32), color))
                ):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    character.sprites.append({"path": source.as_posix()})
    before = source.read_bytes()
    monkeypatch.setattr(
        sprite_generation, "_local_file_access_roots", lambda _: (tmp_path,)
    )

    def render(config, payload, output, reference):
        assert reference.parent == output.parent
        assert reference.name.endswith("-reference.png")
        with Image.open(reference) as image:
            assert image.mode == "RGBA"
            red, _, blue, alpha = image.getpixel((16, 16))
            assert red > 200 and blue < 20 and alpha == 255
            assert image.getpixel((0, 0))[3] == (0 if transparent else 255)
        matting = choose_screen_color([reference])
        assert matting["method"] == ("chroma" if transparent else "ai")
        return {"name": "Mika", "tagging": payload["tagging"], "matting": matting}

    renderer = Mock(side_effect=render)
    monkeypatch.setattr(sprite_generation, "render_animation", renderer)
    monkeypatch.setattr(
        sprite_generation, "_finish_animation", lambda _, __, result: result
    )
    task = _create_task(app, kind="character-sprite-animate", title="regenerate")
    result = sprite_generation.run_sprite_animation(
        app,
        task["id"],
        {"name": "Mika", "referenceImage": source.as_posix(), "tagging": "微笑，挥手"},
    )
    assert result["tagging"] == "微笑，挥手"
    renderer.assert_called_once()
    assert source.read_bytes() == before


@pytest.mark.parametrize("frames", [5, 22])
def test_character_package_round_trip_preserves_transition_endpoints(
    tmp_path, monkeypatch, frames
):
    from config.character_config import CharacterConfig
    from tools import file_util

    def configure(root):
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(root)
        for key, suffix in [
            ("SPRITE_DIR", "data/sprite"),
            ("SPEECH_DIR", "data/speech"),
            ("MODEL_DIR", "data/models"),
            ("CONFIG_DIR", "data/config"),
        ]:
            path = root / suffix
            path.mkdir(parents=True, exist_ok=True)
            monkeypatch.setattr(file_util, key, path)
        config = root / "data/config/characters.yaml"
        config.write_text("[]")
        monkeypatch.setattr(file_util, "CHARACTERS_CONFIG_PATH", config)

    configure(tmp_path / "source")
    directory = file_util.SPRITE_DIR / "mika"
    directory.mkdir()
    first, last = directory / "first.png", directory / "last.png"
    for path, color in [(first, "red"), (last, "blue")]:
        Image.new("RGBA", (32, 32), color).save(path)
    (directory / "transitions").mkdir()
    clip = directory / "transitions/bridge.webm"
    alpha_clip(clip, frames)
    config = CharacterConfig.parse_dic(
        {
            "name": "Mika",
            "color": "#fff",
            "sprite_prefix": "mika",
            "sprites": [{"path": str(first)}, {"path": str(last)}],
            "sprite_transitions": [
                {
                    "from_path": str(first),
                    "to_path": str(last),
                    "path": str(clip),
                    "from_fingerprint": sprite_fingerprint(first),
                    "to_fingerprint": sprite_fingerprint(last),
                    **({"frame_count": frames} if frames != 5 else {}),
                }
            ],
        }
    )
    package = tmp_path / "character.char"
    file_util.export_character([config], str(package), open_folder=False)
    configure(tmp_path / "destination")
    restored = file_util.import_character(str(package))[0]
    edges = list(valid_transitions(restored))
    assert len(edges) == 1
    assert Path(edges[0]["path"]).is_relative_to(tmp_path / "destination")
    assert edges[0]["from_path"] == restored.sprites[0]["path"]
    assert edges[0]["to_path"] == restored.sprites[1]["path"]
    assert edges[0]["frame_count"] == frames
