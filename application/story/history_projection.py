"""Rebuild chat-history files from the atomically committed story history.

These files are projections: interruption during either write is repaired by
running this function again on recovery or command retry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import html
import json
from typing import Any, TYPE_CHECKING

from core.chat_history.storage import (
    ACTIVE_HISTORY_FILENAME,
    branch_state_payload,
    chat_history_active_path,
    chat_history_branch_tree_path,
    chat_history_session_dir,
    load_branch_state,
)

from .persistence import _atomic_write_json

if TYPE_CHECKING:
    from .session import StorySession


def _system_prefix(messages: Sequence[Any]) -> list[dict[str, Any]]:
    prefix = []
    for message in messages:
        if not isinstance(message, Mapping) or message.get("role") != "system":
            break
        prefix.append(dict(message))
    return prefix


def _message(entry: Mapping[str, Any]) -> dict[str, Any]:
    saved = entry.get("message")
    if isinstance(saved, Mapping):
        return dict(saved)
    role = "user" if entry.get("role") == "user" else "assistant"
    if "content" in entry:
        return {"role": role, "content": entry["content"]}
    # Existing story checkpoints contain display text only.
    text = str(entry.get("text") or entry.get("content") or "")
    name, separator, content = text.partition(":" if ":" in text else "：")
    result = {"role": role, "content": content.lstrip() if separator else text}
    if role == "assistant" and separator:
        result["name"] = name
    return result


def _history_markup(entry: Mapping[str, Any]) -> str:
    text = str(entry.get("text") or entry.get("content") or "")
    speaker, separator, body = text.partition(":" if ":" in text else "：")
    if not separator:
        return html.escape(text)
    return f"<b>{html.escape(speaker)}</b>：{html.escape(body.lstrip())}"


def project_story_history(session: StorySession) -> None:
    path = session.owner_history_path
    if not path:
        return
    snapshot = session.to_payload()
    active_path = chat_history_active_path(path)
    active_messages = []
    if active_path.is_file():
        with active_path.open(encoding="utf-8") as file:
            active_messages = json.load(file)
    default_prefix = _system_prefix(
        active_messages if isinstance(active_messages, list) else []
    )
    tree = load_branch_state(path) or {"active": "main", "counter": 1, "branches": {}}
    for branch_id, branch in snapshot["branches"].items():
        saved = tree["branches"].setdefault(
            branch_id,
            {
                "id": branch_id,
                "label": branch_id,
                "parentId": branch["parentId"],
            },
        )
        prefix = _system_prefix(saved.get("messages", ())) or default_prefix
        saved["messages"] = prefix + [
            _message(entry) for entry in branch["historyEntries"]
        ]
        saved["history"] = [
            _history_markup(entry) for entry in branch["historyEntries"]
        ]
    tree["active"] = snapshot["activeBranchId"]
    # Creating branches.json migrates a legacy .json alias to a directory.
    # Write the canonical active file before making that directory authoritative.
    active_path = chat_history_session_dir(path) / ACTIVE_HISTORY_FILENAME
    active_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(active_path, tree["branches"][tree["active"]]["messages"])
    _atomic_write_json(chat_history_branch_tree_path(path), branch_state_payload(tree))
