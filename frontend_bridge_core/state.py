from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


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
    chat_session: dict[str, Any] = field(default_factory=dict)


def _jsonify(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    return value
