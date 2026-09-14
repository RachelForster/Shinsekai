"""Named conversations, independent of mutable templates and character selection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from application.chat.history_paths import resolve_history_path_for_project
from core.chat_history.storage import (
    ACTIVE_HISTORY_FILENAME,
    STORY_SESSION_FILENAME,
    chat_history_active_path,
    chat_history_session_dir,
    remove_chat_history_storage,
)
from core.chat_history.text import chat_history_to_turns


def _directory(state: Any) -> Path:
    return Path(state.template_dir_path).resolve().parent / "config" / "conversations"


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _id(path: Path) -> str:
    canonical = chat_history_session_dir(path).resolve()
    return hashlib.sha256(os.path.normcase(str(canonical)).encode()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remember_conversation(state: Any, history_path: Path, payload: dict) -> None:
    """Store the effective launch, never a reference to the mutable template body."""
    path = resolve_history_path_for_project(state, history_path)
    target = _directory(state) / f"{_id(path)}.json"
    previous = _read(target)
    previous = previous if isinstance(previous, dict) else {}
    launch = {**payload, "historyPath": path.as_posix(), "resetHistory": False}
    _write(
        target,
        {
            "historyPath": path.as_posix(),
            "title": previous.get("title") or str(payload.get("conversationTitle") or "").strip()[:120],
            "createdAt": previous.get("createdAt")
            or datetime.now(timezone.utc).isoformat(),
            "launch": launch,
        },
    )


def _records(state: Any) -> dict[str, dict]:
    records = {}
    for file in _directory(state).glob("*.json"):
        value = _read(file)
        if (
            isinstance(value, dict)
            and isinstance(value.get("historyPath"), str)
            and value["historyPath"]
        ):
            path = Path(value["historyPath"])
            if chat_history_active_path(path).is_file():
                records[_id(path)] = value
    root = Path(state.history_dir).resolve()
    candidates = list(root.glob("*.json")) + list(root.rglob(ACTIVE_HISTORY_FILENAME))
    for active in candidates:
        if not active.resolve().is_relative_to(root):
            continue
        path = active.parent if active.name == ACTIVE_HISTORY_FILENAME else active
        if (
            active.name != ACTIVE_HISTORY_FILENAME
            and chat_history_active_path(path) != active
        ):
            continue  # A migrated legacy alias is already represented by its directory.
        records.setdefault(_id(path), {"historyPath": path.as_posix()})
    return records


def _record(state: Any, conversation_id: str) -> dict:
    record = _records(state).get(conversation_id)
    if record is None:
        raise KeyError("conversation not found")
    return record


def _details(record: dict) -> dict:
    path = Path(record["historyPath"])
    active = chat_history_active_path(path)
    messages = _read(active)
    turns = chat_history_to_turns(messages) if messages else []
    launch = record.get("launch")
    launch = launch if isinstance(launch, dict) else {}
    characters = launch.get("characters") or list(
        dict.fromkeys(
            turn["speaker"]
            for turn in turns
            if turn["role"] == "assistant" and turn["speaker"]
        )
    )
    directory = chat_history_session_dir(path)
    binding = _read(directory / "story-prompt-binding.json")
    binding = binding if isinstance(binding, dict) else {}
    story = (directory / STORY_SESSION_FILENAME).is_file()
    modified = active.stat().st_mtime
    if story:
        modified = max(modified, (directory / STORY_SESSION_FILENAME).stat().st_mtime)
    title = record.get("title") or launch.get("templateName") or ""
    if not title:
        title = " · ".join(characters[:3])
    return {
        "id": _id(path),
        "title": title,
        "characters": characters,
        "preview": turns[-1]["content"][:180] if turns else "",
        "updatedAt": modified * 1000,
        "kind": "story" if story else "normal",
        "storyPath": binding.get("storyPath", ""),
        "historyPath": path.as_posix(),
        "hasSettings": bool(launch),
    }


def list_conversations(state: Any) -> list[dict]:
    result = []
    for record in _records(state).values():
        try:
            result.append(_details(record))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(result, key=lambda item: item["updatedAt"], reverse=True)


def conversation_launch_payload(state: Any, conversation_id: str) -> dict:
    record = _record(state, conversation_id)
    path = resolve_history_path_for_project(state, record["historyPath"])
    launch = record.get("launch")
    if not isinstance(launch, dict):
        # Old records contain the original system prompt, but no launch settings.
        # Preserve it rather than borrowing the last opened, unrelated template.
        messages = _read(chat_history_active_path(path))
        messages = messages if isinstance(messages, list) else []
        system = next(
            (
                item.get("content", "")
                for item in messages
                if isinstance(item, dict) and item.get("role") == "system"
            ),
            "",
        )
        details = _details(record)
        launch = {
            "templateId": "",
            "templateName": details["title"],
            "scenario": "",
            "system": system,
            "characters": [
                name
                for name in details["characters"]
                if state.config_manager.get_character_by_name(name) is not None
            ],
            "backgroundName": "",
            "mediaSelectionMode": "indexed",
        }
    return {**launch, "historyPath": path.as_posix(), "resetHistory": False}


def conversation_details(state: Any, conversation_id: str) -> dict:
    return _details(_record(state, conversation_id))


def current_conversation(state: Any) -> dict | None:
    history = state.chat_session.get("historyPath")
    if not history:
        return None
    try:
        return conversation_details(
            state, _id(resolve_history_path_for_project(state, history))
        )
    except KeyError:
        return None


def saved_conversation_launch(state: Any, history_path: Path) -> dict | None:
    record = _read(_directory(state) / f"{_id(history_path)}.json")
    if not isinstance(record, dict) or not isinstance(record.get("launch"), dict):
        return None
    return {
        **record["launch"],
        "historyPath": history_path.as_posix(),
        "resetHistory": False,
    }


def rename_conversation(state: Any, conversation_id: str, title: str) -> dict:
    title = str(title).strip()
    if not title or len(title) > 120:
        raise ValueError("conversation title must contain 1–120 characters")
    record = _record(state, conversation_id)
    record["title"] = title
    _write(_directory(state) / f"{conversation_id}.json", record)
    return _details(record)


def delete_conversation(state: Any, conversation_id: str) -> None:
    from application.chat.runtime_process import _chat_runtime_status
    from application.chat.start_chat import _chat_init_lock

    with _chat_init_lock(state):
        record = _record(state, conversation_id)
        if getattr(state, "chat_init_task_id", ""):
            raise RuntimeError("Wait for chat initialization to finish before deleting.")
        active = getattr(state, "chat_session", {}).get("historyPath")
        if active and _id(Path(active)) == conversation_id and _chat_runtime_status(state)["state"] != "idle":
            raise RuntimeError("Close this chat before deleting it.")
        path = resolve_history_path_for_project(state, record["historyPath"])
        directory = chat_history_session_dir(path)
        legacy = Path(str(directory) + ".json")
        if legacy.is_file() and (directory / "branches.json").is_file():
            path = legacy
        remove_chat_history_storage(path)
        (directory / "story-prompt-binding.json").unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        (_directory(state) / f"{conversation_id}.json").unlink(missing_ok=True)
