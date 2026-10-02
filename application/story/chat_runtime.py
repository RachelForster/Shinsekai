"""Own story choices, history presentation and chat branch coordination."""

from __future__ import annotations

import html
import json
import uuid
from collections.abc import Sequence
from typing import Any

from application.chat.dispatch_commands import CommandContext, CommandRegistry
from core.story import SelectChoice
from sdk.path_utils import reject_control_chars
from core.messaging.dialog_tokens import SYSTEM_HISTORY_NAMES, normalize_character_name
from core.chat_history.storage import (
    chat_history_active_path,
    load_branch_state,
    save_branch_state,
)
from application.chat.history_paths import is_unc_history_path
from application.runtime.state import BridgeState
from application.story.coordinator import (
    bound_story_session,
    clear_story_session,
    discard_story_session_storage,
    publish_story_transition,
    story_snapshot_patch,
)
from application.chat.session_metadata import chat_user_display_name_from_snapshot
from application.chat.read_history import (
    resolve_history_file,
    chat_history_entries,
    read_history_file,
)


def story_choice_label(session: Any, choice_id: str) -> str:
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


def persist_story_choice_messages(
    state: BridgeState,
    label: str,
    user_name: str,
) -> None:
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if not history_raw or is_unc_history_path(history_raw):
        return
    history_path = resolve_history_file(state, history_raw)
    if is_unc_history_path(history_path):
        return
    active = chat_history_active_path(history_path)
    messages: list[Any] = []
    if active.is_file():
        loaded = read_history_file(active)
        if isinstance(loaded, list):
            messages = loaded
    messages.append({"role": "user", "content": label})
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
    history.append(f"<b>{user_name}</b>：{label}")
    branch["messages"] = list(messages)
    branch["history"] = history
    save_branch_state(history_path, branch_state)


def record_story_choice_history(state: BridgeState, label: str) -> list[dict[str, Any]]:
    entries = [dict(item) for item in chat_history_entries(state)]
    user_name = chat_user_display_name_from_snapshot(state)
    user_index = sum(1 for item in entries if str(item.get("role") or "") == "user")
    entries.append(
        {
            "id": f"history-{len(entries)}",
            "revertUserIndex": user_index,
            "role": "user",
            "text": f"{user_name}: {label}",
        }
    )
    persist_story_choice_messages(state, label, user_name)
    return entries


def scene_history_role(character_id: str) -> str:
    speaker = normalize_character_name(character_id)
    if speaker in SYSTEM_HISTORY_NAMES or speaker == "narr":
        return "system"
    return "assistant"


def scene_turn_already_recorded(
    entries: Sequence[dict[str, Any]],
    user_text: str,
    dialogue: Sequence[Any],
) -> bool:
    if not entries:
        return False
    expected_user = user_text.strip()
    user_entry = next(
        (
            item
            for item in reversed(entries)
            if str(item.get("role") or "") == "user"
        ),
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


def persist_scene_turn_messages(
    state: BridgeState,
    user_text: str,
    user_name: str,
    dialogue: Sequence[Any],
) -> None:
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if not history_raw or is_unc_history_path(history_raw):
        return
    history_path = resolve_history_file(state, history_raw)
    if is_unc_history_path(history_path):
        return
    active = chat_history_active_path(history_path)
    messages: list[Any] = []
    if active.is_file():
        loaded = read_history_file(active)
        if isinstance(loaded, list):
            messages = loaded
    messages.append({"role": "user", "content": user_text})
    for item in dialogue:
        messages.append(
            {
                "role": "assistant",
                "name": item.character_id,
                "content": item.text,
            }
        )
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
    history.append(f"<b>{html.escape(user_name)}</b>：{html.escape(user_text)}")
    for item in dialogue:
        history.append(
            f"<b>{html.escape(item.character_id)}</b>：{html.escape(item.text)}"
        )
    branch["messages"] = list(messages)
    branch["history"] = history
    save_branch_state(history_path, branch_state)


def record_scene_turn_history(
    state: BridgeState,
    user_text: str,
    dialogue: Sequence[Any],
) -> list[dict[str, Any]]:
    entries = [dict(item) for item in chat_history_entries(state)]
    if scene_turn_already_recorded(entries, user_text, dialogue):
        return entries
    user_name = chat_user_display_name_from_snapshot(state)
    user_index = sum(1 for item in entries if str(item.get("role") or "") == "user")
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
                "role": scene_history_role(item.character_id),
                "text": f"{item.character_id}: {item.text}",
            }
        )
    persist_scene_turn_messages(state, user_text, user_name, dialogue)
    return entries


