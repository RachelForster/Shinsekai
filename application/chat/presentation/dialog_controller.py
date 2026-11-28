"""Stage dialog emission, history synchronization, and player portrait deferral controller."""

from __future__ import annotations

import html
import re
import threading
from collections.abc import Callable
from typing import Any, MutableSequence

from application.chat.history.state import (
    restore_history_voice_ids,
    serialize_chat_history_entries,
)
from core.messaging.dialog_tokens import NARR_ALIASES, normalize_character_name

from .formatting import _format_dialog_html


class StageDialogController:
    """Coordinate dialog history updates, history snapshot sync, and deferred player portraits."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None],
        chat_history_getter: Callable[[], MutableSequence[str]],
        voice_archive_getter: Callable[[], Any],
        player_character_getter: Callable[[], str],
        show_player_portrait: Callable[[str, int], None],
        record_console_user_message: Callable[[str], None],
    ) -> None:
        self._emit = emit
        self._chat_history_getter = chat_history_getter
        self._voice_archive_getter = voice_archive_getter
        self._player_character_getter = player_character_getter
        self._show_player_portrait = show_player_portrait
        self._record_console_user_message = record_console_user_message
        self._history_sync_lock = threading.Lock()
        self._player_input_visible = False
        self._pending_player_portrait: tuple[str, int] | None = None

    def sync_history_entries(self) -> None:
        # Completion and presentation run on different workers. Publish snapshots
        # in order so a pending snapshot cannot overwrite the completion update.
        with self._history_sync_lock:
            archive = self._voice_archive_getter()
            chat_history = self._chat_history_getter()
            if archive is not None:
                restore_history_voice_ids(chat_history, archive.voice_for_dialog)
            entries = serialize_chat_history_entries(list(chat_history))
            for entry in entries:
                if entry.get("voiceId") and (
                    archive is None or not archive.has_voice(entry["voiceId"])
                ):
                    entry.pop("voiceId", None)
            self._emit(
                {
                    "type": "history.replace",
                    "entries": entries,
                    "voiceArchiveEnabled": bool(archive and archive.enabled),
                }
            )

    def queue_player_portrait(self, name: str, sprite_id: int) -> None:
        if self._player_input_visible:
            self._show_player_portrait(name, sprite_id)
        else:
            self._pending_player_portrait = (name, sprite_id)

    def apply_player_portrait_for_dialog(self, name: str, speech: str) -> None:
        player = self._player_character_getter()

        def compact(value: object) -> str:
            return re.sub(r"\s+", "", str(value or ""))

        relevant = bool(player) and (
            compact(name) == compact(player)
            or (
                normalize_character_name(name) in NARR_ALIASES
                and compact(player) in compact(speech)
            )
        )
        self._player_input_visible = False
        pending = self._pending_player_portrait
        self._pending_player_portrait = None
        if relevant and pending is not None:
            self._show_player_portrait(*pending)

    def update_dialog(
        self,
        name: str,
        speech: str,
        color: str,
        is_system: bool = True,
        voice_id: str = "",
        dialog_id: str = "",
        *,
        animate: bool | None = None,
    ) -> None:
        if animate is None:
            self.apply_player_portrait_for_dialog(name, speech)
        formatted = _format_dialog_html(name, speech, color, is_system)
        if re.fullmatch(r"[0-9a-f]{64}", dialog_id):
            formatted = formatted.replace("<p ", f"<p data-dialog-id='{dialog_id}' ", 1)
        if re.fullmatch(r"[0-9a-f]{32}", voice_id):
            formatted = formatted.replace("<p ", f"<p data-voice-id='{voice_id}' ", 1)
        if animate is None and (str(speech or "").strip() or str(name or "").strip()):
            self._chat_history_getter().append(formatted)
        self._emit(
            {
                "type": "dialog.end",
                "speaker": name or "",
                "color": color or "",
                "isSystem": bool(is_system),
                "fullHtml": formatted,
                **({"animate": animate} if animate is not None else {}),
            }
        )
        if animate is None:
            self.sync_history_entries()

    def record_user_message(self, text: str) -> None:
        self._player_input_visible = True
        self._pending_player_portrait = None
        self._record_console_user_message(text)
        self.sync_history_entries()

    def post_dialog_html(
        self,
        full_html: str,
        *,
        append_history: bool = True,
        speaker: str = "",
        color: str = "",
        is_system: bool = True,
    ) -> None:
        self.apply_player_portrait_for_dialog(
            speaker, html.unescape(re.sub(r"<[^>]*>", "", full_html))
        )
        if append_history and str(full_html or "").strip():
            self._chat_history_getter().append(full_html)
        self._emit(
            {
                "type": "dialog.end",
                "speaker": speaker,
                "color": color,
                "isSystem": bool(is_system),
                "fullHtml": full_html,
            }
        )
        self.sync_history_entries()
