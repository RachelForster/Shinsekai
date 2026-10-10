from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter
from ai.t2i.t2i_manager import T2IManager
from sdk.adapters.t2i import T2IAdapter


@pytest.mark.parametrize("images", ["a.png", b"a.png", [""], [None], [1]])
def test_reference_array_rejects_malformed_values(images):
    with pytest.raises(ValueError, match="reference_images"):
        T2IAdapter.normalize_reference_images(images)


def test_manager_passes_ordered_references_and_retains_legacy_calls(tmp_path):
    adapter = Mock(spec=T2IAdapter)
    manager = T2IManager(adapter, image_cache_dir=str(tmp_path))
    try:
        manager.t2i("edit", reference_images=[Path("first.png"), "second.png"])
        assert adapter.generate_image.call_args.kwargs["reference_images"] == (
            "first.png",
            "second.png",
        )
        manager.t2i("generate", reference_images=[])
        assert "reference_images" not in adapter.generate_image.call_args.kwargs
    finally:
        manager.shutdown()
    adapter.shutdown.assert_called_once()


def test_queue_snapshots_reference_paths():
    import queue

    manager = T2IManager.__new__(T2IManager)
    manager.task_queue = queue.Queue()
    images = ["original.png"]
    manager.queue_generation("edit", reference_images=images)
    images.append("unexpected.png")
    assert manager.task_queue.get_nowait()["kwargs"]["reference_images"] == (
        "original.png",
    )


def test_sd_txt2img_rejects_references_before_network_call(monkeypatch):
    post = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    with pytest.raises(ValueError, match="does not support"):
        StableDiffusionAdapter().generate_image("edit", reference_images=["source.png"])
    post.assert_not_called()


def test_comfy_uploads_references_to_ordered_nodes_without_changing_template(
    tmp_path, monkeypatch
):
    import json

    workflow = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "original"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "8": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow))
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)
    monkeypatch.setattr(ComfyUIT2IAdapter, "_is_server_ready", lambda self: True)
    adapter = ComfyUIT2IAdapter(workflow_path=str(path), reference_image_node_ids="8,4")
    images = [tmp_path / "first.png", tmp_path / "second.png"]
    for image in images:
        image.write_bytes(b"reference")
    uploaded = []

    def post(url, **kwargs):
        response = Mock()
        if url.endswith("/upload/image"):
            name, stream = kwargs["files"]["image"]
            assert stream.read() == b"reference"
            uploaded.append(name)
            response.json.return_value = {"name": name, "subfolder": "references"}
        else:
            submitted = kwargs["json"]["prompt"]
            assert submitted["8"]["inputs"]["image"] == "references/first.png"
            assert submitted["4"]["inputs"]["image"] == "references/second.png"
            response.json.return_value = {"prompt_id": "id"}
        return response

    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    monkeypatch.setattr(adapter, "_wait_for_and_get_image", lambda *args: "output.png")
    assert adapter.generate_image("edit", reference_images=images) == "output.png"
    assert uploaded == ["first.png", "second.png"]
    assert adapter.workflow_template == workflow


def test_comfy_rejects_insufficient_image_nodes_before_upload(monkeypatch):
    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.reference_image_node_ids = ""
    post = Mock()
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    with pytest.raises(ValueError, match="one distinct"):
        adapter._inject_reference_images({}, ["a.png"])
    post.assert_not_called()
