import base64
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter


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


def test_comfy_reports_video_workflows_instead_of_polling_until_timeout(
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
                    "outputs": {"3": {"videos": [{}]}},
                    "status": {"completed": True},
                }
            }
        ),
    )
    with pytest.raises(ValueError, match="SaveImage"):
        adapter._wait_for_and_get_image("job", str(tmp_path / "output.png"))


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
