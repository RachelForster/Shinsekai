"""Pure helpers for turning chat-history payloads into conversation text.

The application stores chat history in several related shapes: raw LLM
messages, rendered history rows, frontend ``historyEntries`` and branch-tree
exports.  This module deliberately has no Qt, bridge or LLM-manager dependency
so clipboard export and memory extraction can share the same normalization.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict


DEFAULT_USER_DISPLAY_NAME = "你"

__all__ = [
    "ChatHistoryTurn",
    "chat_history_to_text",
    "chat_history_to_turns",
    "history_payload_to_plain_text",
    "history_payload_to_turns",
    "parse_assistant_dialog_content",
    "rendered_history_text",
    "turns_to_text",
]


class ChatHistoryTurn(TypedDict):
    """A normalized conversation turn.

    ``content`` is the unprefixed payload when a speaker can be identified;
    ``text`` is the final plain-text row used by clipboard export and chunking.
    Rendered rows with no recognizable speaker keep all text in ``content``.
    """

    role: str
    speaker: str
    content: str
    text: str


def _repair_json_string(text: str) -> str:
    """Repair common control-character and unterminated-string JSON output.

    The behavior intentionally matches the historical parser from
    :mod:`llm.history_manager` so previously tolerated assistant responses keep
    loading after the parser is moved into this dependency-free module.
    """

    result: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        i += 1
        if escaped:
            escaped = False
            result.append(ch)
            continue
        if ch == "\\":
            escaped = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ord(ch) < 0x20:
            if ord(ch) in (0x0A, 0x0D):
                ahead = text[i:].lstrip(" \t\r\n")
                if ahead and ahead[0] in "]}{[":
                    result.append('"')
                    result.append(ch)
                    in_string = False
                    continue
            result.append(f"\\u{ord(ch):04x}")
            continue
        result.append(ch)
    if in_string:
        result.append('"')
    return "".join(result)


def parse_assistant_dialog_content(content: Any) -> list[Any]:
    """Parse an assistant response into its ``dialog`` list.

    Plain JSON objects, fenced JSON, and the same mildly malformed JSON that
    the legacy history loader repaired are supported.  A decoded mapping is
    also accepted, which is useful for third-party history exports.
    """

    if content is None:
        return []
    if isinstance(content, Mapping):
        dialog = content.get("dialog", [])
        return dialog if isinstance(dialog, list) else []

    text = str(content).strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text, flags=re.DOTALL)
    text = text.strip()

    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(_repair_json_string(text))
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                return []
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
    if not isinstance(parsed, dict):
        return []
    dialog = parsed.get("dialog", [])
    return dialog if isinstance(dialog, list) else []


def rendered_history_text(value: Any) -> str:
    """Convert a legacy rendered HTML row to readable plain text."""

    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|li)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                part = item.strip()
            elif isinstance(item, Mapping):
                part = _content_text(item.get("text", item.get("content")))
            else:
                part = ""
            if part:
                parts.append(part)
        return "\n".join(parts)
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).strip()
    except (TypeError, ValueError):
        return str(value).strip()


def _split_speaker(text: str) -> tuple[str, str]:
    first_ascii = text.find(":")
    first_fullwidth = text.find("：")
    positions = [position for position in (first_ascii, first_fullwidth) if position >= 0]
    if not positions:
        return "", text
    position = min(positions)
    speaker = text[:position].strip()
    if not speaker or "\n" in speaker or len(speaker) > 80:
        return "", text
    return speaker, text[position + 1 :].strip()


def _turn(role: str, speaker: str, content: str, *, text: str | None = None) -> ChatHistoryTurn:
    content = str(content or "").strip()
    speaker = str(speaker or "").strip()
    plain = str(text).strip() if text is not None else (f"{speaker}: {content}" if speaker else content)
    return {
        "role": str(role or "unknown").strip() or "unknown",
        "speaker": speaker,
        "content": content,
        "text": plain,
    }


def _turns_from_message(message: Mapping[str, Any], user_display_name: str) -> list[ChatHistoryTurn]:
    role = str(message.get("role") or "").strip().lower()
    if role in {"system", "tool"}:
        return []
    if role == "user":
        content = _content_text(message.get("content"))
        return [_turn("user", user_display_name, content)] if content else []
    if role != "assistant":
        return []

    content_value = message.get("content")
    turns: list[ChatHistoryTurn] = []
    dialog = parse_assistant_dialog_content(content_value)
    for item in dialog:
        if not isinstance(item, Mapping):
            continue
        speaker = _content_text(item.get("character_name"))
        speech = _content_text(item.get("speech"))
        if speech:
            turns.append(_turn("assistant", speaker, speech))
    if turns:
        return turns

    content = _content_text(content_value)
    return [_turn("assistant", "assistant", content)] if content else []


def _turn_from_history_entry(entry: Mapping[str, Any]) -> ChatHistoryTurn | None:
    text = str(entry.get("text") or "").strip()
    if not text:
        return None
    speaker, content = _split_speaker(text)
    return _turn(str(entry.get("role") or "rendered"), speaker, content, text=text)


def _turn_from_rendered_row(row: Any, user_display_name: str) -> ChatHistoryTurn | None:
    text = rendered_history_text(row)
    if not text:
        return None
    speaker, content = _split_speaker(text)
    role = "user" if speaker in {DEFAULT_USER_DISPLAY_NAME, user_display_name} else "rendered"
    return _turn(role, speaker, content, text=text)


def _active_branch_payload(raw: Mapping[str, Any]) -> Mapping[str, Any] | None:
    raw_branches = raw.get("branches")
    branches: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(raw_branches, Mapping):
        branches = [
            (str(branch_id), branch)
            for branch_id, branch in raw_branches.items()
            if isinstance(branch, Mapping)
        ]
    elif isinstance(raw_branches, list):
        branches = [
            (str(branch.get("id") or index), branch)
            for index, branch in enumerate(raw_branches)
            if isinstance(branch, Mapping)
        ]
    if not branches:
        return None

    active_id = str(raw.get("activeBranchId") or raw.get("active") or "").strip()
    for branch_id, branch in branches:
        if branch_id == active_id or str(branch.get("id") or "").strip() == active_id:
            return branch
    for branch_id, branch in branches:
        if branch_id == "main" or str(branch.get("id") or "").strip() == "main":
            return branch
    return branches[0][1]


def _wrapped_history_payload(raw: Mapping[str, Any]) -> Any:
    branch = _active_branch_payload(raw)
    if branch is not None:
        return _wrapped_history_payload(branch)
    # Rendered history is the authoritative representation in branch exports.
    # Empty containers fall through to the next representation.
    for key in ("history", "historyEntries", "messages"):
        value = raw.get(key)
        if isinstance(value, list) and value:
            return value
    for key in ("history", "historyEntries", "messages"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return raw


def chat_history_to_turns(
    raw: Any,
    *,
    user_display_name: str = DEFAULT_USER_DISPLAY_NAME,
) -> list[ChatHistoryTurn]:
    """Normalize supported chat-history payloads into structured turns.

    Supported inputs are raw message lists, rendered string lists, frontend
    ``historyEntries``, wrappers containing ``messages``/``history``/
    ``historyEntries``, and branch exports.  Raw system and tool messages are
    excluded; already-rendered entries remain visible to preserve clipboard
    behavior.
    """

    user_name = str(user_display_name or "").strip() or DEFAULT_USER_DISPLAY_NAME
    if isinstance(raw, Mapping):
        selected = _wrapped_history_payload(raw)
        if selected is raw:
            if "text" in raw:
                turn = _turn_from_history_entry(raw)
                return [turn] if turn is not None else []
            if "role" in raw:
                return _turns_from_message(raw, user_name)
            return []
        raw = selected
    if not isinstance(raw, list):
        return []

    turns: list[ChatHistoryTurn] = []
    for item in raw:
        if isinstance(item, Mapping):
            if "text" in item:
                turn = _turn_from_history_entry(item)
                if turn is not None:
                    turns.append(turn)
            elif "role" in item:
                turns.extend(_turns_from_message(item, user_name))
            else:
                nested = _wrapped_history_payload(item)
                if nested is not item:
                    turns.extend(chat_history_to_turns(nested, user_display_name=user_name))
        else:
            turn = _turn_from_rendered_row(item, user_name)
            if turn is not None:
                turns.append(turn)
    return turns


def turns_to_text(turns: Iterable[Mapping[str, Any]]) -> str:
    """Join normalized turns without adding a trailing newline."""

    rows = [str(turn.get("text") or "").strip() for turn in turns]
    return "\n".join(row for row in rows if row)


def chat_history_to_text(
    raw: Any,
    *,
    user_display_name: str = DEFAULT_USER_DISPLAY_NAME,
) -> str:
    """Return normalized chat history as newline-delimited plain text."""

    return turns_to_text(chat_history_to_turns(raw, user_display_name=user_display_name))


def history_payload_to_turns(
    payload: Any,
    user_display_name: str = DEFAULT_USER_DISPLAY_NAME,
) -> list[str]:
    """Return stable, fully rendered conversation rows for memory consumers."""

    return [
        turn["text"]
        for turn in chat_history_to_turns(payload, user_display_name=user_display_name)
        if turn["text"]
    ]


def history_payload_to_plain_text(
    payload: Any,
    user_display_name: str = DEFAULT_USER_DISPLAY_NAME,
) -> str:
    """Return stable newline-delimited conversation text for a history payload."""

    return "\n".join(history_payload_to_turns(payload, user_display_name=user_display_name))
