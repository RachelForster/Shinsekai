"""Small assessment projections and a durable write-ahead record for prompt turns."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from core.chat_history.storage import chat_history_active_path, chat_history_session_dir
from .persistence import _atomic_write_json


def assessment_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist text and attachment metadata, never binary provider payloads."""
    result = {"role": message.get("role")}
    for key in ("display_content", "input_text", "text"):
        if isinstance(message.get(key), str):
            result[key] = message[key]
    content = message.get("content")
    if isinstance(content, str):
        result["content"] = content
    elif isinstance(content, list):
        result["content"] = [
            {
                key: block[key]
                for key in ("type", "text", "name", "media_type", "mimeType", "size")
                if key in block and isinstance(block[key], (str, int))
            }
            for block in content
            if isinstance(block, Mapping)
        ]
    attachments = message.get("attachments")
    if isinstance(attachments, list):
        result["attachments"] = [
            {
                key: item[key]
                for key in ("kind", "name", "mimeType", "size")
                if key in item
            }
            for item in attachments
            if isinstance(item, Mapping)
        ]
    return result


class PromptTurnJournal:
    def __init__(self, history_path: str) -> None:
        self.history_path = history_path
        self.path = chat_history_session_dir(history_path) / "story-prompt-turn.json"

    def load(self) -> dict[str, Any] | None:
        return (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else None
        )

    def save(self, turn: dict[str, Any]) -> None:
        _atomic_write_json(self.path, turn)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def ensure_reply(self, turn: dict[str, Any]) -> None:
        """Repair a crash before append; a turn marker prevents duplicate replies."""
        from ai.llm.history_manager import _tmp_write_lock

        with _tmp_write_lock:
            self._ensure_reply_locked(turn)

    def _ensure_reply_locked(self, turn: dict[str, Any]) -> None:
        active = chat_history_active_path(self.history_path)
        temporary = Path(str(active) + ".tmp")
        marker = turn["message"]["_storyTurnId"]
        if active.exists():
            messages = json.loads(active.read_text(encoding="utf-8"))
            if any(
                isinstance(item, dict) and item.get("_storyTurnId") == marker
                for item in messages
            ):
                return
        if temporary.exists():
            lines = temporary.read_bytes().splitlines(keepends=True)
            offset = 0
            for index, line in enumerate(lines):
                try:
                    message = json.loads(line.decode("utf-8").strip().rstrip(","))
                except (ValueError, UnicodeDecodeError):
                    if index != len(lines) - 1:
                        raise ValueError(
                            "incremental history contains a damaged earlier record"
                        )
                    with temporary.open("r+b") as stream:
                        stream.truncate(offset)
                    break
                if message.get("_storyTurnId") == marker:
                    return
                offset += len(line)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(turn["message"], ensure_ascii=False) + ",\n")
            stream.flush()
            os.fsync(stream.fileno())
