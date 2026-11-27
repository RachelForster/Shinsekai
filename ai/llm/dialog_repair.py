"""Tool-free repair policy and cross-format history normalization for runtime dialogue."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.llm.template.session import (
    DIALOG_REPAIR_PROMPT_SPEC,
    DialogRepairPromptContext,
)
from core.chat_history.identity import CHAT_OUTPUT_FORMAT
from core.messaging.dialog_output import has_valid_dialog_output
from core.messaging.formats.registry import (
    parse_dialog_content,
    resolve_dialog_format,
)
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, DialogOutputFormat


def _repair_prompt(
    media_field: str,
    *,
    retry: bool,
    allow_unbound_speakers: bool = False,
    bound_speakers: Sequence[str] = (),
    locale: LocaleInput = None,
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID,
) -> str:
    fmt = resolve_dialog_format(output_format_id)
    resolved_locale = resolve_dynamic_locale(locale)
    try:
        custom = fmt.render_repair_prompt(
            media_field=media_field,
            retry=retry,
            locale=resolved_locale,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=tuple(bound_speakers),
        )
    except TypeError:
        custom = fmt.render_repair_prompt(
            media_field=media_field,
            retry=retry,
            locale=resolved_locale,
        )
    if isinstance(custom, str) and custom.strip():
        return custom
    return DIALOG_REPAIR_PROMPT_SPEC.render_user(
        DialogRepairPromptContext(
            media_field=media_field,
            retry=retry,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=tuple(bound_speakers),
            output_format_id=fmt.format_id,
            locale=resolved_locale,
        )
    )


def normalize_messages_for_output_format(
    messages: list[dict[str, Any]],
    target_format: DialogOutputFormat,
) -> list[dict[str, Any]]:
    """Return outbound request messages converted to `target_format` when needed.

    Never mutates the persisted history list or its message dicts in place.
    """
    target_id = target_format.format_id
    updated: list[dict[str, Any]] | None = None
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if msg.get("tool_calls"):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        source_format = str(msg.get(CHAT_OUTPUT_FORMAT) or "").strip().lower()
        if source_format == target_id:
            continue
        if not source_format and target_format.can_parse(content):
            continue
        items = parse_dialog_content(content, format_id=source_format or None)
        if not items:
            continue
        converted = target_format.serialize(items)
        if not converted:
            continue
        if updated is None:
            updated = list(messages)
        updated[index] = {**msg, "content": converted}
    return updated if updated is not None else messages


class ChatAdapter(Protocol):
    def chat(self, messages: list[dict], stream: bool = False, **kwargs: Any) -> Any: ...


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(
            block_text
            for block in content
            if isinstance((block_text := getattr(block, "text", None)), str)
        )

    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        choice_text = getattr(message, "content", None)
        if isinstance(choice_text, str):
            return choice_text
    return ""


def repair_dialog_output(
    adapter: ChatAdapter,
    content: str,
    messages: list[dict],
    generation_kwargs: dict[str, Any],
    *,
    cancelled: Callable[[], bool],
    event_logger: logging.Logger,
    max_attempts: int = 2,
    media_selection_mode: str = "indexed",
    speaker_requires_media: Callable[[str], bool] | None = None,
    bound_speakers: Sequence[str] = (),
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID,
    locale: LocaleInput = None,
) -> str:
    """Repair malformed dialogue output without mutating persisted chat history."""
    resolved_format_id = resolve_dialog_format(output_format_id).format_id
    if has_valid_dialog_output(
        content,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=speaker_requires_media,
        format_id=resolved_format_id,
    ):
        return content

    attempts = max(1, int(max_attempts))
    repair_messages = copy.deepcopy(messages)
    repair_messages.append({"role": "assistant", "content": content})
    request_kwargs = dict(generation_kwargs)
    request_kwargs.pop("tools", None)

    for attempt in range(attempts):
        if cancelled():
            return content
        media_field = (
            "vibe"
            if str(media_selection_mode or "").strip().lower() == "semantic"
            else "sprite"
        )
        prompt = _repair_prompt(
            media_field,
            retry=attempt > 0,
            allow_unbound_speakers=speaker_requires_media is not None,
            bound_speakers=bound_speakers,
            locale=locale,
            output_format_id=resolved_format_id,
        )
        repair_messages.append({"role": "user", "content": prompt})
        try:
            response = adapter.chat(
                messages=repair_messages,
                stream=False,
                tools=None,
                **request_kwargs,
            )
            if cancelled():
                return content
            repaired = _response_text(response)
            decode = getattr(adapter, "decode_response", None)
            if callable(decode):
                try:
                    decoded_content = decode(response).content
                except (AttributeError, IndexError, KeyError, TypeError):
                    pass  # Legacy structural adapters may return plain text.
                else:
                    if isinstance(decoded_content, str):
                        repaired = decoded_content
            if not repaired:
                raise RuntimeError("empty format-repair response")
        except Exception as exc:
            event_logger.error(
                "LLM dialogue format repair failed",
                extra={
                    "event": "llm.dialog_format.repair_failed",
                    "attempt": attempt + 1,
                    "error_type": type(exc).__name__,
                    "output_format": resolved_format_id,
                    "raw_chars": len(content),
                },
            )
            return content

        if has_valid_dialog_output(
            repaired,
            media_selection_mode=media_selection_mode,
            speaker_requires_media=speaker_requires_media,
            format_id=resolved_format_id,
        ):
            event_logger.warning(
                "Recovered malformed LLM dialogue output with a tool-free repair request",
                extra={
                    "event": "llm.dialog_format.repaired",
                    "attempt": attempt + 1,
                    "output_format": resolved_format_id,
                    "raw_chars": len(content),
                    "repaired_chars": len(repaired),
                },
            )
            return repaired

        repair_messages.append({"role": "assistant", "content": repaired})

    event_logger.error(
        "LLM dialogue format repair returned no valid dialogue",
        extra={
            "event": "llm.dialog_format.repair_invalid",
            "attempts": attempts,
            "output_format": resolved_format_id,
            "raw_chars": len(content),
        },
    )
    return content
