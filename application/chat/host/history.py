"""Project history and manage short-lived download capabilities."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable
import json
import threading
from datetime import datetime
from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    is_option_history_name,
    normalize_character_name,
)
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_download_path,
)
from core.chat_history.text import (
    history_payload_to_plain_text,
    parse_assistant_dialog_content,
)
from application.chat.history.paths import is_unc_history_path
from application.chat.host.projection import _sanitize_user_display_name
from sdk.path_utils import reject_control_chars

_DEFAULT_USER_DISPLAY_NAME = "你"
_SYSTEM_HISTORY_NAMES = (
    COT_ALIASES | NARR_ALIASES | STAT_ALIASES | SCENE_ALIASES | BGM_ALIASES | CG_ALIASES
)


def _history_entry_role_from_text(text: str) -> str:
    raw = str(text or "")
    if "你：" in raw or "你:" in raw:
        return "user"
    if is_option_history_name(raw.split("：", 1)[0].split(":", 1)[0].strip()):
        return "options"
    speaker = normalize_character_name(raw.split("：", 1)[0].split(":", 1)[0].strip())
    if speaker in _SYSTEM_HISTORY_NAMES:
        return "system"
    return "assistant"


def _message_created_at_ms(message: dict[str, Any]) -> int | None:
    for key in ("createdAt", "created_at", "timestamp", "ts"):
        raw = message.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return int(raw * 1000) if raw < 10000000000 else int(raw)
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            if text.isdigit():
                num = int(text)
                return num * 1000 if num < 10000000000 else num
            try:
                return int(
                    datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                    * 1000
                )
            except ValueError:
                continue
    return None


def _serialize_history_entries_from_messages(
    messages: Any, user_display_name: str = _DEFAULT_USER_DISPLAY_NAME
) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    entries: list[dict[str, Any]] = []
    user_index = 0
    row_index = 0
    user_name = (
        _sanitize_user_display_name(user_display_name) or _DEFAULT_USER_DISPLAY_NAME
    )
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role == "user":
            text = str(
                message.get("display_content") or message.get("content") or ""
            ).strip()
            if not text:
                continue
            entry = {
                "id": f"history-{row_index}",
                "revertUserIndex": user_index,
                "role": "user",
                "text": f"{user_name}: {text}",
            }
            created_at = _message_created_at_ms(message)
            if created_at is not None:
                entry["createdAt"] = created_at
            entries.append(entry)
            user_index += 1
            row_index += 1
            continue
        if role != "assistant":
            continue
        for item in parse_assistant_dialog_content(message.get("content", "")):
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("character_name") or "").strip()
            speech = str(item.get("speech") or "").strip()
            if not speech:
                continue
            plain = f"{speaker}: {speech}" if speaker else speech
            entries.append(
                {
                    "id": f"history-{row_index}",
                    "role": _history_entry_role_from_text(plain),
                    "text": plain,
                }
            )
            row_index += 1
    return entries


def _history_entries_from_snapshot(
    snapshot: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    return [
        dict(item)
        for item in snapshot.get("historyEntries") or []
        if isinstance(item, dict)
    ]


def _plain_history_text(raw: Any) -> str:
    return history_payload_to_plain_text(raw)


def _plain_history_text_from_entries(entries: list[dict[str, Any]]) -> str:
    return history_payload_to_plain_text(entries)


def _read_history_file(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _history_download_state(
    state: Any,
) -> tuple[threading.Lock, dict[str, tuple[str, float]]]:
    lock = getattr(state, "history_download_lock", None)
    if lock is None:
        lock = threading.Lock()
        setattr(state, "history_download_lock", lock)
    capabilities = getattr(state, "history_download_capabilities", None)
    if not isinstance(capabilities, dict):
        capabilities = {}
        setattr(state, "history_download_capabilities", capabilities)
    return (lock, capabilities)


class HistoryProjection:
    def __init__(
        self,
        *,
        resolve: Callable[[Any, str | Path], Path],
        read: Callable[[Path], Any],
        user_name: Callable[[Any], str],
    ) -> None:
        self.resolve, self.read, self.user_name = resolve, read, user_name

    def entries(self, state: Any) -> list[dict[str, Any]]:
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        chat_stream = getattr(state, "chat_stream", None)
        if session_id and chat_stream is not None:
            snapshot = chat_stream.get_snapshot(session_id)
            if isinstance(snapshot, dict) and "historyEntries" in snapshot:
                entries = _history_entries_from_snapshot(snapshot)
                return entries
        history_raw = str(state.chat_session.get("historyPath") or "").strip()
        if history_raw and is_unc_history_path(history_raw):
            return []
        history_path = self.resolve(state, history_raw) if history_raw else None
        if history_path is not None and is_unc_history_path(history_path):
            return []
        history_file = (
            chat_history_active_path(history_path) if history_path is not None else None
        )
        if history_file is None or not history_file.is_file():
            return []
        return _serialize_history_entries_from_messages(
            self.read(history_file), self.user_name(state)
        )


class HistoryDownloads:
    def __init__(
        self,
        *,
        resolve: Callable[[Any, str | Path], Path],
        clock: Callable[[], float],
        token: Callable[[], str],
        ttl: float = 60.0,
    ) -> None:
        self.resolve, self.clock, self.token, self.ttl = resolve, clock, token, ttl

    def current_file(self, state: Any) -> Path:
        history_raw = str(state.chat_session.get("historyPath") or "").strip()
        if not history_raw:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        history_path = self.resolve(state, history_raw)
        history_file = chat_history_download_path(history_path)
        if not history_file.is_file():
            raise FileNotFoundError(history_file.as_posix())
        return history_file

    def issue(self, state: Any, history_file: Path) -> str:
        capability = self.token()
        (lock, capabilities) = _history_download_state(state)
        with lock:
            capabilities.clear()
            capabilities[capability] = (str(history_file), self.clock() + self.ttl)
        return capability

    def fetch(self, state: Any, capability: str) -> Path:
        supplied = reject_control_chars(
            str(capability or "").strip(), field="history download capability"
        )
        if not supplied:
            raise PermissionError("missing chat history download capability")
        (lock, capabilities) = _history_download_state(state)
        now = self.clock()
        with lock:
            expired = [
                token
                for (token, (_path, deadline)) in capabilities.items()
                if deadline < now
            ]
            for token in expired:
                capabilities.pop(token, None)
            record = capabilities.get(supplied)
        if record is None:
            raise PermissionError("invalid or expired chat history download capability")
        history_file = Path(record[0])
        if not history_file.is_file():
            raise FileNotFoundError(history_file.as_posix())
        return history_file
