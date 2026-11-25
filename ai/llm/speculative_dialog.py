"""Pure, side-effect-free speculative dialog generation helper for prefetching."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import logging
import threading
from typing import Any

from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.template.integrations.localization import LocaleInput
from core.messaging.dialog_output import parse_and_validate_dialog_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeculativeDialogResult:
    """Immutable output of a side-effect-free speculative dialog generation call."""

    dialogs: tuple[dict[str, Any], ...] = ()
    raw_text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    error: str | None = None


def _is_cancelled(cancel_event: threading.Event | None) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _extract_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, Mapping):
        usage = response.get("usage")
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass
    extracted: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = getattr(usage, key, None)
        if isinstance(val, (int, float)):
            extracted[key] = int(val)
    return extracted


def _decode_content(adapter: Any, response: Any) -> str:
    if isinstance(response, str):
        return response
    decode = getattr(adapter, "decode_response", None)
    if callable(decode):
        try:
            decoded = decode(response)
            content = getattr(decoded, "content", None)
            if isinstance(content, str):
                return content
        except (AttributeError, IndexError, KeyError, TypeError):
            pass
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


def run_speculative_dialog_generation(
    *,
    adapter: Any,
    messages: Sequence[Mapping[str, Any]],
    system_prompt: str | None = None,
    generation_kwargs: Mapping[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    media_selection_mode: str = "indexed",
    speaker_requires_media: Callable[[str], bool] | None = None,
    bound_speakers: Sequence[str] = (),
    max_repair_retries: int = 2,
    locale: LocaleInput = None,
) -> SpeculativeDialogResult:
    """Execute one non-streaming, tool-free dialog call without persisting any state."""
    if _is_cancelled(cancel_event):
        return SpeculativeDialogResult(cancelled=True)

    payload_messages: list[dict[str, Any]] = [
        copy.deepcopy(dict(message)) for message in messages
    ]
    if system_prompt is not None and str(system_prompt).strip():
        if not payload_messages or payload_messages[0].get("role") != "system":
            payload_messages.insert(0, {"role": "system", "content": str(system_prompt)})

    safe_kwargs = dict(generation_kwargs or {})
    safe_kwargs.pop("tools", None)
    safe_kwargs.pop("stream", None)

    try:
        response = adapter.chat(
            messages=payload_messages,
            stream=False,
            tools=None,
            **safe_kwargs,
        )
    except Exception as exc:
        if _is_cancelled(cancel_event):
            return SpeculativeDialogResult(cancelled=True)
        logger.warning(
            "Speculative dialog generation failed",
            extra={
                "event": "llm.speculative_dialog.failed",
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        return SpeculativeDialogResult(error=f"{type(exc).__name__}: {exc}")

    if _is_cancelled(cancel_event):
        return SpeculativeDialogResult(cancelled=True)

    usage = _extract_usage(response)
    raw_text = _decode_content(adapter, response)
    if not raw_text:
        return SpeculativeDialogResult(
            raw_text="",
            usage=usage,
            error="empty_response",
        )

    repaired = repair_dialog_output(
        adapter,
        raw_text,
        payload_messages,
        safe_kwargs,
        cancelled=lambda: _is_cancelled(cancel_event),
        event_logger=logger,
        max_attempts=max_repair_retries,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=speaker_requires_media,
        bound_speakers=tuple(bound_speakers),
        locale=locale,
    )
    if _is_cancelled(cancel_event):
        return SpeculativeDialogResult(cancelled=True)

    valid, dialogs = parse_and_validate_dialog_output(
        repaired,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=speaker_requires_media,
    )
    if not valid:
        return SpeculativeDialogResult(
            raw_text=repaired,
            usage=usage,
            error="invalid_dialog_output",
        )
    return SpeculativeDialogResult(
        dialogs=tuple(dialogs),
        raw_text=repaired,
        usage=usage,
    )


__all__ = [
    "SpeculativeDialogResult",
    "run_speculative_dialog_generation",
]
