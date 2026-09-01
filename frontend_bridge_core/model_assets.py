"""Transport projections and task adapters for model-asset actions."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Callable, Iterator

from application.model_assets.download_model import ModelAssetRequest
from application.runtime.state import BridgeState
from application.runtime.tasks import _update_task


_MODEL_DOWNLOAD_ENQUEUE_LOCK = threading.Lock()


def parse_model_asset_request(payload: dict[str, Any]) -> ModelAssetRequest:
    configured = payload.get("configured", False)
    if not isinstance(configured, bool):
        raise ValueError("configured must be a boolean")
    variant: str | None = None
    if "variant" in payload:
        variant = str(payload.get("variant") or "")
    elif "modelName" in payload:
        variant = str(payload.get("modelName") or "")
    return ModelAssetRequest(
        asset_id=str(payload.get("assetId") or "").strip(),
        configured=configured,
        variant=variant,
    )


def configured_asr_model(state: BridgeState) -> str:
    system_config = getattr(
        getattr(getattr(state, "config_manager", None), "config", None),
        "system_config",
        None,
    )
    return (
        str(getattr(system_config, "asr_whisper_model_size", "") or "small").strip()
        or "small"
    )


def huggingface_token(state: BridgeState) -> str:
    api_config = getattr(
        getattr(getattr(state, "config_manager", None), "config", None),
        "api_config",
        None,
    )
    return str(getattr(api_config, "hugging_face_access_token", "") or "").strip()


def model_download_progress(
    state: BridgeState,
    task_id: str,
) -> Callable[..., None]:
    def update(**changes: Any) -> None:
        _update_task(state, task_id, **changes)

    return update


def find_running_model_download(
    state: BridgeState,
    task_key: str,
) -> dict[str, Any] | None:
    with state.task_lock:
        for task in state.tasks.values():
            if task.get("assetKey") != task_key:
                continue
            if str(task.get("status") or "") not in {"queued", "running"}:
                continue
            return dict(task)
    return None


@contextmanager
def model_download_enqueue_guard() -> Iterator[None]:
    """Serialize transport task creation so identical requests share a task."""

    with _MODEL_DOWNLOAD_ENQUEUE_LOCK:
        yield
