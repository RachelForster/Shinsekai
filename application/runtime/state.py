"""Mutable application state shared by transport adapters and use cases."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from application.chat.mobile_access import MobileAccessPort


def _default_project_root_dir() -> str:
    # Presence, not a trimmed interpretation, determines precedence.  An
    # explicitly configured but invalid current root must fail closed instead
    # of silently reviving a different legacy project.
    if "SHINSEKAI_PROJECT_ROOT" in os.environ:
        raw: str | None = os.environ["SHINSEKAI_PROJECT_ROOT"]
    elif "EASYAI_PROJECT_ROOT" in os.environ:
        raw = os.environ["EASYAI_PROJECT_ROOT"]
    else:
        raw = None
    try:
        if raw is not None:
            if raw != raw.strip() or any(
                ord(character) < 32
                or ord(character) == 127
                or 0xD800 <= ord(character) <= 0xDFFF
                for character in raw
            ):
                raise ValueError("configured project root contains non-portable characters")
            from core.paths import resolve_project_path

            candidate = resolve_project_path(".", root=raw)
        else:
            from core.paths import project_root

            candidate = project_root()
        return str(candidate)
    except (OSError, RuntimeError, ValueError) as exc:
        if raw is not None:
            raise ValueError("configured project root is invalid") from exc
        raise RuntimeError("stable project root is unavailable") from exc


@dataclass
class BridgeState:
    config_manager: Any
    character_manager: Any
    background_manager: Any
    template_generator: Any
    task_lock: threading.Lock = field(default_factory=threading.Lock)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    template_dir_path: str = "data/character_templates"
    history_dir: str = "data/chat_history"
    frontend_dist_dir: str = ""
    app_root_dir: str = ""
    auth_token: str = ""
    chat_session: dict[str, Any] = field(default_factory=dict)
    chat_stream: Any = None
    mobile_access_service: MobileAccessPort | None = None
    chat_runtime_lock: threading.Lock = field(default_factory=threading.Lock)
    chat_runtime_closing: bool = False
    history_download_lock: threading.Lock = field(default_factory=threading.Lock)
    history_download_capabilities: dict[str, tuple[str, float]] = field(default_factory=dict)
    chat_init_lock: threading.Lock = field(default_factory=threading.Lock)
    chat_init_task_id: str = ""
    chat_transition_lock: threading.RLock = field(default_factory=threading.RLock)
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
