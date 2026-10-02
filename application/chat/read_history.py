"""Read chat history and issue bounded download capabilities."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.chat_history.storage import remove_chat_history_storage
from core.messaging.dialog_tokens import (
    SYSTEM_HISTORY_NAMES,
    is_option_history_name,
    normalize_character_name,
)
from core.chat_history.storage import chat_history_active_path, chat_history_download_path
from core.chat_history.text import history_payload_to_plain_text, parse_assistant_dialog_content
from application.chat.history_paths import is_unc_history_path, resolve_history_path_for_project
from application.runtime.state import BridgeState
from sdk.path_utils import reject_control_chars
from application.chat.session_metadata import sanitize_session_display_name, chat_user_display_name
from application.chat.session_metadata import DEFAULT_USER_DISPLAY_NAME

_HISTORY_DOWNLOAD_CAPABILITY_TTL_SECONDS = 60.0


def resolve_history_file(state: BridgeState, raw_path: str | Path) -> Path:
    return resolve_history_path_for_project(state, raw_path)


def history_entry_role_from_text(text: str) -> str:
    raw = str(text or "")
    if "你：" in raw or "你:" in raw:
        return "user"
    if is_option_history_name(raw.split("：", 1)[0].split(":", 1)[0].strip()):
        return "options"
    speaker = normalize_character_name(raw.split("：", 1)[0].split(":", 1)[0].strip())
    if speaker in SYSTEM_HISTORY_NAMES:
        return "system"
    return "assistant"


def message_created_at_ms(message: dict[str, Any]) -> int | None:
    for key in ("createdAt", "created_at", "timestamp", "ts"):
        raw = message.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return int(raw * 1000) if raw < 10_000_000_000 else int(raw)
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            if text.isdigit():
                num = int(text)
                return num * 1000 if num < 10_000_000_000 else num
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                continue
    return None


def serialize_history_entries_from_messages(
    messages: Any,
    user_display_name: str = DEFAULT_USER_DISPLAY_NAME,
) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    entries: list[dict[str, Any]] = []
    user_index = 0
    row_index = 0
    user_name = sanitize_session_display_name(user_display_name) or DEFAULT_USER_DISPLAY_NAME
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role == "user":
            text = str(message.get("display_content") or message.get("content") or "").strip()
            if not text:
                continue
            entry = {
                "id": f"history-{row_index}",
                "revertUserIndex": user_index,
                "role": "user",
                "text": f"{user_name}: {text}",
            }
            created_at = message_created_at_ms(message)
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
                    "role": history_entry_role_from_text(plain),
                    "text": plain,
                }
            )
            row_index += 1
    return entries


def history_entries_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    return [dict(item) for item in (snapshot.get("historyEntries") or []) if isinstance(item, dict)]


def chat_history_entries(state: BridgeState) -> list[dict[str, Any]]:
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if session_id and chat_stream is not None:
        snapshot = chat_stream.get_snapshot(session_id)
        if isinstance(snapshot, dict) and "historyEntries" in snapshot:
            entries = history_entries_from_snapshot(snapshot)
            return entries
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if history_raw and is_unc_history_path(history_raw):
        return []
    history_path = resolve_history_file(state, history_raw) if history_raw else None
    if history_path is not None and is_unc_history_path(history_path):
        return []
    history_file = chat_history_active_path(history_path) if history_path is not None else None
    if history_file is None or not history_file.is_file():
        return []
    return serialize_history_entries_from_messages(read_history_file(history_file), chat_user_display_name(state))


def read_chat_history(state: BridgeState) -> list[dict[str, Any]]:
    return chat_history_entries(state)


def plain_history_text(raw: Any) -> str:
    return history_payload_to_plain_text(raw)


def plain_history_text_from_entries(entries: list[dict[str, Any]]) -> str:
    return history_payload_to_plain_text(entries)


def read_history_file(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def current_chat_history_download_file(state: BridgeState) -> Path:
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if not history_raw:
        raise FileNotFoundError("没有已关联的聊天历史文件。")
    history_path = resolve_history_file(state, history_raw)
    history_file = chat_history_download_path(history_path)
    if not history_file.is_file():
        raise FileNotFoundError(history_file.as_posix())
    return history_file


def copy_history_payload(state: BridgeState) -> dict[str, Any]:
    text = plain_history_text_from_entries(chat_history_entries(state))
    opened_path = str(state.chat_session.get("historyPath") or "").strip()
    if not text:
        if not opened_path:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        path = chat_history_active_path(resolve_history_file(state, opened_path))
        if not path.exists():
            raise FileNotFoundError(path.as_posix())
        text = plain_history_text(read_history_file(path))
        opened_path = path.as_posix()
    return {"clipboardText": text, "openedPath": opened_path}


def open_history_payload(state: BridgeState) -> dict[str, Any]:
    path = current_chat_history_download_file(state)
    capability = issue_chat_history_download_capability(state, path)
    return {"downloadUrl": f"/api/chat/history-file?cap={quote(capability, safe='')}", "openedPath": path.as_posix()}


def clear_chat_history(state: BridgeState) -> None:
    raw = str(state.chat_session.get("historyPath") or "").strip()
    if not raw:
        raise FileNotFoundError("没有已关联的聊天历史文件。")
    remove_chat_history_storage(resolve_history_file(state, raw))


def history_download_state(state: BridgeState) -> tuple[threading.Lock, dict[str, tuple[str, float]]]:
    lock = getattr(state, "history_download_lock", None)
    if lock is None:
        lock = threading.Lock()
        setattr(state, "history_download_lock", lock)
    capabilities = getattr(state, "history_download_capabilities", None)
    if not isinstance(capabilities, dict):
        capabilities = {}
        setattr(state, "history_download_capabilities", capabilities)
    return lock, capabilities


def issue_chat_history_download_capability(state: BridgeState, history_file: Path) -> str:
    capability = uuid.uuid4().hex
    lock, capabilities = history_download_state(state)
    with lock:
        # Only the latest requested history download remains valid.
        capabilities.clear()
        capabilities[capability] = (
            str(history_file),
            time.monotonic() + _HISTORY_DOWNLOAD_CAPABILITY_TTL_SECONDS,
        )
    return capability


def resolve_history_download(state: BridgeState, capability: str) -> Path:
    supplied = reject_control_chars(
        str(capability or "").strip(),
        field="history download capability",
    )
    if not supplied:
        raise PermissionError("missing chat history download capability")
    lock, capabilities = history_download_state(state)
    now = time.monotonic()
    with lock:
        expired = [token for token, (_path, deadline) in capabilities.items() if deadline < now]
        for token in expired:
            capabilities.pop(token, None)
        record = capabilities.get(supplied)
    if record is None:
        raise PermissionError("invalid or expired chat history download capability")
    history_file = Path(record[0])
    if not history_file.is_file():
        raise FileNotFoundError(history_file.as_posix())
    return history_file
