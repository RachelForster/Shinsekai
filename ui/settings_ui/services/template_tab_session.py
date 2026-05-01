"""聊天模板页：上次启动聊天时的选项快照（人物、背景、模板正文等）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SESSION_VERSION = 1


def template_session_file(template_dir_path: str) -> Path:
    """与模板目录同处于 data/ 下：data/config/template_tab_last_launch.json"""
    root = Path(template_dir_path).resolve().parent
    return root / "config" / "template_tab_last_launch.json"


def load_template_session(template_dir_path: str) -> dict[str, Any] | None:
    p = template_session_file(template_dir_path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != _SESSION_VERSION:
        return None
    return raw


def save_template_session(template_dir_path: str, data: dict[str, Any]) -> None:
    p = template_session_file(template_dir_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _SESSION_VERSION, **data}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
