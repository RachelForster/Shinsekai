"""Conversation metadata mutations, character migrations, and storage deletion."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from application.chat import conversation_library as _lib
from application.chat.history.paths import (
    _state_project_root,
    resolve_history_path_for_project,
)
from application.documents.reclaim_documents import (
    read_bound_doc_id,
    reclaim_unreferenced_documents,
)
from application.story.prompt_turns import PROMPT_TURN_FILENAME
from core.chat_history.models import normalize_memory_mode
from core.chat_history.sqlite_session_store import borrow_session_store_for_dir
from core.chat_history.storage import (
    STORY_SESSION_FILENAME,
    chat_history_db_path,
    chat_history_session_dir,
    chat_history_storage_files,
    prune_chat_history_storage,
)
from core.document.repository import DOCUMENT_BINDING_FILENAME
from core.storage.layout import StorageLayout


def rename_conversation(state: Any, conversation_id: str, title: str) -> dict:
    title = str(title).strip()
    if not title or len(title) > 120:
        raise ValueError("conversation title must contain 1–120 characters")
    store = _lib._conversation_store(state)
    with _lib._metadata_lock:
        record = _lib._record(state, conversation_id)
        record["title"] = title
        if store is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            store.put(
                conversation_id,
                ConversationRecord.from_legacy_dict(conversation_id, record),
            )
        else:
            _lib._write(_lib._directory(state) / f"{conversation_id}.json", record)
        return _lib._details(record)


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

    with _lib._metadata_lock:
        record = _lib._record(state, conversation_id)
        path = resolve_history_path_for_project(state, record["historyPath"])
        launch = record.get("launch")
        launch_dict = dict(launch) if isinstance(launch, dict) else {}
        if next_mode is not None:
            launch_dict["memoryMode"] = next_mode
        if next_auto_outfit is not None:
            launch_dict["autoOutfitSwitch"] = next_auto_outfit
        if launch_dict:
            record["launch"] = launch_dict
        store_obj = _lib._conversation_store(state)
        if store_obj is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            store_obj.put(
                conversation_id,
                ConversationRecord.from_legacy_dict(conversation_id, record),
            )
        else:
            _lib._write(_lib._directory(state) / f"{conversation_id}.json", record)

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
        details = _lib._details(record)

    active_history = str(
        getattr(state, "chat_session", {}).get("historyPath") or ""
    ).strip()
    if active_history:
        try:
            active_id = _lib._id(resolve_history_path_for_project(state, active_history))
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


def update_conversation_character(
    state: Any, old_name: str, new_name: str | None = None
) -> None:
    """Migrate renamed cast references; require editing after a cast member is deleted."""
    store = _lib._conversation_store(state)
    with _lib._metadata_lock:
        if store is not None:
            from core.storage.stores.conversation_store import ConversationRecord

            for rec in store.list_all():
                record = rec.to_legacy_dict()
                if not isinstance(record.get("launch"), dict):
                    continue
                if _rewrite_launch_cast_reference(record, old_name, new_name):
                    store.put(
                        rec.id,
                        ConversationRecord.from_legacy_dict(rec.id, record),
                    )
            return
        for target in _lib._directory(state).glob("*.json"):
            record = _lib._read(target)
            if not isinstance(record, dict) or not isinstance(
                record.get("launch"), dict
            ):
                continue
            if _rewrite_launch_cast_reference(record, old_name, new_name):
                _lib._write(target, record)


def _rewrite_launch_cast_reference(
    record: dict, old_name: str, new_name: str | None
) -> bool:
    launch = record["launch"]
    editor = launch.get("editorSession")
    changed = False
    for settings, keys in (
        (launch, ("characters", "primaryCharacters")),
        (editor, ("selectedCharacters", "primaryCharacters")),
    ):
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
                settings[key] = list(
                    dict.fromkeys(
                        new_name if name == old_name else name for name in names
                    )
                )
    if changed and new_name is None:
        record["requiresCharacterSelection"] = True
    return changed


def _registered_session_dirs(state: Any) -> tuple[Path, ...]:
    """Enumerate all registered session directories, including external absolute paths."""
    session_dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(raw_path: object) -> None:
        raw = str(raw_path or "").strip()
        if not raw:
            return
        session_dir = chat_history_session_dir(Path(raw))
        resolved = session_dir.resolve(strict=False)
        if resolved not in seen:
            seen.add(resolved)
            session_dirs.append(session_dir)

    store = _lib._conversation_store(state)
    if store is not None:
        for rec in store.list_all():
            _add(getattr(rec, "history_path", ""))
    else:
        meta_dir = _lib._directory(state)
        if meta_dir.is_dir():
            for file in meta_dir.glob("*.json"):
                value = _lib._read(file)
                if isinstance(value, dict):
                    _add(value.get("historyPath"))
    active_history = getattr(state, "chat_session", {}).get("historyPath")
    _add(active_history)
    return tuple(session_dirs)


def _reclaim_documents_for_state(
    state: Any,
    *,
    candidate_doc_ids: Iterable[str] | None = None,
) -> tuple[str, ...]:
    ids = tuple(candidate_doc_ids or ())
    if candidate_doc_ids is not None and not ids:
        return ()
    layout = StorageLayout(_state_project_root(state))
    history_root = Path(
        getattr(state, "history_dir", None) or layout.chat_history_dir
    )
    return reclaim_unreferenced_documents(
        layout,
        history_root=history_root,
        candidate_doc_ids=ids if candidate_doc_ids is not None else None,
        extra_session_dirs=_registered_session_dirs(state),
    )


def delete_conversation(state: Any, conversation_id: str) -> None:
    from application.chat.composition import _chat_runtime_status
    from application.chat.start_chat import _chat_init_lock

    with _chat_init_lock(state), _lib._metadata_lock:
        record = _lib._record(state, conversation_id)
        if getattr(state, "chat_init_task_id", ""):
            raise RuntimeError("Wait for chat initialization to finish before deleting.")
        active = getattr(state, "chat_session", {}).get("historyPath")
        if (
            active
            and _lib._id(Path(active)) == conversation_id
            and _chat_runtime_status(state)["state"] != "idle"
        ):
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
        directory / DOCUMENT_BINDING_FILENAME,
        directory / "story-prompt-binding.json",
        directory / f"{STORY_SESSION_FILENAME}.lock",
        directory / PROMPT_TURN_FILENAME,
        _lib._directory(state) / f"{_lib._id(path)}.json",
    )


def _delete_conversation_files(state: Any, path: Path) -> None:
    """Remove validated storage while the caller holds initialization/metadata locks."""
    session_dir = chat_history_session_dir(path)
    bound_doc_id = read_bound_doc_id(session_dir)
    for file in _conversation_storage_files(state, path):
        file.unlink(missing_ok=True)
    prune_chat_history_storage(path)
    store = _lib._conversation_store(state)
    if store is not None:
        store.delete(_lib._id(path))
    if not bound_doc_id:
        return
    deferred = _DEFERRED_DOC_RECLAIM_CANDIDATES.get()
    if deferred is not None:
        deferred.append(bound_doc_id)
    else:
        _reclaim_documents_for_state(state, candidate_doc_ids=(bound_doc_id,))


_DEFERRED_DOC_RECLAIM_CANDIDATES: ContextVar[list[str] | None] = ContextVar(
    "deferred_doc_reclaim_candidates",
    default=None,
)


@contextmanager
def deferred_document_reclamation(state: Any) -> Iterator[None]:
    """Defer shared-document GC until an outer multi-history transaction commits."""
    candidates: list[str] = []
    token = _DEFERRED_DOC_RECLAIM_CANDIDATES.set(candidates)
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        _DEFERRED_DOC_RECLAIM_CANDIDATES.reset(token)
    if succeeded and candidates:
        _reclaim_documents_for_state(state, candidate_doc_ids=candidates)
