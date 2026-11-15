"""Persist story turns and restore story state during chat rollback."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable, Sequence
import html
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_db_path,
    legacy_active_history_branch,
    load_branch_state,
    save_branch_state,
    session_id_for_history_path,
    write_active_history_snapshot,
)
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.messaging.dialog_tokens import (
    SYSTEM_HISTORY_NAMES,
    normalize_character_name,
)
from application.chat.history.paths import is_unc_history_path
from application.chat.host.ports import HistoryPort, StoryCoordinatorPort

def _story_choice_label(session: Any, choice_id: str) -> str:
    snapshot = session.chat_snapshot()
    for option in snapshot.get("options") or []:
        if not isinstance(option, dict):
            continue
        if str(option.get("id") or "") != choice_id:
            continue
        label = str(option.get("label") or "").strip()
        if label:
            return label
    return choice_id


def _scene_history_role(character_id: str) -> str:
    speaker = normalize_character_name(character_id)
    if speaker in SYSTEM_HISTORY_NAMES:
        return "system"
    return "assistant"


def _scene_turn_already_recorded(
    entries: Sequence[dict[str, Any]], user_text: str, dialogue: Sequence[Any]
) -> bool:
    if not entries:
        return False
    expected_user = user_text.strip()
    user_entry = next(
        (item for item in reversed(entries) if str(item.get("role") or "") == "user"),
        None,
    )
    if user_entry is None:
        return False
    user_body = str(user_entry.get("text") or "")
    if expected_user not in user_body:
        return False
    if not dialogue:
        return True
    last = str(entries[-1].get("text") or "")
    return str(getattr(dialogue[-1], "text", "") or "") in last


def _scene_dialog_events(dialogue: Sequence[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in dialogue:
        speaker = str(item.character_id or "")
        is_system = _scene_history_role(speaker) == "system"
        events.append(
            {
                "type": "dialog.end",
                "speaker": speaker,
                "color": "",
                "isSystem": is_system,
                "fullHtml": f"<p>{html.escape(item.text)}</p>",
            }
        )
    return events


class StoryHistoryRecorder:
    def __init__(self, history: HistoryPort, user_name: Callable[[Any], str]) -> None:
        self.history, self.user_name = history, user_name

    def persist_choice(self, state: Any, label: str, user_name: str) -> None:
        self._append_history(
            state,
            [{"role": "user", "content": label}],
            [f"<b>{user_name}</b>：{label}"],
        )

    def persist_scene(
        self, state: Any, user_text: str, user_name: str, dialogue: Sequence[Any]
    ) -> None:
        self._append_history(
            state,
            [{"role": "user", "content": user_text}]
            + [
                {"role": "assistant", "name": item.character_id, "content": item.text}
                for item in dialogue
            ],
            [f"<b>{html.escape(user_name)}</b>：{html.escape(user_text)}"]
            + [
                f"<b>{html.escape(item.character_id)}</b>：{html.escape(item.text)}"
                for item in dialogue
            ],
        )

    def _append_history(
        self, state: Any, new_messages: list[dict], new_history: list[str]
    ) -> None:
        history_raw = str(state.chat_session.get("historyPath") or "").strip()
        if not history_raw or is_unc_history_path(history_raw):
            return
        history_path = self.history.resolve(state, history_raw)
        if is_unc_history_path(history_path):
            return
        active = chat_history_active_path(history_path)
        db_path = chat_history_db_path(history_path)
        if db_path.is_file():
            # The bridge may record a structured story choice while the chat
            # process owns the session. Release our connection immediately.
            branch = legacy_active_history_branch(history_path)
            store = SqliteSessionStore(db_path, session_id=session_id_for_history_path(history_path))
            try:
                for message in new_messages:
                    store.append_raw_message(message, branch_id=branch)
                messages = store.build_full_raw_messages(branch_id=branch)
            finally:
                store.close()
        else:
            loaded = self.history.read(active) if active.is_file() else []
            messages = [*(loaded if isinstance(loaded, list) else []), *new_messages]
        write_active_history_snapshot(active, messages)
        branch_state = load_branch_state(history_path)
        if branch_state is None:
            return
        branches = branch_state.get("branches")
        if not isinstance(branches, dict):
            return
        active_id = str(branch_state.get("active") or "main")
        branch = branches.get(active_id)
        if not isinstance(branch, dict):
            return
        history = list(branch.get("history") or [])
        history.extend(new_history)
        branch["messages"] = list(messages)
        branch["history"] = history
        save_branch_state(history_path, branch_state)

    def record_choice(self, state: Any, label: str) -> list[dict[str, Any]]:
        entries = [dict(item) for item in self.history.entries(state)]
        user_name = self.user_name(state)
        user_index = sum(
            (1 for item in entries if str(item.get("role") or "") == "user")
        )
        entries.append(
            {
                "id": f"history-{len(entries)}",
                "revertUserIndex": user_index,
                "role": "user",
                "text": f"{user_name}: {label}",
            }
        )
        self.persist_choice(state, label, user_name)
        return entries

    def record_scene(
        self, state: Any, user_text: str, dialogue: Sequence[Any]
    ) -> list[dict[str, Any]]:
        entries = [dict(item) for item in self.history.entries(state)]
        if _scene_turn_already_recorded(entries, user_text, dialogue):
            return entries
        user_name = self.user_name(state)
        user_index = sum(
            (1 for item in entries if str(item.get("role") or "") == "user")
        )
        entries.append(
            {
                "id": f"history-{len(entries)}",
                "revertUserIndex": user_index,
                "role": "user",
                "text": f"{user_name}: {user_text}",
            }
        )
        for item in dialogue:
            entries.append(
                {
                    "id": f"history-{len(entries)}",
                    "role": _scene_history_role(item.character_id),
                    "text": f"{item.character_id}: {item.text}",
                }
            )
        self.persist_scene(state, user_text, user_name, dialogue)
        return entries


class StoryHistoryRollback:
    def __init__(
        self, story: StoryCoordinatorPort, resolve: Callable[[Any, str | Path], Path]
    ) -> None:
        self.story, self.resolve = story, resolve

    def restore(self, state: Any, user_index: int) -> None:
        session = self.story.session(state)
        if session is not None:
            generation = session.checkpoint_generation_before_user_index(user_index)
            session.restore_generation(generation)

    def publish(self, state: Any) -> None:
        if self.story.session(state) is None:
            return
        self.story.publish(state, self.story.patch(state))

    def discard(self, state: Any) -> None:
        history_raw = str(state.chat_session.get("historyPath") or "").strip()
        if history_raw and (not is_unc_history_path(history_raw)):
            history_path = self.resolve(state, history_raw)
            if not is_unc_history_path(history_path):
                self.story.discard(history_path)
        self.story.clear(state)
