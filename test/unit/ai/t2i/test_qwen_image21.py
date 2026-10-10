import json
import sys
from pathlib import Path

import pytest

from ai.t2i import qwen_image21_adapter, qwen_image21_worker
from ai.t2i.qwen_image21_adapter import QwenImage21Adapter
from ai.t2i.qwen_image21_assets import QWEN_IMAGE21_MODEL_ASSET, complete_qwen_snapshot
from application.model_assets.download_model import (
    ModelAssetRequest,
    resolve_model_asset,
)


@pytest.fixture
def model(tmp_path):
    model = tmp_path / "model"
    for component, filename in (
        ("text_encoder", "model.safetensors.index.json"),
        ("transformer", "diffusion_pytorch_model.safetensors.index.json"),
    ):
        folder = model / component
        folder.mkdir(parents=True)
        (folder / filename).write_text(
            json.dumps(
                {
                    "weight_map": {
                        "one": "part-1.safetensors",
                        "two": "part-2.safetensors",
                    }
                }
            )
        )
        for shard in ("part-1.safetensors", "part-2.safetensors"):
            (folder / shard).write_bytes(b"weights")
    for filename in (
        "model_index.json",
        "processor/tokenizer.json",
        "processor/preprocessor_config.json",
        "text_encoder/config.json",
        "transformer/config.json",
        "scheduler/scheduler_config.json",
        "vae/config.json",
        "vae/diffusion_pytorch_model.safetensors",
    ):
        file = model / filename
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"{}")
    return model


def test_download_asset_validates_all_shards(model):
    assert (
        resolve_model_asset(ModelAssetRequest("t2i.qwen-image-2.1"))
        is QWEN_IMAGE21_MODEL_ASSET
    )
    assert complete_qwen_snapshot(model)
    (model / "text_encoder/part-2.safetensors").unlink()
    assert not complete_qwen_snapshot(model)


@pytest.mark.parametrize(
    "asset_request",
    [
        ModelAssetRequest("t2i.qwen-image-2.1", configured=True),
        ModelAssetRequest("t2i.qwen-image-2.1", variant="other/model"),
    ],
)
def test_download_cannot_select_other_models(asset_request):
    with pytest.raises(ValueError, match="do not accept a variant"):
        resolve_model_asset(asset_request)


def test_incomplete_index_cannot_claim_cached_model(model):
    (model / "text_encoder/model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"one": "../../unexpected"}})
    )
    assert not complete_qwen_snapshot(model)


def test_real_subprocess_protocol_passes_reference_order_and_progress(
    model, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        qwen_image21_worker,
        "WORKER_SOURCE",
        """
import json, sys
from pathlib import Path
request = json.load(sys.stdin)
Path(request["output"]).write_bytes(b"generated")
Path(request["output"]).with_suffix(".json").write_text(json.dumps(request))
print(json.dumps({"type": "progress", "progress": 0.5, "message": "Generating"}), flush=True)
print(json.dumps({"type": "result", "path": request["output"]}), flush=True)
""",
    )
    references = [tmp_path / "first 中文.png", tmp_path / "second.png"]
    for file in references:
        file.write_bytes(b"reference")
    adapter = QwenImage21Adapter(
        python_executable=sys.executable, model_path=str(model)
    )
    updates = []
    output = tmp_path / "output.png"
    result = adapter.generate_image(
        "change pose",
        str(output),
        reference_images=references,
        transparent=True,
        reference_canvas_index=0,
        width=512,
        height=1024,
        on_progress=lambda *args: updates.append(args),
    )
    request = json.loads(output.with_suffix(".json").read_text())
    assert Path(result) == output
    assert request["reference_images"] == [str(file.resolve()) for file in references]
    assert request["transparent"] is True
    assert request["reference_canvas_index"] == 0
    assert request["width"] == 512 and request["height"] == 1024
    assert updates == [(0.5, "Generating")]
    assert adapter._process is None
    assert all(file.read_bytes() == b"reference" for file in references)


