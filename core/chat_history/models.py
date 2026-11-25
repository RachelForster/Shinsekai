"""Domain helpers and builders for session TurnNode and CompactCheckpoint models."""

from __future__ import annotations

import copy
import inspect
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.text import (
    history_payload_to_plain_text,
    parse_assistant_dialog_content,
)
from sdk.adapters.session import (
    MEMORY_MODE_INHERIT_READONLY,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
    VALID_MEMORY_MODES,
    CompactCheckpoint,
    ConversationSessionPort,
    MemoryMode,
    OutfitState,
    TruncateReport,
    TurnNode,
    normalize_memory_mode,
)

from sdk.lang import normalize_lang

COMPACT_SUMMARY_SOURCE = "compact_summary"
PERCEPTION_SOURCE = "perception"
CHUNK_FEED_SOURCE = "chunk_feed"
SYNTHETIC_INTERNAL_SOURCES: frozenset[str] = frozenset(
    {PERCEPTION_SOURCE, CHUNK_FEED_SOURCE}
)
COMPACT_UP_TO_SEQ_KEY = "_compact_up_to_seq"
SUMMARY_MARKERS: tuple[str, ...] = (
    "历史对话总结",
    "历史摘要",
    "较早历史已省略",
    "[Conversation Summary]",
    "[History Summary]",
    "これまでの会話の要約",
    "履歴要約",
)
OMITTED_HISTORY_PREFIXES: tuple[str, ...] = (
    "【历史摘要】",
    "[History Summary]",
    "【履歴要約】",
)

_SUMMARY_WRAPPER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^【历史对话总结】以下是之前对话的压缩总结：\n?(.*?)(?:\n\n请基于这个上下文继续对话。)?\s*$",
        flags=re.DOTALL,
    ),
    re.compile(
        r"^\[Conversation Summary\] Compressed summary of earlier dialogue:\n?(.*?)(?:\n\nContinue based on this context\.)?\s*$",
        flags=re.DOTALL,
    ),
    re.compile(
        r"^【これまでの会話の要約】以前の会話の圧縮要約：\n?(.*?)(?:\n\nこの文脈を踏まえて会話を続けてください。)?\s*$",
        flags=re.DOTALL,
    ),
)


def rollback_memory_for_timeline(
    rollback: Callable[..., int],
    session_id: str,
    cutoff: int,
    protected_turn_seqs: Sequence[int] = (),
) -> int:
    if not protected_turn_seqs:
        return int(rollback(session_id, cutoff) or 0)
    try:
        inspect.signature(rollback).bind(
            session_id, cutoff, protected_turn_seqs=protected_turn_seqs
        )
    except (TypeError, ValueError):
        # A legacy plugin that only supports a cutoff cannot safely clean
        # up a save that contains other timelines.
        return 0
    return int(
        rollback(session_id, cutoff, protected_turn_seqs=protected_turn_seqs) or 0
    )


def is_compact_summary_message(message: Any) -> bool:
    """Return True when message is a synthetic compaction or omitted-history summary."""
    if not isinstance(message, Mapping):
        return False
    if str(message.get("source") or "").strip() == COMPACT_SUMMARY_SOURCE:
        return True
    if message.get("role") != "user":
        return False
    content = str(message.get("content") or "")
    return any(marker in content for marker in SUMMARY_MARKERS)


def is_synthetic_internal_source(source: object) -> bool:
    """Return True when source identifies a host-injected non-user turn."""
    return str(source or "").strip().casefold() in SYNTHETIC_INTERNAL_SOURCES


def is_synthetic_internal_message(message: Any) -> bool:
    """Return True when message originated from a synthetic internal source."""
    if not isinstance(message, Mapping):
        return False
    return is_synthetic_internal_source(message.get("source"))


def is_real_user_turn_message(message: Any) -> bool:
    """Return True when message represents an interactive user turn (not synthetic/summary)."""
    if not isinstance(message, Mapping):
        return False
    if message.get("role") != "user":
        return False
    source = str(message.get("source") or "user").strip()
    if is_synthetic_internal_source(source) or source == COMPACT_SUMMARY_SOURCE:
        return False
    return not is_compact_summary_message(message)


def is_omitted_history_summary(content: str) -> bool:
    """Return True when text is a non-LLM omitted-history fallback notice."""
    return str(content or "").strip().startswith(OMITTED_HISTORY_PREFIXES)


def extract_summary_body(content: str) -> str:
    """Unwrap standard summary framing so rolling summaries never double-wrap."""
    text = str(content or "").strip()
    for pattern in _SUMMARY_WRAPPER_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group(1).strip()
    return text


