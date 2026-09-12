"""Pure reconciliation for dialogue recovered by a stream repair."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sdk.messages import LLMDialogMessage


_DialogDeliveryKey = tuple[str, str, str | None, str, str, str]


@dataclass(frozen=True, slots=True)
class DialogReconciliationResult:
    """Outcome of comparing delivered dialogue with a repaired response."""

    prefix_matched: bool
    messages_to_append: tuple[LLMDialogMessage, ...]


def _dialog_delivery_key(message: LLMDialogMessage) -> _DialogDeliveryKey:
    """Normalize fields that have equivalent downstream representations."""
    asset_id = None if message.asset_id is None else str(message.asset_id)
    return (
        message.name,
        message.text or "",
        asset_id,
        message.vibe or "",
        message.translate or "",
        message.effect or "",
    )


def reconcile_dialog_repair(
    streamed_messages: Sequence[LLMDialogMessage],
    repaired_messages: Sequence[LLMDialogMessage],
) -> DialogReconciliationResult:
    """Append only the repaired suffix when the stream is its exact prefix."""
    streamed_keys = [_dialog_delivery_key(message) for message in streamed_messages]
    repaired_keys = [_dialog_delivery_key(message) for message in repaired_messages]
    prefix_matched = streamed_keys == repaired_keys[: len(streamed_keys)]
    messages_to_append = (
        tuple(repaired_messages[len(streamed_messages) :])
        if prefix_matched
        else ()
    )
    return DialogReconciliationResult(
        prefix_matched=prefix_matched,
        messages_to_append=messages_to_append,
    )