@pytest.mark.parametrize("index", [-1, 1, True, "0"])
def test_invalid_canvas_reference_does_not_start_worker(
    model, tmp_path, monkeypatch, index
):
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    adapter = QwenImage21Adapter(
        python_executable=sys.executable, model_path=str(model)
    )
    start = []
    monkeypatch.setattr(
        qwen_image21_adapter.subprocess,
        "Popen",
        lambda *args, **kwargs: start.append(args),
    )
    with pytest.raises(ValueError, match="reference_canvas_index"):
        adapter.generate_image(
            "edit",
            str(tmp_path / "result.png"),
            reference_images=[image],
            reference_canvas_index=index,
        )
    assert not start


def test_worker_errors_do_not_overwrite_existing_output(model, tmp_path, monkeypatch):
    monkeypatch.setattr(
        qwen_image21_worker,
        "WORKER_SOURCE",
        'import sys; print(\'{"type":"error","message":"CUDA out of memory"}\'); sys.exit(1)',
    )
    output = tmp_path / "output.png"
    output.write_bytes(b"original")
    adapter = QwenImage21Adapter(
        python_executable=sys.executable, model_path=str(model)
    )
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        adapter.generate_image("generate", str(output))
    assert output.read_bytes() == b"original"
    assert adapter._process is None


def test_worker_timeout_terminates_child(model, tmp_path, monkeypatch):
    monkeypatch.setattr(
        qwen_image21_worker, "WORKER_SOURCE", "import time; time.sleep(60)"
    )
    adapter = QwenImage21Adapter(
        python_executable=sys.executable, model_path=str(model), timeout_seconds=1
    )
    with pytest.raises(TimeoutError, match="exceeded"):
        adapter.generate_image("generate", str(tmp_path / "out.png"))
    assert adapter._process is None


def test_shutdown_terminates_active_worker(model, tmp_path, monkeypatch):
    monkeypatch.setattr(
        qwen_image21_worker,
        "WORKER_SOURCE",
        'import time; print(\'{"type":"progress","progress":0,"message":"Ready"}\', flush=True); time.sleep(60)',
    )
    adapter = QwenImage21Adapter(
        python_executable=sys.executable, model_path=str(model)
    )
    with pytest.raises(RuntimeError, match="Qwen generation failed"):
        adapter.generate_image(
            "generate",
            str(tmp_path / "out.png"),
            on_progress=lambda *_: adapter.shutdown(),
        )
    assert adapter._process is None


def test_invalid_reference_paths_rejected_without_starting_worker(
    model, tmp_path, monkeypatch
):
    start = []
    monkeypatch.setattr(
        qwen_image21_adapter.subprocess,
        "Popen",
        lambda *args, **kwargs: start.append(args),
    )
    adapter = QwenImage21Adapter(model_path=str(model))
    with pytest.raises(ValueError, match="existing local files"):
        adapter.generate_image("edit", reference_images=[tmp_path / "missing.png"])
    image = tmp_path / "source.png"
    image.write_bytes(b"original")
    with pytest.raises(ValueError, match="Output must differ"):
        adapter.generate_image("edit", str(image), reference_images=[image])
    with pytest.raises(ValueError, match="at most 10"):
        adapter.generate_image("edit", reference_images=[image] * 11)
    assert start == []


def test_model_loading_is_lazy_and_missing_model_has_actionable_error(tmp_path):
    adapter = QwenImage21Adapter(model_path=str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="Download it in AI services"):
        adapter.generate_image("generate")
    adapter.shutdown()


def test_worker_source_compiles_without_importing_ml_libraries():
    compile(qwen_image21_worker.WORKER_SOURCE, "qwen-worker", "exec")


def test_shutdown_interrupts_waiting_for_another_generation(model, tmp_path):
    owner = QwenImage21Adapter(model_path=str(model))
    waiter = QwenImage21Adapter(model_path=str(model))
    with owner._generation_slot(None):
        with pytest.raises(RuntimeError, match="shut down"):
            waiter.generate_image(
                "generate",
                str(tmp_path / "output.png"),
                on_progress=lambda *_: waiter.shutdown(),
            )
    assert waiter._process is None


def test_factory_registers_lazy_qwen_and_filters_http_configuration(tmp_path):
    from ai.t2i.t2i_manager import T2IAdapterFactory

    adapter = T2IAdapterFactory.create_adapter(
        "QWEN-IMAGE-2.1",
        api_url="unused",
        workflow_path="unused",
        model_path=str(tmp_path),
    )
    assert isinstance(adapter, QwenImage21Adapter)
    assert adapter.model_path == str(tmp_path)
    assert adapter._process is None
