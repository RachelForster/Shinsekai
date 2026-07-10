from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.model_assets.service import ModelAssetSpec, download_model_asset, inspect_model_asset

from .state import BridgeState
from .tasks import _update_task

_ASR_FASTER_WHISPER_ASSET_ID = "asr.faster-whisper"
_ASR_ALLOW_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
_ASR_REQUIRED_FILE_GROUPS = (
    ("config.json",),
    ("model.bin",),
    ("tokenizer.json",),
)
_ASR_MODEL_REPOS = {
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "tiny": "Systran/faster-whisper-tiny",
    "base.en": "Systran/faster-whisper-base.en",
    "base": "Systran/faster-whisper-base",
    "small.en": "Systran/faster-whisper-small.en",
    "small": "Systran/faster-whisper-small",
    "medium.en": "Systran/faster-whisper-medium.en",
    "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_MODEL_ASSET_ENQUEUE_LOCK = threading.Lock()


def _looks_like_local_model(value: str) -> tuple[bool, Path]:
    raw = str(value or "").strip()
    path = Path(raw).expanduser()
    resolved = path.resolve(strict=False)
    if path.exists():
        return True, resolved
    looks_local = bool(
        not raw
        or raw.startswith((".", "/", "\\", "~"))
        or raw.endswith(("/", "\\"))
        or "\\" in raw
        or ":" in raw
        or raw.count("/") > 1
        or re.match(r"^[A-Za-z]:", raw)
    )
    return looks_local, resolved


def _faster_whisper_repo_id(model_name: str) -> str:
    model = str(model_name or "small").strip() or "small"
    if model in _ASR_MODEL_REPOS:
        return _ASR_MODEL_REPOS[model]
    if "/" in model:
        return model
    raise ValueError(
        f"Unsupported faster-whisper model name: {model}. "
        "Use a supported model alias, a full Hugging Face repository id, or a local model directory."
    )


def _configured_asr_model(state: BridgeState) -> str:
    config_manager = getattr(state, "config_manager", None)
    config = getattr(config_manager, "config", None)
    system_config = getattr(config, "system_config", None)
    return str(getattr(system_config, "asr_whisper_model_size", "") or "small").strip() or "small"


def _resolve_model_asset(state: BridgeState, payload: dict[str, Any]) -> ModelAssetSpec:
    asset_id = str(payload.get("assetId") or "").strip()
    if asset_id != _ASR_FASTER_WHISPER_ASSET_ID:
        raise ValueError(f"Unsupported model asset: {asset_id or '<empty>'}")

    variant = str(payload.get("variant") or payload.get("modelName") or _configured_asr_model(state)).strip() or "small"
    is_local, local_path = _looks_like_local_model(variant)
    title = f"faster-whisper {variant}"
    if is_local:
        return ModelAssetSpec(
            asset_id=asset_id,
            title=title,
            variant=variant,
            source="local",
            local_path=local_path,
            required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
        )
    return ModelAssetSpec(
        asset_id=asset_id,
        title=title,
        variant=variant,
        repo_id=_faster_whisper_repo_id(variant),
        allow_patterns=_ASR_ALLOW_PATTERNS,
        required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
    )


def _model_asset_status(state: BridgeState, payload: dict[str, Any]) -> dict[str, object]:
    return inspect_model_asset(_resolve_model_asset(state, payload))


def _huggingface_token(state: BridgeState) -> str:
    config_manager = getattr(state, "config_manager", None)
    config = getattr(config_manager, "config", None)
    api_config = getattr(config, "api_config", None)
    return str(getattr(api_config, "hugging_face_access_token", "") or "").strip()


def _download_model_asset(state: BridgeState, task_id: str, spec: ModelAssetSpec) -> dict[str, object]:
    def update_task(**changes: Any) -> None:
        _update_task(state, task_id, **changes)

    return download_model_asset(
        spec,
        update_task=update_task,
        token=_huggingface_token(state),
    )


def _find_running_model_asset_task(state: BridgeState, task_key: str) -> dict[str, Any] | None:
    with state.task_lock:
        for task in state.tasks.values():
            if task.get("assetKey") != task_key:
                continue
            if str(task.get("status") or "") not in {"queued", "running"}:
                continue
            return dict(task)
    return None


@contextmanager
def _model_asset_enqueue_guard() -> Iterator[None]:
    """Serialize check-and-enqueue so identical HTTP requests share a task."""

    with _MODEL_ASSET_ENQUEUE_LOCK:
        yield


__all__ = [
    "_download_model_asset",
    "_find_running_model_asset_task",
    "_model_asset_enqueue_guard",
    "_model_asset_status",
    "_resolve_model_asset",
]
