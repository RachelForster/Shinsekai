"""Keep resolved dialog media selections in the persisted LLM history."""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ai.llm.history_manager import HistoryManager
from sdk.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _ResolvedSprite:
    asset_id: str
    character_name: str
    speech: str


def _dialog_payload(content: Any) -> tuple[dict[str, Any], bool] | None:
    """Return a mutable dialog payload and whether its source was a mapping."""
    if isinstance(content, Mapping):
        payload = copy.deepcopy(dict(content))
        return (payload, True) if isinstance(payload.get("dialog"), list) else None

    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("dialog"), list):
        return None
    return payload, False


class DialogHistoryBinding:
    """Bind asynchronously resolved sprites to one assistant history message.

    Dialog media can finish before or after ``LLMManager`` appends the raw
    assistant response. Resolutions are retained until the worker binds this
    object to that response, then applied immediately on either side of the
    race.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._resolutions: dict[int, _ResolvedSprite] = {}
        self._assistant_message: dict[str, Any] | None = None
        self._history_file: str | None = None

    def bind(self, llm_manager: Any) -> None:
        """Bind to the latest parseable assistant response for this LLM turn."""
        try:
            messages = llm_manager.get_messages()
        except Exception:
            return
        if not isinstance(messages, list):
            return

        with self._lock:
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                if _dialog_payload(message.get("content")) is None:
                    continue
                self._assistant_message = message
                self._history_file = getattr(llm_manager, "_history_file", None)
                self._apply_locked()
                return

    def record(
        self,
        dialog_index: int,
        *,
        asset_id: str | int | None,
        character_name: str,
        speech: str | None,
    ) -> None:
        """Record one lookup result and apply it when history is available."""
        if dialog_index < 0:
            return
        resolved = _ResolvedSprite(
            asset_id=str(asset_id if asset_id is not None else "-1"),
            character_name=str(character_name or ""),
            speech=str(speech or ""),
        )
        with self._lock:
            self._resolutions[dialog_index] = resolved
            self._apply_locked()

    def _apply_locked(self) -> None:
        message = self._assistant_message
        if message is None or not self._resolutions:
            return
        parsed = _dialog_payload(message.get("content"))
        if parsed is None:
            return
        payload, content_was_mapping = parsed
        dialog = payload["dialog"]
        changed = False

        for index, resolved in self._resolutions.items():
            if not 0 <= index < len(dialog):
                continue
            item = dialog[index]
            if not isinstance(item, dict):
                continue
            if str(item.get("character_name", "")) != resolved.character_name:
                continue
            if str(item.get("speech", "") or "") != resolved.speech:
                continue
            if str(item.get("sprite", "-1")) == resolved.asset_id:
                continue
            item["sprite"] = resolved.asset_id
            changed = True

        if not changed:
            return

        previous_message = copy.deepcopy(message)
        message["content"] = (
            payload
            if content_was_mapping
            else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        if self._history_file:
            HistoryManager.replace_message_in_tmp(
                self._history_file,
                previous_message,
                message,
            )
        logger.debug(
            "Persisted resolved sprite selections in assistant history",
            extra={"event": "dialog_media.sprite.persisted"},
        )
