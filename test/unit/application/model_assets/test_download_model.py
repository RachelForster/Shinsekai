from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.model_assets import download_model as model_assets
from application.model_assets.download_model import ModelAssetRequest
from application.runtime.state import BridgeState
from application.runtime.tasks import _create_task, _get_task, _update_task
from frontend_bridge_core.model_assets import find_running_model_download


def _state(*, model_name: str = "small", token: str = "hf-token") -> BridgeState:
    config = SimpleNamespace(
        api_config=SimpleNamespace(hugging_face_access_token=token),
        system_config=SimpleNamespace(asr_whisper_model_size=model_name),
    )
    return BridgeState(
        config_manager=SimpleNamespace(config=config),
        character_manager=None,
        background_manager=None,
        template_generator=None,
        task_lock=threading.Lock(),
    )


def _request(payload: dict) -> ModelAssetRequest:
    variant = (
        payload.get("variant") if "variant" in payload else payload.get("modelName")
    )
    return ModelAssetRequest(
        asset_id=str(payload.get("assetId") or ""),
        configured=bool(payload.get("configured", False)),
        variant=None
        if "variant" not in payload and "modelName" not in payload
        else str(variant or ""),
    )


def _configured_model(state: BridgeState) -> str:
    return str(state.config_manager.config.system_config.asr_whisper_model_size)


def _resolve_model_asset(state: BridgeState, payload: dict):
    return model_assets.resolve_model_asset(
        _request(payload),
        configured_asr_model=_configured_model(state),
    )


def _model_asset_status(state: BridgeState, payload: dict):
    return model_assets.inspect_model(
        _request(payload),
        configured_asr_model=_configured_model(state),
    )


