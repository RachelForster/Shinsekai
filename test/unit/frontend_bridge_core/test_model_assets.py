from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_bridge_core import model_assets
from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.tasks import _create_task, _get_task, _update_task


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
        ("custom/model", "custom/model"),
    ],
)
def test_resolve_faster_whisper_asset_maps_model_names(variant, repo_id):
    spec = model_assets._resolve_model_asset(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": variant},
    )

    assert spec.source == "huggingface"
    assert spec.repo_id == repo_id
    assert spec.variant == variant


def test_resolve_faster_whisper_asset_uses_configured_default():
    spec = model_assets._resolve_model_asset(_state(model_name="medium"), {"assetId": "asr.faster-whisper"})

    assert spec.variant == "medium"
    assert spec.repo_id == "Systran/faster-whisper-medium"


def test_local_model_paths_are_never_downloadable(tmp_path):
    existing = tmp_path / "whisper"
    existing.mkdir()
    (existing / "config.json").write_text("{}", encoding="utf-8")
    (existing / "model.bin").write_bytes(b"model")
    (existing / "tokenizer.json").write_text("{}", encoding="utf-8")
    present = model_assets._model_asset_status(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": str(existing)},
    )
    missing_path = tmp_path / "missing"
    missing = model_assets._model_asset_status(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": str(missing_path)},
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

    status = model_assets._model_asset_status(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": str(empty)},
    )

    assert status["source"] == "local"
    assert status["cached"] is False
    assert status["downloadable"] is False

    (empty / "config.json").write_text("{}", encoding="utf-8")
    (empty / "model.bin").write_bytes(b"model")
    (empty / "vocabulary.json").write_text("{}", encoding="utf-8")
    vocabulary_only = model_assets._model_asset_status(
        _state(),
        {"assetId": "asr.faster-whisper", "variant": str(empty)},
    )
    assert vocabulary_only["cached"] is False


def test_download_model_asset_uses_configured_huggingface_token(monkeypatch):
    state = _state(token="hf-secret")
    task = _create_task(state, kind="model-download", title="Whisper")
    spec = model_assets._resolve_model_asset(
        state,
        {"assetId": "asr.faster-whisper", "variant": "small"},
    )
    calls = []

    def fake_download(received_spec, **kwargs):
        calls.append((received_spec, kwargs))
        kwargs["update_task"](phase="download", progress=0.5)
        return {"assetId": received_spec.asset_id, "cached": True}

    monkeypatch.setattr(model_assets, "download_model_asset", fake_download)

    result = model_assets._download_model_asset(state, str(task["id"]), spec)

    assert result == {"assetId": "asr.faster-whisper", "cached": True}
    assert calls[0][1]["token"] == "hf-secret"
    assert _get_task(state, str(task["id"]))["progress"] == 0.5


def test_running_model_asset_task_is_reused_by_task_key():
    state = _state()
    task = _create_task(state, kind="model-download", title="Whisper")
    _update_task(state, str(task["id"]), assetKey="asset-key", status="running")

    running = model_assets._find_running_model_asset_task(state, "asset-key")
    assert running is not None
    assert running["id"] == task["id"]

    _update_task(state, str(task["id"]), status="succeeded")
    assert model_assets._find_running_model_asset_task(state, "asset-key") is None


def test_unknown_model_asset_is_rejected():
    with pytest.raises(ValueError, match="Unsupported model asset"):
        model_assets._resolve_model_asset(_state(), {"assetId": "vision.moondream"})


def test_unknown_short_whisper_alias_is_rejected():
    with pytest.raises(ValueError, match="Unsupported faster-whisper model name"):
        model_assets._resolve_model_asset(
            _state(),
            {"assetId": "asr.faster-whisper", "variant": "unknown-model"},
        )