def scene_dialog_events(dialogue: Sequence[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in dialogue:
        speaker = str(item.character_id or "")
        is_system = scene_history_role(speaker) == "system"
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


def allocate_aligned_story_branch_id(state: BridgeState, session: Any) -> str:
    max_counter = 1
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if history_raw and not is_unc_history_path(history_raw):
        history_path = resolve_history_file(state, history_raw)
        if not is_unc_history_path(history_path):
            branch_state = load_branch_state(history_path)
            if branch_state is not None:
                try:
                    max_counter = max(max_counter, int(branch_state.get("counter") or 1))
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


def sync_story_session_branch_command(
    state: BridgeState,
    command: str,
    body: dict[str, Any],
) -> None:
    session = bound_story_session(state)
    if session is None:
        return
    if command == "fork-history":
        payload = body.get("payload")
        raw_index = payload.get("userIndex") if isinstance(payload, dict) else payload
        user_index = int(raw_index)
        generation = session.checkpoint_generation_before_user_index(user_index)
        branch_id = allocate_aligned_story_branch_id(state, session)
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
        generation = session.checkpoint_generation_before_user_index(int(body.get("payload")))
        session.restore_generation(generation)


def publish_bound_story_transition(state: BridgeState) -> None:
    if bound_story_session(state) is None:
        return
    publish_story_transition(state, story_snapshot_patch(state))


def discard_bound_story_session(state: BridgeState) -> None:
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    if history_raw and not is_unc_history_path(history_raw):
        history_path = resolve_history_file(state, history_raw)
        if not is_unc_history_path(history_path):
            discard_story_session_storage(history_path)
    clear_story_session(state)

def register_story_choice(registry: CommandRegistry, state: BridgeState) -> None:
    """Bind story-owned operations; the handler contract never exposes state."""

    def choose(context: CommandContext) -> dict[str, Any]:
        body = context.body
        payload = body["payload"]
        story_session = bound_story_session(state)
        if story_session is None:
            raise ValueError("Option selection must be a string.")
        choice_id = reject_control_chars(
            str(payload.get("choiceId") or "").strip(),
            field="choiceId",
        )
        expected_node_id = reject_control_chars(
            str(payload.get("expectedNodeId") or "").strip(),
            field="expectedNodeId",
        )
        try:
            expected_revision = int(payload.get("expectedRevision"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Story choice revision is invalid.") from exc
        if not choice_id or not expected_node_id:
            raise ValueError("Story choice is invalid.")
        command_id = str(body.get("cmdId") or uuid.uuid4().hex)
        history_entries = record_story_choice_history(
            state,
            story_choice_label(story_session, choice_id),
        )
        ack = story_session.execute(
            SelectChoice(
                command_id=command_id,
                expected_revision=expected_revision,
                choice_id=choice_id,
                expected_node_id=expected_node_id,
            ),
            history_entries=history_entries,
        )
        patch = story_session.chat_snapshot()
        patch["storyAck"] = ack.to_payload()
        publish_story_transition(
            state,
            patch,
            history_entries=history_entries,
            presentation_events=ack.presentation_events,
        )
        return context.ports.snapshot( "idle", extra=patch)

    registry.register_option("story-choice", choose)
