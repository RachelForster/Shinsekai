"""Tool-free repair policy for malformed runtime dialogue output."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any, Protocol

from core.messaging.dialog_output import has_valid_dialog_output

_DIALOG_FORMAT_REPAIR_PROMPT = (
    "Reformat your immediately preceding answer as the application's dialogue JSON. "
    "Return only a JSON object with a non-empty `dialog` array. Each item must have "
    "`character_name`, `sprite`, and `speech`. Do not call tools or add markdown."
)

_DIALOG_FORMAT_RETRY_PROMPT = (
    "That reply is STILL not valid. You MUST answer with ONLY a JSON object — a "
    "non-empty `dialog` array whose items each have `character_name`, `sprite`, and "
    "`speech`. Output that JSON and nothing else: no prose, no markdown fences, no tool calls."
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
) -> str:
    """Repair malformed dialogue JSON without mutating persisted chat history."""
    if has_valid_dialog_output(content):
        return content

    attempts = max(1, int(max_attempts))
    repair_messages = copy.deepcopy(messages)
    repair_messages.append({"role": "assistant", "content": content})
    request_kwargs = dict(generation_kwargs)
    request_kwargs.pop("tools", None)

    for attempt in range(attempts):
        if cancelled():
            return content
        prompt = _DIALOG_FORMAT_REPAIR_PROMPT if attempt == 0 else _DIALOG_FORMAT_RETRY_PROMPT
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

        if has_valid_dialog_output(repaired):
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
