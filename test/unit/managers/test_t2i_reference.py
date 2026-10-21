import base64
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter


def test_comfy_autostart_uses_configured_port_and_arguments_without_a_window(
    monkeypatch,
):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://127.0.0.1:8189"
    adapter.work_path = "C:/H3 portable"
    adapter.startup_args = (
        "--windows-standalone-build --reserve-vram 1.5 --disable-all-custom-nodes"
    )
    monkeypatch.setattr(adapter, "_is_server_ready", lambda: False)
    monkeypatch.setattr(adapter, "_wait_for_server_ready", lambda: True)
    start = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.subprocess.Popen", start)
    adapter._start_server_process()
    command = start.call_args.args[0]
    assert command[command.index("--port") + 1] == "8189"
    assert "--reserve-vram" in command
    assert start.call_args.kwargs["cwd"] == adapter.work_path
    assert start.call_args.kwargs["creationflags"] == (
        subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )


def comfy(tmp_path, monkeypatch, workflow, **kwargs):
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda _: None)
    adapter = ComfyUIT2IAdapter(
        workflow_path=str(path), prompt_node_id="1", output_node_id="3", **kwargs
    )
    monkeypatch.setattr(adapter, "_wait_for_server_ready", lambda: True)
    monkeypatch.setattr(adapter, "_wait_for_and_get_image", lambda *_: "done.png")
    return adapter


@pytest.mark.parametrize("field", ["text", "prompt"])
def test_comfy_uploads_reference_and_injects_actual_prompt_field(
    tmp_path, monkeypatch, field
):
    workflow = {
        "1": {"class_type": "TextNode", "inputs": {field: "old", "seed": 1}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    }
    adapter = comfy(tmp_path, monkeypatch, workflow)
    post = Mock(
        side_effect=[
            Mock(json=lambda: {"name": "uploaded.png", "subfolder": "refs"}),
            Mock(json=lambda: {"prompt_id": "job"}),
        ]
    )
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"reference bytes")
    assert (
        adapter.generate_image(
            "new prompt", reference_image_path=str(reference), seed=42
        )
        == "done.png"
    )
    sent = post.call_args.kwargs["json"]["prompt"]
    assert sent["1"]["inputs"] == {field: "new prompt", "seed": 42}
    assert sent["2"]["inputs"]["image"] == "refs/uploaded.png"
    assert adapter.workflow_template == workflow
    assert post.call_args_list[0].args[0].endswith("/upload/image")


def test_comfy_requires_explicit_node_for_ambiguous_reference(tmp_path, monkeypatch):
    workflow = {
        "1": {"class_type": "Text", "inputs": {"text": ""}},
        "2": {"class_type": "LoadImage", "inputs": {}},
        "4": {"class_type": "LoadImage", "inputs": {}},
    }
    adapter = comfy(tmp_path, monkeypatch, workflow)
    with pytest.raises(ValueError, match="reference_node_id"):
        adapter.generate_image("pose", reference_image_path="ignored.png")


def test_comfy_reports_missing_media_instead_of_polling_until_timeout(
    tmp_path, monkeypatch
):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url, adapter.output_node_id, adapter.generation_timeout = (
        "http://local",
        "3",
        600,
    )
    monkeypatch.setattr("ai.t2i.t2i_adapter.time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "ai.t2i.t2i_adapter.requests.get",
        lambda *_args, **_kwargs: Mock(
            json=lambda: {
                "job": {
                    "outputs": {"3": {}},
                    "status": {"completed": True},
                }
            }
        ),
    )
    with pytest.raises(ValueError, match="SaveImage"):
        adapter._wait_for_and_get_image("job", str(tmp_path / "output.png"))


@pytest.mark.parametrize("key", ["images", "videos", "gifs"])
def test_comfy_downloads_video_and_extracts_a_still(tmp_path, monkeypatch, key):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url, adapter.output_node_id, adapter.generation_timeout = (
        "http://local",
        "3",
        600,
    )
    monkeypatch.setattr("ai.t2i.t2i_adapter.time.sleep", lambda *_: None)
    get = Mock(
        side_effect=[
            Mock(
                json=lambda: {
                    "job": {
                        "outputs": {
                            "3": {
                                key: [
                                    {
                                        "filename": "H3 clip.mp4",
                                        "subfolder": "video",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                        "status": {"completed": True},
                    }
                }
            ),
            Mock(content=b"video bytes"),
        ]
    )
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.get", get)

    def capture(video, output):
        assert video.read_bytes() == b"video bytes"
        output.write_bytes(b"png bytes")
        return 1.5

    monkeypatch.setattr("core.media.video_frames.extract_video_frame", capture)
    output = tmp_path / "sprite.png"
    assert adapter._wait_for_and_get_image("job", str(output)) == str(output.resolve())
    assert output.read_bytes() == b"png bytes"
    assert adapter.last_video_path == str(output.with_suffix(".mp4").resolve())
    assert adapter.last_video_frame_time == 1.5
    assert "filename=H3+clip.mp4" in get.call_args.args[0]


def test_comfy_selects_text_only_workflow_when_reference_is_absent(
    tmp_path, monkeypatch
):
    template = {
        "1": {"class_type": "Text", "inputs": {"text": ""}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "required.png"}},
    }
    text_only = tmp_path / "text-only.json"
    text_only.write_text(json.dumps({"1": template["1"]}), encoding="utf-8")
    adapter = comfy(
        tmp_path, monkeypatch, template, text_only_workflow_path=str(text_only)
    )
    post = Mock(return_value=Mock(json=lambda: {"prompt_id": "job"}))
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    adapter.generate_image("new pose")
    assert "2" not in post.call_args.kwargs["json"]["prompt"]
    assert "2" in adapter.workflow_template


def test_sd_reference_uses_img2img_and_same_output_contract(tmp_path, monkeypatch):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"input")
    post = Mock(
        return_value=Mock(
            json=lambda: {"images": [base64.b64encode(b"output").decode()]}
        )
    )
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    output = tmp_path / "output.png"
    result = StableDiffusionAdapter().generate_image(
        "pose", file_path=str(output), reference_image_path=str(reference)
    )
    assert result == str(output.resolve())
    assert output.read_bytes() == b"output"
    assert post.call_args.args[0].endswith("/img2img")
    assert post.call_args.kwargs["json"]["init_images"] == [
        base64.b64encode(b"input").decode()
    ]