def build_compact_summary_message(
    rolling_summary: str,
    *,
    up_to_seq: int | None = None,
    locale: str | None = "zh_CN",
) -> dict[str, Any]:
    """Construct the canonical synthetic LLM message for a CompactCheckpoint."""
    body = extract_summary_body(rolling_summary)
    if is_omitted_history_summary(body):
        formatted = body
    else:
        loc = normalize_lang(locale)
        if loc == "en":
            formatted = (
                f"[Conversation Summary] Compressed summary of earlier dialogue:\n"
                f"{body}\n\n"
                f"Continue based on this context."
            )
        elif loc == "ja":
            formatted = (
                f"【これまでの会話の要約】以前の会話の圧縮要約：\n"
                f"{body}\n\n"
                f"この文脈を踏まえて会話を続けてください。"
            )
        else:
            formatted = (
                f"【历史对话总结】以下是之前对话的压缩总结：\n"
                f"{body}\n\n"
                f"请基于这个上下文继续对话。"
            )
    msg: dict[str, Any] = {
        "role": "user",
        "source": COMPACT_SUMMARY_SOURCE,
        "content": formatted,
    }
    if up_to_seq is not None:
        msg[COMPACT_UP_TO_SEQ_KEY] = int(up_to_seq)
    return msg


def strip_internal_message_keys(message: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of message without transient internal bookkeeping keys."""
    cleaned = copy.deepcopy(dict(message))
    cleaned.pop("_turn_seq", None)
    cleaned.pop(COMPACT_UP_TO_SEQ_KEY, None)
    return cleaned


def render_messages_to_ui_history(
    messages: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render raw conversation messages into UI HTML rows with stable dialog IDs."""
    rendered: list[str] = []
    identities = DialogIdentities()
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "")
        if role == "user":
            if is_compact_summary_message(message):
                continue
            identities = DialogIdentities(str(message.get(CHAT_TURN_ID, "") or ""))
            if is_synthetic_internal_message(message):
                continue
            display_content = message.get("display_content") or message.get("content", "")
            rendered.append(
                f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                f"<b style='color:white;'>你</b>: {display_content}</p>"
            )
        elif role == "assistant":
            content = message.get("content", "")
            if not content:
                continue
            dialog = parse_assistant_dialog_content(content)
            if not dialog:
                continue
            for item in dialog:
                dialog_id = identities.next(item)
                identity = f" data-dialog-id='{dialog_id}'" if dialog_id else ""
                rendered.append(
                    f"<p{identity} style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                    f"<b style='color:white;'>{item['character_name']}</b>: "
                    f"{item['speech']}</p>"
                )
    return rendered


def turn_node_from_message(
    message: Mapping[str, Any],
    *,
    seq: int = 0,
    branch_id: str = "main",
    outfit_snapshot: Mapping[str, OutfitState] | None = None,
    created_at_ms: int | None = None,
) -> TurnNode:
    """Build an immutable TurnNode from a raw LLM message mapping."""
    clean_msg = strip_internal_message_keys(message)
    role = str(clean_msg.get("role") or "").strip()
    if not role:
        raise ValueError("TurnNode requires a non-empty message role")
    turn_id = str(clean_msg.get(CHAT_TURN_ID) or "").strip()
    source = str(clean_msg.get("source") or ("user" if role == "user" else role)).strip() or role

    speaker = ""
    if role == "user":
        speaker = "user"
    elif role == "assistant":
        dialog = parse_assistant_dialog_content(clean_msg.get("content"))
        for item in reversed(dialog):
            cand = str(item.get("character_name") or "").strip()
            if cand:
                speaker = cand
                break
    elif role == "tool":
        speaker = str(clean_msg.get("name") or "tool").strip()

    raw_attachments = clean_msg.get("attachments")
    attachments: tuple[Mapping[str, Any], ...] = ()
    if isinstance(raw_attachments, Sequence) and not isinstance(raw_attachments, (str, bytes)):
        attachments = tuple(
            copy.deepcopy(dict(item))
            for item in raw_attachments
            if isinstance(item, Mapping)
        )

    rendered_rows = render_messages_to_ui_history([clean_msg])
    rendered_html = "\n".join(rendered_rows)
    plain_text = history_payload_to_plain_text([clean_msg], user_display_name="user")
    ts_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)

    return TurnNode(
        seq=int(seq),
        branch_id=str(branch_id or "main").strip() or "main",
        turn_id=turn_id,
        role=role,
        speaker=speaker,
        raw_message=clean_msg,
        rendered_html=rendered_html,
        plain_text=plain_text,
        voice_id=str(clean_msg.get("voice_id") or "").strip(),
        attachments=attachments,
        source=source,
        outfit_snapshot=dict(outfit_snapshot or {}),
        created_at_ms=ts_ms,
    )


__all__ = [
    "COMPACT_SUMMARY_SOURCE",
    "COMPACT_UP_TO_SEQ_KEY",
    "CompactCheckpoint",
    "ConversationSessionPort",
    "MEMORY_MODE_INHERIT_READONLY",
    "MEMORY_MODE_ISOLATED",
    "MEMORY_MODE_SHARED",
    "MemoryMode",
    "OMITTED_HISTORY_PREFIXES",
    "OutfitState",
    "SUMMARY_MARKERS",
    "TruncateReport",
    "TurnNode",
    "VALID_MEMORY_MODES",
    "build_compact_summary_message",
    "extract_summary_body",
    "is_compact_summary_message",
    "is_omitted_history_summary",
    "is_real_user_turn_message",
    "normalize_memory_mode",
    "render_messages_to_ui_history",
    "strip_internal_message_keys",
    "turn_node_from_message",
]
