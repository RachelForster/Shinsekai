from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _default_project_root_dir() -> str:
    raw = (
        os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip()
        or os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
    )
    try:
        candidate = Path(raw).expanduser() if raw else Path.cwd()
        return str(candidate.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return raw or "."


@dataclass
class BridgeState:
    config_manager: Any
    character_manager: Any
    background_manager: Any
    template_generator: Any
    task_lock: threading.Lock = field(default_factory=threading.Lock)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    template_dir_path: str = "./data/character_templates"
    history_dir: str = "./data/chat_history"
    frontend_dist_dir: str = ""
    app_root_dir: str = ""
    auth_token: str = ""
    chat_session: dict[str, Any] = field(default_factory=dict)
    chat_stream: Any = None
    chat_runtime_lock: threading.Lock = field(default_factory=threading.Lock)
    chat_runtime_closing: bool = False
    history_download_lock: threading.Lock = field(default_factory=threading.Lock)
    history_download_capabilities: dict[str, tuple[str, float]] = field(default_factory=dict)
    chat_init_lock: threading.Lock = field(default_factory=threading.Lock)
    chat_init_task_id: str = ""
    plugin_load_lock: threading.Lock = field(default_factory=threading.Lock)
    plugin_load_status: str = "idle"
    plugin_load_error: str = ""
    plugin_load_started_at: float = 0.0
    plugin_load_completed_at: float = 0.0
    # Keep this field last so positional construction by older integrations remains compatible.
    project_root_dir: str = field(default_factory=_default_project_root_dir)


def _jsonify(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    return value


def set_plugin_load_status(
    state: BridgeState,
    status: str,
    *,
    error: str = "",
) -> None:
    now = time.time()
    with state.plugin_load_lock:
        state.plugin_load_status = status
        state.plugin_load_error = error
        if status == "loading":
            state.plugin_load_started_at = now
            state.plugin_load_completed_at = 0.0
        elif status in {"ready", "error"}:
            state.plugin_load_completed_at = now


def plugin_load_snapshot(state: BridgeState) -> dict[str, Any]:
    with state.plugin_load_lock:
        started_at = state.plugin_load_started_at
        completed_at = state.plugin_load_completed_at
        status = state.plugin_load_status
        error = state.plugin_load_error
    now = time.time()
    elapsed = 0.0
    if started_at > 0:
        end = completed_at if completed_at > 0 else now
        elapsed = max(0.0, end - started_at)
    return {
        "status": status,
        "error": error,
        "startedAt": started_at,
        "completedAt": completed_at,
        "elapsedSec": round(elapsed, 3),
    }
