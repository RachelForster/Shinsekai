"""Tool-free repair policy for malformed runtime dialogue output."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any, Protocol

from core.messaging.dialog_output import has_valid_dialog_output


def _repair_prompt(media_field: str, *, retry: bool) -> str:
    prefix = (
        "That reply is STILL not valid. You MUST answer with ONLY"
        if retry
        else "Reformat your immediately preceding answer as"
    )
    return (
        f"{prefix} the application's dialogue JSON. Return only a JSON object "
        f"with a non-empty `dialog` array. Each character, scene, and BGM item "
        f"must have `character_name`, `speech`, and `{media_field}`. Fixed "
        "system items such as COT, NARR, CHOICE, STAT, and CG may omit the media "
        "field. Do not call tools or add markdown."
    )


class ChatAdapter(Protocol):
    def chat(self, messages: list[dict], stream: bool = False, **kwargs: Any) -> Any: ...


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    content = getattr(response, "content", None)
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
) -> str:
    """Repair malformed dialogue JSON without mutating persisted chat history."""
    if has_valid_dialog_output(content, media_selection_mode=media_selection_mode):
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
        prompt = _repair_prompt(media_field, retry=attempt > 0)
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
            if not repaired:
                raise RuntimeError("empty format-repair response")
        except Exception as exc:
            event_logger.error(
                "LLM dialogue format repair failed",
                extra={
                    "event": "llm.dialog_format.repair_failed",
                    "attempt": attempt + 1,
                    "error_type": type(exc).__name__,
                    "raw_chars": len(content),
                },
            )
            return content

        if has_valid_dialog_output(
            repaired,
            media_selection_mode=media_selection_mode,
        ):
            event_logger.warning(
                "Recovered malformed LLM dialogue output with a tool-free JSON repair request",
                extra={
                    "event": "llm.dialog_format.repaired",
                    "attempt": attempt + 1,
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
            "raw_chars": len(content),
        },
    )
    return content
