from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.media.auto_annotation import (
    AnnotationCancelled,
    auto_label_background_images,
    auto_label_character_sprites,
)
from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.tasks import (
    TaskCancelled,
    _append_task_log,
    _is_task_cancel_requested,
    _update_task,
)


def _task_callbacks(
    state: BridgeState,
    task_id: str,
) -> tuple[Callable[[int, int, str, str], None], Callable[[], bool]]:
    def on_progress(completed: int, total: int, message: str, phase: str) -> None:
        _append_task_log(state, task_id, message)
        _update_task(
            state,
            task_id,
            completedItems=completed,
            message=message,
            phase=phase,
            progress=(completed / total) if total else 1,
            totalItems=total,
        )

    return on_progress, lambda: _is_task_cancel_requested(state, task_id)


def _run_annotation(
    state: BridgeState,
    task_id: str,
    name: str,
    service: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    on_progress, is_cancelled = _task_callbacks(state, task_id)
    try:
        return service(
            state.config_manager,
            name,
            project_root=Path(state.project_root_dir),
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
    except AnnotationCancelled as exc:
        raise TaskCancelled(str(exc)) from exc


def run_character_sprite_auto_label(state: BridgeState, task_id: str, name: str) -> dict[str, Any]:
    return _run_annotation(state, task_id, name, auto_label_character_sprites)


def run_background_image_auto_label(state: BridgeState, task_id: str, name: str) -> dict[str, Any]:
    return _run_annotation(state, task_id, name, auto_label_background_images)
