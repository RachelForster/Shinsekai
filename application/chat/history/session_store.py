"""上次启动聊天时的选项快照（人物、背景、模板正文等），持久化至 ``data/state/ui_state.json``。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from config.models.ui_state import UiRuntimeState
from sdk.file_io import durable_mkdir, durable_rename

_SESSION_VERSION = 1


def ui_state_file(template_dir_path: str) -> Path:
    """Resolve ``data/state/ui_state.json`` relative to ``data/character_templates``."""
    data_root = Path(template_dir_path).resolve(strict=False).parent
    return data_root / "state" / "ui_state.json"


def legacy_template_session_file(template_dir_path: str) -> Path:
    """Legacy pre-migration location: ``data/config/template_tab_last_launch.json``."""
    data_root = Path(template_dir_path).resolve(strict=False).parent
    return data_root / "config" / "template_tab_last_launch.json"


def template_session_file(template_dir_path: str) -> Path:
    """Return the active persistent path holding template-tab launch state."""
    return ui_state_file(template_dir_path)


def _read_ui_state(path: Path) -> UiRuntimeState:
    if not path.is_file():
        return UiRuntimeState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UiRuntimeState()
    if not isinstance(raw, dict):
        return UiRuntimeState()
    try:
        return UiRuntimeState.model_validate(raw)
    except Exception:
        return UiRuntimeState()


def _write_ui_state(path: Path, state: UiRuntimeState) -> None:
    durable_mkdir(path.parent)
    serialized = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        durable_rename(temporary_path, path, replace=True)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _valid_session_dict(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != _SESSION_VERSION:
        return None
    return dict(raw)


def load_template_session(template_dir_path: str) -> dict[str, Any] | None:
    ui_state = _read_ui_state(ui_state_file(template_dir_path))
    current = _valid_session_dict(ui_state.template_last_launch)
    if current is not None:
        return current
    legacy_path = legacy_template_session_file(template_dir_path)
    if not legacy_path.is_file():
        return None
    try:
        legacy_raw = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _valid_session_dict(legacy_raw)


def save_template_session(template_dir_path: str, data: dict[str, Any]) -> None:
    path = ui_state_file(template_dir_path)
    current = _read_ui_state(path)
    updated = current.model_copy(
        update={"template_last_launch": {"version": _SESSION_VERSION, **data}}
    )
    _write_ui_state(path, updated)
