import base64
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter


def test_comfy_autostart_uses_configured_port_and_arguments_without_a_window(
    tmp_path,
    monkeypatch,
):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://127.0.0.1:8189"
    portable = tmp_path / "H3 portable"
    for relative in ("python_embeded/python.exe", "ComfyUI/main.py"):
        target = portable / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    adapter.work_path = str(portable)
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


def test_comfy_manual_mode_never_launches_even_with_a_saved_directory(monkeypatch):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://127.0.0.1:8189"
    adapter.work_path = "C:/old portable"
    adapter.auto_start = False
    monkeypatch.setattr(adapter, "_is_server_ready", lambda: False)
    start = Mock()
    wait = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.subprocess.Popen", start)
    monkeypatch.setattr(adapter, "_wait_for_server_ready", wait)
    with pytest.raises(RuntimeError, match="自带启动器"):
        adapter._start_server_process()
    start.assert_not_called()
    wait.assert_not_called()


@pytest.mark.parametrize("auto_start", [False, True])
def test_comfy_reuses_running_server_without_a_portable_install(
    monkeypatch, auto_start
):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.work_path = ""
    adapter.auto_start = auto_start
    monkeypatch.setattr(adapter, "_is_server_ready", lambda: True)
    start = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.subprocess.Popen", start)
    adapter._start_server_process()
    start.assert_not_called()


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://127.0.0.1:8188", "便携版根目录"),
        ("http://192.0.2.1:8188", "仅支持本机"),
    ],
)
def test_comfy_autostart_explains_unsupported_installation(monkeypatch, url, message):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = url
    adapter.work_path = ""
    adapter.auto_start = True
    monkeypatch.setattr(adapter, "_is_server_ready", lambda: False)
    start = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.subprocess.Popen", start)
    with pytest.raises(ValueError, match=message):
        adapter._start_server_process()
    start.assert_not_called()


@pytest.mark.parametrize(
    ("status", "payload", "ready"),
    [
        (200, {"system": {"python_version": "3.10"}, "devices": []}, True),
        (200, {"message": "a different web application"}, False),
        (200, ["not ComfyUI"], False),
        (404, {"system": {}, "devices": []}, False),
        (401, {}, False),
    ],
)
def test_comfy_readiness_requires_system_stats(monkeypatch, status, payload, ready):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://localhost:8189/comfy"
    get = Mock(return_value=Mock(status_code=status, json=lambda: payload))
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.get", get)
    assert adapter._is_server_ready() is ready
    assert get.call_args.args[0] == "http://localhost:8189/comfy/system_stats"


def test_comfy_readiness_rejects_html_even_when_http_succeeds(monkeypatch):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://localhost:8188"
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("HTML page")
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.get", Mock(return_value=response))
    assert not adapter._is_server_ready()


@pytest.mark.parametrize(
    ("work_path", "explicit", "expected"),
    [
        ("", None, False),
        ("C:/portable", None, True),
        ("C:/portable", False, False),
        ("", True, True),
    ],
)
def test_comfy_startup_mode_preserves_legacy_portable_settings(
    tmp_path, monkeypatch, work_path, explicit, expected
):
    adapter = comfy(
        tmp_path,
        monkeypatch,
        {"1": {"inputs": {"text": ""}}},
        work_path=work_path,
        auto_start=explicit,
    )
    assert adapter.auto_start is expected


def test_comfy_api_workflow_accepts_bom_and_explains_canvas_export(tmp_path):
    path = tmp_path / "workflow.json"
    workflow = {"1": {"class_type": "TextNode", "inputs": {"text": ""}}}
    path.write_text(json.dumps(workflow), encoding="utf-8-sig")
    assert ComfyUIT2IAdapter._read_api_workflow(str(path)) == workflow
    path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="导出\\(API\\)"):
        ComfyUIT2IAdapter._read_api_workflow(str(path))


def test_comfy_validates_text_only_workflow_format_before_submission(
    tmp_path, monkeypatch
):
    path = tmp_path / "text-only.json"
    path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    adapter = comfy(
        tmp_path,
        monkeypatch,
        {"1": {"inputs": {"text": ""}}},
        text_only_workflow_path=str(path),
    )
    post = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    with pytest.raises(ValueError, match="画布工作流"):
        adapter.generate_image("test")
    post.assert_not_called()


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
