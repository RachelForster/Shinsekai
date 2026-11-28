"""Named conversations, independent of mutable templates and character selection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from application.chat.history.paths import resolve_history_path_for_project
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
    read_active_chat_history,
)
from core.chat_history.text import chat_history_to_turns, parse_assistant_dialog_content
from core.document import DocumentRepository
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
    doc_binding = DocumentRepository.read_session_binding(directory)
    novel_doc_id = (
        doc_binding.doc_id
        if doc_binding is not None and doc_binding.behavior_id == "novel_theater"
        else (
            str(launch.get("novelDocId") or "")
            if launch.get("behaviorId") == "novel_theater"
            else ""
        )
    )
    novel = (
        bool(novel_doc_id)
        or (doc_binding is not None and doc_binding.behavior_id == "novel_theater")
        or launch.get("behaviorId") == "novel_theater"
    )
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
            else (
                MEMORY_MODE_ISOLATED
                if (story or novel)
                else str(prefs.get("memoryMode") or "shared")
            )
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
        "kind": "story" if story else ("novel" if novel else "normal"),
        "storyPath": story_path,
        "novelDocId": novel_doc_id,
        "behaviorId": "novel_theater" if novel else str(launch.get("behaviorId") or "").strip(),
        "castEntries": list(launch.get("castEntries") or []) if novel else [],
        "novelNameMode": (
            (
                "actor"
                if str(launch.get("nameMode") or "").strip().lower() == "actor"
                else "story"
            )
            if novel
            else ""
        ),
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
            "outputFormat": "json_v1",
        }
    launch_copy = dict(launch)
    if launch_copy.get("systemStale"):
        from application.chat.conversation_mutations import regenerate_launch_system

        regenerate_launch_system(state, launch_copy)
        launch_copy.pop("systemStale", None)
    return {
        **launch_copy,
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
    launch_copy = dict(record["launch"])
    if launch_copy.get("systemStale"):
        from application.chat.conversation_mutations import regenerate_launch_system

        regenerate_launch_system(state, launch_copy)
        launch_copy.pop("systemStale", None)
    return {
        **launch_copy,
        "memoryMode": details["memoryMode"],
        "autoOutfitSwitch": details["autoOutfitSwitch"],
        "historyPath": history_path.as_posix(),
        "resetHistory": False,
    }


from application.chat.conversation_mutations import (  # noqa: E402
    _conversation_storage_files,
    _delete_conversation_files,
    _reclaim_documents_for_state,
    _registered_session_dirs,
    _rewrite_launch_cast_reference,
    deferred_document_reclamation,
    delete_conversation,
    rename_conversation,
    update_conversation_character,
    update_conversation_launch_fields,
    update_conversation_settings,
)

