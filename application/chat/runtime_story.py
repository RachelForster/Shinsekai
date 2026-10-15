"""Persist story turns and coordinate their branches with chat history."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable, Sequence
import html
import json
from core.chat_history.storage import (
    chat_history_active_path,
    load_branch_state,
    save_branch_state,
)
from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)
from application.chat.history_paths import is_unc_history_path
from application.chat.runtime_ports import HistoryPort, StoryCoordinatorPort

_SYSTEM_HISTORY_NAMES = (
    COT_ALIASES | NARR_ALIASES | STAT_ALIASES | SCENE_ALIASES | BGM_ALIASES | CG_ALIASES
)


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
    if speaker in _SYSTEM_HISTORY_NAMES or speaker == "narr":
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
        messages: list[Any] = []
        if active.is_file():
            loaded = self.history.read(active)
            if isinstance(loaded, list):
                messages = loaded
        messages.extend(new_messages)
        active.parent.mkdir(parents=True, exist_ok=True)
        with active.open("w", encoding="utf-8") as file:
            json.dump(messages, file, ensure_ascii=False, indent=4)
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


class StoryBranchCoordinator:
    def __init__(
        self, story: StoryCoordinatorPort, resolve: Callable[[Any, str | Path], Path]
    ) -> None:
        self.story, self.resolve = story, resolve

    def allocate_id(self, state: Any, session: Any) -> str:
        max_counter = 1
        history_raw = str(state.chat_session.get("historyPath") or "").strip()
        if history_raw and (not is_unc_history_path(history_raw)):
            history_path = self.resolve(state, history_raw)
            if not is_unc_history_path(history_path):
                branch_state = load_branch_state(history_path)
                if branch_state is not None:
                    try:
                        max_counter = max(
                            max_counter, int(branch_state.get("counter") or 1)
                        )
                    except (TypeError, ValueError):
                        pass
        for branch_id in session.branches:
            suffix = str(branch_id)[7:] if str(branch_id).startswith("branch-") else ""
            if suffix.isdigit():
                max_counter = max(max_counter, int(suffix))
        candidate = max_counter + 1
        while f"branch-{candidate}" in session.branches:
            candidate += 1
        return f"branch-{candidate}"

    def sync(self, state: Any, command: str, body: dict[str, Any]) -> None:
        session = self.story.session(state)
        if session is None:
            return
        if command == "fork-history":
            payload = body.get("payload")
            raw_index = (
                payload.get("userIndex") if isinstance(payload, dict) else payload
            )
            user_index = int(raw_index)
            generation = session.checkpoint_generation_before_user_index(user_index)
            branch_id = self.allocate_id(state, session)
            session.fork(branch_id, generation=generation)
            if isinstance(payload, dict):
                body["payload"] = {**payload, "branchId": branch_id}
            else:
                body["payload"] = {"userIndex": user_index, "branchId": branch_id}
            return
        if command == "switch-branch":
            branch_id = str(body.get("payload") or "").strip()
            if branch_id in session.branches:
                session.switch_branch(branch_id)
            return
        if command == "revert-history":
            generation = session.checkpoint_generation_before_user_index(
                int(body.get("payload"))
            )
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
