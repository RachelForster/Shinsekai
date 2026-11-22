"""Named conversations, independent of mutable templates and character selection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from application.chat.history.paths import resolve_history_path_for_project
from application.story.prompt_turns import PROMPT_TURN_FILENAME
from core.chat_history.models import MEMORY_MODE_ISOLATED, normalize_memory_mode
from core.chat_history.sqlite_session_store import (
    borrow_session_store_for_dir,
    read_session_preferences_readonly,
)
from core.chat_history.storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    HISTORY_DB_FILENAME,
    STORY_SESSION_FILENAME,
    chat_history_active_path,
    chat_history_branch_tree_path,
    chat_history_db_path,
    chat_history_session_dir,
    chat_history_storage_files,
    prune_chat_history_storage,
    read_active_chat_history,
)
from core.chat_history.text import chat_history_to_turns, parse_assistant_dialog_content
from core.messaging.dialog_tokens import (
    NARR_ALIASES,
    SYSTEM_UI_SKIP,
    normalize_character_name,
)


# All bridge windows and HTTP worker threads share this metadata transaction lock.
_metadata_lock = threading.RLock()


def _conversation_store(state: Any) -> Any | None:
    stores = getattr(state, "stores", None)
    return getattr(stores, "conversations", None) if stores is not None else None


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
    active = chat_history_active_path(path)
    active.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Never replace a snapshot already written by the chat process.
        with active.open("x", encoding="utf-8") as file:
            file.write("[]")
    except FileExistsError:
        pass
    conv_id = _id(path)
    store = _conversation_store(state)
    with _metadata_lock:
        if store is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            existing_rec = store.get(conv_id)
            title = (
                (existing_rec.title if existing_rec is not None else "")
                or str(payload.get("conversationTitle") or "").strip()[:120]
            )
            created_at = (
                existing_rec.created_at
                if existing_rec is not None and existing_rec.created_at
                else datetime.now(timezone.utc).isoformat()
            )
            launch = {**payload, "historyPath": path.as_posix(), "resetHistory": False}
            store.put(
                conv_id,
                ConversationRecord(
                    id=conv_id,
                    history_path=path.as_posix(),
                    title=title,
                    created_at=created_at,
                    launch=launch,
                    requires_character_selection=False,
                ),
            )
        else:
            target = _directory(state) / f"{conv_id}.json"
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
    if "memoryMode" in payload or "autoOutfitSwitch" in payload:
        with borrow_session_store_for_dir(
            chat_history_session_dir(path),
            create_if_dir_exists=False,
        ) as store:
            if store is not None:
                if "memoryMode" in payload and str(payload.get("memoryMode") or "").strip():
                    store.set_memory_mode(normalize_memory_mode(str(payload["memoryMode"])))
                if "autoOutfitSwitch" in payload and isinstance(payload.get("autoOutfitSwitch"), bool):
                    store.set_auto_outfit_switch(bool(payload["autoOutfitSwitch"]))


def _records(state: Any) -> dict[str, dict]:
    records: dict[str, dict] = {}
    store = _conversation_store(state)
    if store is not None:
        for rec in store.list_all():
            if not rec.history_path:
                continue
            path = Path(rec.history_path)
            active = chat_history_active_path(path)
            if (
                active.is_file()
                or Path(str(active) + ".tmp").is_file()
                or chat_history_db_path(path).is_file()
                or chat_history_branch_tree_path(path).is_file()
            ):
                records[_id(path)] = rec.to_legacy_dict()
    else:
        for file in _directory(state).glob("*.json"):
            value = _read(file)
            if (
                isinstance(value, dict)
                and isinstance(value.get("historyPath"), str)
                and value["historyPath"]
            ):
                path = Path(value["historyPath"])
                active = chat_history_active_path(path)
                if (
                    active.is_file()
                    or Path(str(active) + ".tmp").is_file()
                    or chat_history_db_path(path).is_file()
                    or chat_history_branch_tree_path(path).is_file()
                ):
                    records[_id(path)] = value
    root = Path(state.history_dir).resolve()
    candidates = (
        list(root.glob("*.json"))
        + list(root.rglob(ACTIVE_HISTORY_FILENAME))
        + list(root.rglob(HISTORY_DB_FILENAME))
        + list(root.rglob(BRANCH_TREE_FILENAME))
    )
    for active in candidates:
        if not active.resolve().is_relative_to(root):
            continue
        path = (
            active.parent
            if active.name in {ACTIVE_HISTORY_FILENAME, HISTORY_DB_FILENAME, BRANCH_TREE_FILENAME}
            else active
        )
        if (
            active.name not in {ACTIVE_HISTORY_FILENAME, HISTORY_DB_FILENAME, BRANCH_TREE_FILENAME}
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


def _history_messages(active: Path) -> list:
    return read_active_chat_history(active)


def recent_character_dialogs(
    state: Any, name: str, *, limit: int = 200, max_sessions: int = 10
) -> list[list[dict]]:
    """Read recent active branches once, preserving conversation boundaries.

    Only the requested character's raw media instructions leave this reader.
    Reuse the same legacy migration and live-journal recovery as conversation UI.
    """
    from application.chat.history.paths import is_unc_history_path

    candidates = []
    for record in _records(state).values():
        try:
            path = resolve_history_path_for_project(state, record["historyPath"])
            if is_unc_history_path(path):
                continue
            active = chat_history_active_path(path)
            db_path = chat_history_db_path(path)
            modified = max(
                file.stat().st_mtime
                for file in (active, Path(str(active) + ".tmp"), db_path, chat_history_branch_tree_path(path))
                if file.is_file()
            )
            candidates.append((modified, active))
        except (OSError, ValueError):
            continue
    result = []
    remaining = limit
    for _, active in sorted(candidates, key=lambda entry: (-entry[0], str(entry[1])))[
        :100
    ]:
        dialogs = []
        seen = set()
        for message in _history_messages(active):
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            for item in parse_assistant_dialog_content(message.get("content")):
                if not isinstance(item, dict):
                    continue
                speaker = str(
                    item.get("character_name", item.get("name", "")) or ""
                ).strip()
                if speaker.casefold() != name.strip().casefold():
                    continue
                identity = item.get("dialog_id") or item.get("_dialog_id")
                if isinstance(identity, str) and identity:
                    if identity in seen:
                        continue
                    seen.add(identity)
                dialogs.append(
                    {
                        "text": str(item.get("speech", item.get("text", "")) or "")[
                            :240
                        ],
                        "vibe": str(item.get("vibe") or "")[:160],
                        "assetId": item.get("sprite", item.get("asset_id")),
                    }
                )
        if dialogs:
            result.append(dialogs[-remaining:])
            remaining -= len(result[-1])
        if remaining <= 0 or len(result) >= max_sessions:
            break
    return result


def _details(record: dict) -> dict:
    path = Path(record["historyPath"])
    active = chat_history_active_path(path)
    messages = _history_messages(active)
    turns = chat_history_to_turns(messages) if messages else []
    launch = record.get("launch")
    launch = launch if isinstance(launch, dict) else {}
    candidates = launch.get("characters") or [
        turn["speaker"] for turn in turns if turn["role"] == "assistant"
    ]
    # Dialogue control roles are not participants or user-facing default titles.
    reserved = SYSTEM_UI_SKIP | NARR_ALIASES
    characters = list(
        dict.fromkeys(
            name.strip()
            for name in candidates
            if isinstance(name, str) and name.strip()
            and normalize_character_name(name) not in reserved
        )
    )
    directory = chat_history_session_dir(path)
    binding = _read(directory / "story-prompt-binding.json")
    binding = binding if isinstance(binding, dict) else {}
    story_file = directory / STORY_SESSION_FILENAME
    story_path = binding.get("storyPath") or launch.get("storyPath") or ""
    story = bool(story_path) or story_file.is_file()
    db_file = chat_history_db_path(path)
    modified = max(
        file.stat().st_mtime
        for file in (active, Path(str(active) + ".tmp"), db_file)
        if file.is_file()
    )
    if story_file.is_file():
        modified = max(modified, story_file.stat().st_mtime)
    prefs = read_session_preferences_readonly(directory)
    if db_file.is_file():
        memory_mode = str(prefs.get("memoryMode") or "")
        auto_outfit_switch = bool(prefs.get("autoOutfitSwitch", True))
    else:
        raw_launch_mode = launch.get("memoryMode")
        memory_mode = (
            normalize_memory_mode(str(raw_launch_mode))
            if isinstance(raw_launch_mode, str) and raw_launch_mode.strip()
            else (MEMORY_MODE_ISOLATED if story else str(prefs.get("memoryMode") or "shared"))
        )
        launch_auto_outfit = launch.get("autoOutfitSwitch")
        auto_outfit_switch = launch_auto_outfit if isinstance(launch_auto_outfit, bool) else True
    title = record.get("title") or launch.get("templateName") or ""
    if not title:
        title = " · ".join(characters[:3])
    conv_id = _id(path)
    return {
        "id": conv_id,
        "sessionId": conv_id,
        "title": title,
        "characters": characters,
        "preview": turns[-1]["content"][:180] if turns else "",
        "updatedAt": modified * 1000,
        "kind": "story" if story else "normal",
        "storyPath": story_path,
        "historyPath": path.as_posix(),
        "hasSettings": bool(launch) and not record.get("requiresCharacterSelection", False),
        "requiresCharacterSelection": bool(record.get("requiresCharacterSelection")),
        "memoryMode": memory_mode,
        "autoOutfitSwitch": auto_outfit_switch,
        "outfits": dict(prefs.get("outfits") or {}),
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
    details = _details(record)
    launch = record.get("launch")
    if not isinstance(launch, dict):
        # Old records contain the original system prompt, but no launch settings.
        # Preserve it rather than borrowing the last opened, unrelated template.
        messages = _history_messages(chat_history_active_path(path))
        messages = messages if isinstance(messages, list) else []
        system = next(
            (
                item.get("content", "")
                for item in messages
                if isinstance(item, dict) and item.get("role") == "system"
            ),
            "",
        )
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
    return {
        **launch,
        "memoryMode": details["memoryMode"],
        "autoOutfitSwitch": details["autoOutfitSwitch"],
        "historyPath": path.as_posix(),
        "resetHistory": False,
    }


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
    store = _conversation_store(state)
    if store is not None:
        rec = store.get(_id(history_path))
        record = rec.to_legacy_dict() if rec is not None else None
    else:
        record = _read(_directory(state) / f"{_id(history_path)}.json")
    if not isinstance(record, dict) or not isinstance(record.get("launch"), dict):
        return None
    details = _details(record)
    return {
        **record["launch"],
        "memoryMode": details["memoryMode"],
        "autoOutfitSwitch": details["autoOutfitSwitch"],
        "historyPath": history_path.as_posix(),
        "resetHistory": False,
    }


def rename_conversation(state: Any, conversation_id: str, title: str) -> dict:
    title = str(title).strip()
    if not title or len(title) > 120:
        raise ValueError("conversation title must contain 1–120 characters")
    store = _conversation_store(state)
    with _metadata_lock:
        record = _record(state, conversation_id)
        record["title"] = title
        if store is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            store.put(conversation_id, ConversationRecord.from_legacy_dict(conversation_id, record))
        else:
            _write(_directory(state) / f"{conversation_id}.json", record)
        return _details(record)


def update_conversation_settings(
    state: Any,
    conversation_id: str,
    payload: Mapping[str, Any],
) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError("conversation settings payload must be an object")
    next_mode: str | None = None
    if "memoryMode" in payload:
        raw_mode = str(payload.get("memoryMode") or "").strip().lower()
        if raw_mode not in {"isolated", "shared", "inherit_readonly"}:
            raise ValueError(
                "memoryMode must be 'isolated', 'shared', or 'inherit_readonly'"
            )
        next_mode = normalize_memory_mode(raw_mode)
    next_auto_outfit: bool | None = None
    if "autoOutfitSwitch" in payload:
        raw_auto = payload.get("autoOutfitSwitch")
        if not isinstance(raw_auto, bool):
            raise ValueError("autoOutfitSwitch must be a boolean")
        next_auto_outfit = raw_auto

    with _metadata_lock:
        record = _record(state, conversation_id)
        path = resolve_history_path_for_project(state, record["historyPath"])
        launch = record.get("launch")
        launch_dict = dict(launch) if isinstance(launch, dict) else {}
        if next_mode is not None:
            launch_dict["memoryMode"] = next_mode
        if next_auto_outfit is not None:
            launch_dict["autoOutfitSwitch"] = next_auto_outfit
        if launch_dict:
            record["launch"] = launch_dict
        store_obj = _conversation_store(state)
        if store_obj is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            store_obj.put(
                conversation_id,
                ConversationRecord.from_legacy_dict(conversation_id, record),
            )
        else:
            _write(_directory(state) / f"{conversation_id}.json", record)

        directory = chat_history_session_dir(path)
        with borrow_session_store_for_dir(
            directory,
            create_if_dir_exists=chat_history_db_path(path).is_file(),
        ) as store:
            if store is not None:
                if next_mode is not None:
                    store.set_memory_mode(next_mode)
                if next_auto_outfit is not None:
                    store.set_auto_outfit_switch(next_auto_outfit)
        details = _details(record)

    active_history = str(getattr(state, "chat_session", {}).get("historyPath") or "").strip()
    if active_history:
        try:
            active_id = _id(resolve_history_path_for_project(state, active_history))
        except Exception:
            active_id = ""
        if active_id == conversation_id:
            from application.chat.composition import _handle_chat_command

            if next_mode is not None:
                state.chat_session = {**state.chat_session, "memoryMode": next_mode}
                try:
                    _handle_chat_command(
                        state,
                        {"type": "set-memory-mode", "payload": {"memoryMode": next_mode}},
                    )
                except RuntimeError:
                    pass
            if next_auto_outfit is not None:
                state.chat_session = {
                    **state.chat_session,
                    "autoOutfitSwitch": next_auto_outfit,
                }
                try:
                    _handle_chat_command(
                        state,
                        {
                            "type": "set-auto-outfit-switch",
                            "payload": {"enabled": next_auto_outfit},
                        },
                    )
                except RuntimeError:
                    pass
    return details


def update_conversation_character(state: Any, old_name: str, new_name: str | None = None) -> None:
    """Migrate renamed cast references; require editing after a cast member is deleted."""
    store = _conversation_store(state)
    with _metadata_lock:
        if store is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            for rec in store.list_all():
                record = rec.to_legacy_dict()
                if not isinstance(record.get("launch"), dict):
                    continue
                if _rewrite_launch_cast_reference(record, old_name, new_name):
                    store.put(rec.id, ConversationRecord.from_legacy_dict(rec.id, record))
            return
        for target in _directory(state).glob("*.json"):
            record = _read(target)
            if not isinstance(record, dict) or not isinstance(record.get("launch"), dict):
                continue
            if _rewrite_launch_cast_reference(record, old_name, new_name):
                _write(target, record)


def _rewrite_launch_cast_reference(record: dict, old_name: str, new_name: str | None) -> bool:
    launch = record["launch"]
    editor = launch.get("editorSession")
    changed = False
    for settings, keys in ((launch, ("characters", "primaryCharacters")), (editor, ("selectedCharacters", "primaryCharacters"))):
        if not isinstance(settings, dict):
            continue
        if settings.get("playerCharacter") == old_name:
            settings["playerCharacter"] = new_name or ""
            changed = True
        for key in keys:
            names = settings.get(key)
            if not isinstance(names, list) or old_name not in names:
                continue
            changed = True
            if new_name is not None:
                settings[key] = list(dict.fromkeys(new_name if name == old_name else name for name in names))
    if changed and new_name is None:
        record["requiresCharacterSelection"] = True
    return changed


def delete_conversation(state: Any, conversation_id: str) -> None:
    from application.chat.composition import _chat_runtime_status
    from application.chat.start_chat import _chat_init_lock

    with _chat_init_lock(state), _metadata_lock:
        record = _record(state, conversation_id)
        if getattr(state, "chat_init_task_id", ""):
            raise RuntimeError("Wait for chat initialization to finish before deleting.")
        active = getattr(state, "chat_session", {}).get("historyPath")
        if active and _id(Path(active)) == conversation_id and _chat_runtime_status(state)["state"] != "idle":
            raise RuntimeError("Close this chat before deleting it.")
        path = resolve_history_path_for_project(state, record["historyPath"])
        _delete_conversation_files(state, path)


def _conversation_storage_files(state: Any, path: Path) -> tuple[Path, ...]:
    """One ownership list for conversation cleanup and recoverable story deletion."""
    directory = chat_history_session_dir(path)
    legacy = Path(str(directory) + ".json")
    if legacy.is_file() and (directory / "branches.json").is_file():
        path = legacy
    return (
        *chat_history_storage_files(path),
        directory / "story-prompt-binding.json",
        directory / f"{STORY_SESSION_FILENAME}.lock",
        directory / PROMPT_TURN_FILENAME,
        _directory(state) / f"{_id(path)}.json",
    )


def _delete_conversation_files(state: Any, path: Path) -> None:
    """Remove validated storage while the caller holds initialization/metadata locks."""
    for file in _conversation_storage_files(state, path):
        file.unlink(missing_ok=True)
    prune_chat_history_storage(path)
    store = _conversation_store(state)
    if store is not None:
        store.delete(_id(path))