@pytest.mark.parametrize(
    ("variant", "repo_id"),
    [
        ("small", "Systran/faster-whisper-small"),
        ("distil-large-v2", "Systran/faster-distil-whisper-large-v2"),
        ("distil-large-v3", "Systran/faster-distil-whisper-large-v3"),
        ("distil-small.en", "Systran/faster-distil-whisper-small.en"),
        ("large", "Systran/faster-whisper-large-v3"),
        ("turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
        ("distil-large-v3.5", "distil-whisper/distil-large-v3.5-ct2"),
    ],
)
def test_resolve_faster_whisper_asset_maps_model_names(variant, repo_id):
    spec = _resolve_model_asset(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": variant},
    )

    assert spec.source == "huggingface"
    assert spec.repo_id == repo_id
    assert spec.variant == variant


def test_resolve_faster_whisper_asset_uses_configured_default():
    spec = _resolve_model_asset(
        _state(model_name="medium"),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert spec.variant == "medium"
    assert spec.repo_id == "Systran/faster-whisper-medium"


def test_resolve_memory_embedding_asset_uses_canonical_spec():
    from ai.memory.config import EMBEDDING_MODEL_ASSET

    spec = _resolve_model_asset(
        _state(),
        {"assetId": "memory.embedding"},
    )

    assert spec is EMBEDDING_MODEL_ASSET


@pytest.mark.parametrize(
    "extra",
    [
        {"configured": True},
        {"variant": "other/model"},
        {"modelName": "other/model"},
    ],
)
def test_memory_embedding_asset_rejects_client_selected_variants(extra):
    with pytest.raises(ValueError, match="do not accept a variant"):
        _resolve_model_asset(
            _state(),
            {"assetId": "memory.embedding", **extra},
        )


def test_resolve_configured_custom_huggingface_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = _resolve_model_asset(
        _state(model_name="custom/model"),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert spec.source == "huggingface"
    assert spec.variant == "custom/model"
    assert spec.repo_id == "custom/model"


@pytest.mark.parametrize("relative_path", ["whisper", "models/whisper"])
def test_existing_relative_configured_local_models_remain_supported(
    tmp_path, monkeypatch, relative_path
):
    monkeypatch.chdir(tmp_path)
    model_dir = tmp_path.joinpath(*relative_path.split("/"))
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.bin").write_bytes(b"model")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    status = _model_asset_status(
        _state(model_name=relative_path),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert status["source"] == "local"
    assert status["cached"] is True
    assert Path(str(status["path"])) == model_dir.resolve()


def test_configured_alias_stays_remote_when_same_named_directory_exists(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "small").mkdir()

    spec = _resolve_model_asset(
        _state(model_name="small"),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert spec.source == "huggingface"
    assert spec.repo_id == "Systran/faster-whisper-small"


def test_local_model_paths_are_never_downloadable(tmp_path):
    existing = tmp_path / "whisper"
    existing.mkdir()
    (existing / "config.json").write_text("{}", encoding="utf-8")
    (existing / "model.bin").write_bytes(b"model")
    (existing / "tokenizer.json").write_text("{}", encoding="utf-8")
    present = _model_asset_status(
        _state(model_name=str(existing)),
        {"assetId": "asr.faster-whisper", "configured": True},
    )
    missing_path = tmp_path / "missing"
    missing = _model_asset_status(
        _state(model_name=str(missing_path)),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert present["source"] == "local"
    assert present["cached"] is True
    assert present["downloadable"] is False
    assert Path(str(present["path"])) == existing.resolve()
    assert missing["source"] == "local"
    assert missing["cached"] is False
    assert missing["downloadable"] is False


def test_empty_local_model_directory_is_not_reported_ready(tmp_path):
    empty = tmp_path / "empty-whisper"
    empty.mkdir()

    status = _model_asset_status(
        _state(model_name=str(empty)),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert status["source"] == "local"
    assert status["cached"] is False
    assert status["downloadable"] is False

    (empty / "config.json").write_text("{}", encoding="utf-8")
    (empty / "model.bin").write_bytes(b"model")
    (empty / "vocabulary.json").write_text("{}", encoding="utf-8")
    vocabulary_only = _model_asset_status(
        _state(model_name=str(empty)),
        {"assetId": "asr.faster-whisper", "configured": True},
    )
    assert vocabulary_only["cached"] is False


def test_download_model_asset_uses_configured_huggingface_token(monkeypatch):
    state = _state(token="hf-secret")
    task = _create_task(state, kind="model-download", title="Whisper")
    spec = _resolve_model_asset(
        state,
        {"assetId": "asr.faster-whisper", "variant": "small"},
    )
    calls = []

    def fake_download(received_spec, **kwargs):
        calls.append((received_spec, kwargs))
        kwargs["update_task"](phase="download", progress=0.5)
        return {"assetId": received_spec.asset_id, "cached": True}

    monkeypatch.setattr(model_assets, "download_model_asset", fake_download)

    result = model_assets.download_model(
        spec,
        token="hf-secret",
        update_task=lambda **changes: _update_task(
            state,
            str(task["id"]),
            **changes,
        ),
    )

    assert result == {"assetId": "asr.faster-whisper", "cached": True}
    assert calls[0][1]["token"] == "hf-secret"
    assert _get_task(state, str(task["id"]))["progress"] == 0.5


def test_running_model_asset_task_is_reused_by_task_key():
    state = _state()
    task = _create_task(state, kind="model-download", title="Whisper")
    _update_task(state, str(task["id"]), assetKey="asset-key", status="running")

    running = find_running_model_download(state, "asset-key")
    assert running is not None
    assert running["id"] == task["id"]

    _update_task(state, str(task["id"]), status="succeeded")
    assert find_running_model_download(state, "asset-key") is None


def test_resolve_moondream_model_asset_uses_canonical_spec():
    from ai.vision.moondream_adapter import MOONDREAM_MODEL_ASSET

    spec = _resolve_model_asset(_state(), {"assetId": "vision.moondream"})

    assert spec is MOONDREAM_MODEL_ASSET


@pytest.mark.parametrize("extra", [{"configured": True}, {"variant": "other/model"}])
def test_moondream_model_asset_rejects_client_selected_variants(extra):
    with pytest.raises(ValueError, match="do not accept a variant"):
        _resolve_model_asset(
            _state(),
            {"assetId": "vision.moondream", **extra},
        )


def test_unknown_model_asset_is_rejected():
    with pytest.raises(ValueError, match="Unsupported model asset"):
        _resolve_model_asset(_state(), {"assetId": "vision.unknown"})


def test_unknown_short_whisper_alias_is_rejected():
    with pytest.raises(ValueError, match="Unsupported faster-whisper model name"):
        _resolve_model_asset(
            _state(),
            {"assetId": "asr.faster-whisper", "variant": "unknown-model"},
        )


@pytest.mark.parametrize(
    "variant",
    [
        "../secret",
        "/private/model",
        r"C:\Windows\System32",
        r"\\server\share\model",
        "owner/../../secret",
    ],
)
def test_request_local_paths_are_rejected_before_path_access(monkeypatch, variant):
    def unexpected_path_access(*_args, **_kwargs):
        raise AssertionError("request variant reached Path")

    monkeypatch.setattr(model_assets, "Path", unexpected_path_access)

    with pytest.raises(ValueError, match="must be saved"):
        _resolve_model_asset(
            _state(),
            {"assetId": "asr.faster-whisper", "variant": variant},
        )


@pytest.mark.parametrize(
    "model_name",
    [
        "../outside/model",
        "./model/../outside",
        "file:///tmp/model",
        "bad\x00model",
    ],
)
def test_universally_unsafe_configured_paths_are_rejected_before_path_access(
    monkeypatch, model_name
):
    def unexpected_path_access(*_args, **_kwargs):
        raise AssertionError("unsafe configured value reached Path")

    monkeypatch.setattr(model_assets, "Path", unexpected_path_access)

    with pytest.raises((PermissionError, ValueError)):
        _resolve_model_asset(
            _state(model_name=model_name),
            {"assetId": "asr.faster-whisper", "configured": True},
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows path namespace rules")
@pytest.mark.parametrize(
    "model_name",
    [
        r"\\server\share\model",
        "//server/share/model",
        r"\\?\C:\models\whisper",
        r"\\.\PhysicalDrive0",
        r"\??\C:\models\whisper",
        r"\models\whisper",
        "/models/whisper",
        r"C:relative\model",
        r"C:\models\whisper:stream",
        "./NUL",
        "NUL",
        r".\CON",
        r"C:\NUL",
        r"C:\models\CON.txt",
        r"C:\COM1 .txt",
        "C:\\COM\u00b9",
        r"C:\LPT9",
    ],
)
def test_unsafe_windows_configured_paths_are_rejected_before_path_access(
    monkeypatch, model_name
):
    def unexpected_path_access(*_args, **_kwargs):
        raise AssertionError("unsafe configured value reached Path")

    monkeypatch.setattr(model_assets, "Path", unexpected_path_access)

    with pytest.raises((PermissionError, ValueError)):
        _resolve_model_asset(
            _state(model_name=model_name),
            {"assetId": "asr.faster-whisper", "configured": True},
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits these path components")
def test_posix_specific_local_path_components_remain_supported(tmp_path):
    model_dir = tmp_path / "NUL" / "model:version " / "with\\backslash" / "trailing."
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.bin").write_bytes(b"model")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    status = _model_asset_status(
        _state(model_name=str(model_dir)),
        {"assetId": "asr.faster-whisper", "configured": True},
    )

    assert status["source"] == "local"
    assert status["cached"] is True
    assert Path(str(status["path"])) == model_dir.resolve()


def test_configured_requests_reject_variant_override():
    with pytest.raises(ValueError, match="must not include a variant"):
        _resolve_model_asset(
            _state(model_name="small"),
            {"assetId": "asr.faster-whisper", "configured": True, "variant": "small"},
        )


def test_custom_huggingface_repo_request_must_use_configured_selector(monkeypatch):
    def unexpected_path_access(*_args, **_kwargs):
        raise AssertionError("request variant reached Path")

    monkeypatch.setattr(model_assets, "Path", unexpected_path_access)

    with pytest.raises(ValueError, match="must be saved"):
        _resolve_model_asset(
            _state(),
            {"assetId": "asr.faster-whisper", "variant": "custom/model"},
        )


@pytest.mark.parametrize(
    "repo_id",
    [
        "owner/../../secret",
        "owner/model--bad",
        "owner/model..bad",
        "owner/-model",
    ],
)
def test_malformed_huggingface_repo_ids_are_rejected(repo_id):
    with pytest.raises(ValueError):
        _resolve_model_asset(
            _state(model_name=repo_id),
            {"assetId": "asr.faster-whisper", "configured": True},
        )


def test_resolve_perception_vlm_asset_defaults_and_enforces_configured_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    default_spec = model_assets.resolve_model_asset(
        _request({"assetId": "perception.vlm"}),
        configured_asr_model="small",
    )
    assert default_spec is model_assets.PERCEPTION_VLM_MODEL_ASSET

    with pytest.raises(ValueError, match="must be saved"):
        model_assets.resolve_model_asset(
            _request({"assetId": "perception.vlm", "variant": "Qwen/Qwen2.5-VL-3B-Instruct"}),
            configured_asr_model="small",
        )

    custom_spec = model_assets.resolve_model_asset(
        _request({"assetId": "perception.vlm", "configured": True}),
        configured_asr_model="small",
        configured_perception_model="Qwen/Qwen2.5-VL-3B-Instruct",
    )
    assert custom_spec.source == "huggingface"
    assert custom_spec.repo_id == "Qwen/Qwen2.5-VL-3B-Instruct"

    local_vlm = tmp_path / "local-qwen-vl"
    local_vlm.mkdir()
    (local_vlm / "config.json").write_text("{}", encoding="utf-8")
    (local_vlm / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (local_vlm / "tokenizer.json").write_text("{}", encoding="utf-8")
    (local_vlm / "model.safetensors").write_bytes(b"weights")

    local_status = model_assets.inspect_model(
        _request({"assetId": "perception.vlm", "configured": True}),
        configured_asr_model="small",
        configured_perception_model=str(local_vlm),
    )
    assert local_status["source"] == "local"
    assert local_status["cached"] is True
    assert local_status["downloadable"] is False


def test_direct_huggingface_repo_resolves_full_snapshot_by_default():
    spec = model_assets.resolve_model_asset(
        ModelAssetRequest(repo_id="BAAI/bge-m3"),
    )
    assert spec.asset_id == "huggingface.repo"
    assert spec.source == "huggingface"
    assert spec.repo_id == "BAAI/bge-m3"
    assert spec.variant == "BAAI/bge-m3"
    assert spec.title == "BAAI/bge-m3"
    assert spec.revision == ""
    assert spec.allow_patterns == ()
    assert spec.required_file_groups == ()

    pinned = model_assets.resolve_model_asset(
        ModelAssetRequest(
            asset_id="huggingface.repo",
            repo_id="Qwen/Qwen2.5-VL-3B-Instruct",
            revision="2025-01-09",
            title="Qwen 2.5 VL",
        ),
    )
    assert pinned.asset_id == "huggingface.repo"
    assert pinned.repo_id == "Qwen/Qwen2.5-VL-3B-Instruct"
    assert pinned.revision == "2025-01-09"
    assert pinned.variant == "Qwen/Qwen2.5-VL-3B-Instruct@2025-01-09"
    assert pinned.title == "Qwen 2.5 VL"


@pytest.mark.parametrize(
    ("bad_repo", "expected_pattern"),
    [
        ("", "repoId is required"),
        ("../secret", "local model paths are not allowed"),
        ("/private/model", "local model paths are not allowed"),
        (r"C:\Windows\System32", "local model paths are not allowed"),
        (r"\\server\share\model", "local model paths are not allowed"),
        ("owner/../../secret", "local model paths are not allowed"),
        ("small", "Invalid Hugging Face repository id"),
        ("owner/model--bad", "Invalid Hugging Face repository id"),
    ],
)
def test_direct_huggingface_repo_rejects_local_paths_and_malformed_ids_before_path_access(
    monkeypatch, bad_repo, expected_pattern
):
    def unexpected_path_access(*_args, **_kwargs):
        raise AssertionError("direct repoId reached Path")

    monkeypatch.setattr(model_assets, "Path", unexpected_path_access)

    with pytest.raises(ValueError, match=expected_pattern):
        model_assets.resolve_model_asset(ModelAssetRequest(repo_id=bad_repo))


def test_direct_repo_rejects_configured_flag_and_named_assets_reject_repo_id():
    with pytest.raises(ValueError, match="do not accept configured=True"):
        model_assets.resolve_model_asset(
            ModelAssetRequest(repo_id="BAAI/bge-m3", configured=True)
        )

    with pytest.raises(ValueError, match="do not accept repoId"):
        model_assets.resolve_model_asset(
            ModelAssetRequest(asset_id="asr.faster-whisper", repo_id="BAAI/bge-m3")
        )


def test_plugin_registered_model_assets_and_sdk_controller_reuse_host_token(monkeypatch):
    from plugin_system.host.service import bind_model_assets_runtime
    from sdk.model_assets import (
        download_huggingface_model,
        download_registered_model_asset,
    )
    from sdk.register import PluginCapabilityRegistry

    cap_reg = PluginCapabilityRegistry()
    active_plugin_model = {"value": "fast"}

    cap_reg.register_model_asset(
        asset_id="plugin.demo.embed",
        repo_id="BAAI/bge-small-en-v1.5",
        title="Demo Embedder",
        allow_patterns=("*.json", "*.safetensors"),
        required_file_groups=(("config.json",), ("model.safetensors",)),
        plugin_id="demo_plugin",
    )
    cap_reg.register_model_asset(
        asset_id="plugin.demo.reranker",
        title="Demo Reranker",
        aliases={
            "fast": "BAAI/bge-reranker-base",
            "large": "BAAI/bge-reranker-large",
        },
        configured_model_getter=lambda: active_plugin_model["value"],
        plugin_id="demo_plugin",
    )

    with pytest.raises(ValueError, match="reserved host model asset id"):
        cap_reg.register_model_asset(
            asset_id="asr.faster-whisper",
            repo_id="Systran/faster-whisper-small",
        )

    custom_registry = model_assets.ModelAssetRegistry()
    model_assets._register_builtin_definitions(custom_registry)
    custom_registry.configure_plugin_contributions(cap_reg.model_assets_contributions)

    embed_spec = model_assets.resolve_model_asset(
        ModelAssetRequest(asset_id="plugin.demo.embed"),
        registry=custom_registry,
    )
    assert embed_spec.repo_id == "BAAI/bge-small-en-v1.5"
    assert embed_spec.allow_patterns == ("*.json", "*.safetensors")

    with pytest.raises(ValueError, match="do not accept a variant"):
        model_assets.resolve_model_asset(
            ModelAssetRequest(asset_id="plugin.demo.embed", variant="other"),
            registry=custom_registry,
        )

    reranker_configured = model_assets.resolve_model_asset(
        ModelAssetRequest(asset_id="plugin.demo.reranker", configured=True),
        registry=custom_registry,
    )
    assert reranker_configured.repo_id == "BAAI/bge-reranker-base"

    active_plugin_model["value"] = "BAAI/bge-reranker-v2-m3"
    reranker_custom = model_assets.resolve_model_asset(
        ModelAssetRequest(asset_id="plugin.demo.reranker", configured=True),
        registry=custom_registry,
    )
    assert reranker_custom.repo_id == "BAAI/bge-reranker-v2-m3"

    seen_downloads: list[tuple[object, str]] = []
    progress_events: list[dict[str, object]] = []

    def fake_download(spec, *, update_task, token=""):
        seen_downloads.append((spec, token))
        update_task(phase="download", progress=0.75)
        return {
            "assetId": spec.asset_id,
            "repoId": spec.repo_id,
            "cached": True,
            "downloaded": True,
        }

    monkeypatch.setattr(model_assets, "download_model_asset", fake_download)
    dispatcher = model_assets.create_plugin_model_assets_dispatcher(
        get_token=lambda: "hf-host-secret-token",
        get_configured_values=lambda: {"asr.faster-whisper": "small"},
        registry=custom_registry,
    )
    bind_model_assets_runtime(dispatcher)
    try:
        controller = cap_reg.model_assets("demo_plugin")
        direct_result = controller.download(
            "BAAI/bge-m3",
            revision="v1.0",
            allow_patterns=("config.json", "model.safetensors"),
            on_progress=lambda **kw: progress_events.append(kw),
        )
        registered_result = download_registered_model_asset("plugin.demo.embed")
        helper_result = download_huggingface_model("Qwen/Qwen2.5-0.5B")
    finally:
        bind_model_assets_runtime(None)

    assert "hf-host-secret-token" not in str(direct_result)
    assert direct_result["repoId"] == "BAAI/bge-m3"
    assert registered_result["assetId"] == "plugin.demo.embed"
    assert helper_result["repoId"] == "Qwen/Qwen2.5-0.5B"
    assert progress_events == [{"phase": "download", "progress": 0.75}]
    assert [token for _spec, token in seen_downloads] == [
        "hf-host-secret-token",
        "hf-host-secret-token",
        "hf-host-secret-token",
    ]
    assert seen_downloads[0][0].allow_patterns == ("config.json", "model.safetensors")
    assert seen_downloads[0][0].revision == "v1.0"
    assert seen_downloads[2][0].allow_patterns == ()


def test_fixed_model_assets_reject_explicit_revision_and_custom_patterns(tmp_path):
    from sdk.register import PluginCapabilityRegistry

    for fixed_asset_id in ("memory.embedding", "vision.moondream"):
        with pytest.raises(ValueError, match="do not accept a revision"):
            model_assets.resolve_model_asset(
                ModelAssetRequest(asset_id=fixed_asset_id, revision="v1.0")
            )
        with pytest.raises(ValueError, match="do not accept a revision"):
            model_assets.inspect_model(
                ModelAssetRequest(asset_id=fixed_asset_id, revision="v1.0")
            )
        with pytest.raises(ValueError, match="do not accept custom file patterns"):
            model_assets.resolve_model_asset(
                ModelAssetRequest(asset_id=fixed_asset_id, allow_patterns=("config.json",))
            )

    cap_reg = PluginCapabilityRegistry()
    cap_reg.register_model_asset(
        asset_id="plugin.demo.fixed",
        repo_id="BAAI/bge-small-en-v1.5",
        revision="v2.0",
        plugin_id="demo_plugin",
    )
    custom_registry = model_assets.ModelAssetRegistry()
    model_assets._register_builtin_definitions(custom_registry)
    custom_registry.configure_plugin_contributions(cap_reg.model_assets_contributions)

    default_plugin_spec = model_assets.resolve_model_asset(
        ModelAssetRequest(asset_id="plugin.demo.fixed"),
        registry=custom_registry,
    )
    assert default_plugin_spec.revision == "v2.0"

    with pytest.raises(ValueError, match="do not accept a revision"):
        model_assets.resolve_model_asset(
            ModelAssetRequest(asset_id="plugin.demo.fixed", revision="v1.0"),
            registry=custom_registry,
        )

    local_dir = tmp_path / "local-whisper"
    local_dir.mkdir()
    with pytest.raises(ValueError, match="revision is not supported for local model assets"):
        model_assets.resolve_model_asset(
            ModelAssetRequest(
                asset_id="asr.faster-whisper",
                configured=True,
                revision="v1.0",
            ),
            configured_asr_model=str(local_dir),
        )


def test_direct_model_download_checks_requested_scope_against_partial_cache(
    tmp_path, monkeypatch
):
    from core.model_assets import service

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    model_dir = tmp_path / "models--owner--demo"
    snapshot = model_dir / "snapshots" / "sha1"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "refs").mkdir(parents=True)
    (model_dir / "refs" / "main").write_text("sha1", encoding="utf-8")

    monkeypatch.setattr(
        service,
        "_fetch_huggingface_revision_files",
        lambda *_args, **_kwargs: (("config.json", None), ("weights.bin", None)),
    )

    weights_only_req = ModelAssetRequest(
        repo_id="owner/demo",
        allow_patterns=("weights.bin",),
    )
    full_repo_req = ModelAssetRequest(repo_id="owner/demo")

    assert model_assets.inspect_model(weights_only_req)["cached"] is False
    assert model_assets.inspect_model(full_repo_req)["cached"] is False

    preload_calls: list[tuple[str, dict[str, object]]] = []

    def fake_preload(repo_id, **kwargs):
        preload_calls.append((repo_id, kwargs))
        (snapshot / "weights.bin").write_bytes(b"weights-data")
        return str(snapshot)

    monkeypatch.setattr(service, "preload_huggingface_snapshot", fake_preload)

    weights_spec = model_assets.resolve_model_asset(weights_only_req)
    downloaded = model_assets.download_model(
        weights_spec,
        update_task=lambda **_changes: None,
    )
    assert downloaded["cached"] is True
    assert downloaded["downloaded"] is True
    assert len(preload_calls) == 1
    assert preload_calls[0][1]["allow_patterns"] == ["weights.bin"]
    assert model_assets.inspect_model(full_repo_req)["cached"] is True

    # Reset back to config.json only and verify simultaneous allow_patterns + required_file_groups.
    (snapshot / "weights.bin").unlink()
    combined_req = ModelAssetRequest(
        repo_id="owner/demo",
        allow_patterns=("config.json", "weights.bin"),
        required_file_groups=(("config.json",),),
    )
    assert model_assets.inspect_model(combined_req)["cached"] is False

    combined_spec = model_assets.resolve_model_asset(combined_req)
    combined_downloaded = model_assets.download_model(
        combined_spec,
        update_task=lambda **_changes: None,
    )
    assert combined_downloaded["cached"] is True
    assert combined_downloaded["downloaded"] is True
    assert len(preload_calls) == 2
    assert preload_calls[1][1]["allow_patterns"] == ["config.json", "weights.bin"]


