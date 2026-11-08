"""Read-only history messages consumed by the normal presentation worker."""
from __future__ import annotations

import html
import threading
import time

from sdk.messages import PresentationMessage


PRESENTATION_KEYS = (
    "backgroundPath", "bgmPath", "cgPath", "sprites", "stats", "characterName",
    "dialogHtml", "dialogText", "options", "systemMessageText", "playerPortrait",
)


class ReplayPresentationMessage(PresentationMessage):
    replay_id: str
    epoch: int
    index: int
    preview: bool = False


class ReplayPresentation:
    """Queue ownership, pacing and interruption, without touching chat history."""

    def __init__(self, worker, ui):
        self.worker, self.ui = worker, ui
        self.condition = threading.Condition(threading.RLock())
        self.id = ""
        self.epoch = 0
        self.entries = []
        self.restore = {}
        self.index = 0
        self.paused = self.ended = self.waiting = False
        self.error = ""
        self.skipped = set()
        self.paused_at = None
        self.paused_seconds = 0
        self.last_state = None

    @property
    def active(self):
        return bool(self.id)

    def _emit(self):
        entry = self.entries[self.index] if self.id else {}
        state = {
            "id": self.id, "index": self.index, "total": len(self.entries),
            "paused": self.paused, "ended": self.ended, "waiting": self.waiting,
            "error": self.error,
            "voiceSource": entry.get("voiceSource", ""),
            "voiceLabel": entry.get("voiceLabel", ""),
        } if self.id else None
        if state != self.last_state:
            self.last_state = state
            self.ui._emit({"type": "replay.state", "replay": state})

    def _set_paused(self, value):
        if value and not self.paused:
            self.paused_at = time.monotonic()
        elif not value and self.paused_at is not None:
            self.paused_seconds += time.monotonic() - self.paused_at
            self.paused_at = None
        self.paused = value

    def _clock(self):
        return (self.paused_at or time.monotonic()) - self.paused_seconds

    def _urls(self, value):
        if isinstance(value, str) and value.startswith("/api/"):
            return self.ui._media_url(value)
        if isinstance(value, list):
            return [self._urls(item) for item in value]
        if isinstance(value, dict):
            return {key: self._urls(item) for key, item in value.items()}
        return value

    def _enqueue(self):
        for index in range(self.index, len(self.entries)):
            entry = self.entries[index]
            self.worker.presentation_queue.put(ReplayPresentationMessage(
                audio_path="", name=entry["speaker"], text=entry["body"],
                replay_id=self.id, epoch=self.epoch, index=index,
                preview=index == self.index,
            ))

    def start(self, payload):
        with self.condition:
            if self.active:
                raise ValueError("请先退出当前回放")
            if not payload.get("entries"):
                raise ValueError("回放片段为空")
            self.id = payload["id"]
            self.entries = payload["entries"]
            self.restore = payload["restore"]
            self.epoch += 1
            self.index = 0
            self.paused = self.ended = self.waiting = False
            self.paused_at, self.paused_seconds = None, 0
            self.last_state = None
            self.error = ""
            self.skipped.clear()
            self.ui.replay_active = True
            self._emit()
            self._enqueue()

    def control(self, payload):
        with self.condition:
            if payload.get("id") != self.id:
                return
            action = payload.get("action")
            if action == "stop":
                self.epoch += 1
                self.id = ""
                self.worker.skip_speech()
                self.ui._emit({"type": "presentation.restore", "presentation": self.restore})
                self.ui._emit({"type": "status.change", "status": "idle"})
                self._emit()
                self.ui.replay_active = False
            elif action in {"pause", "play"}:
                self._set_paused(action == "pause")
                self._emit()
            elif action == "seek":
                self.index = max(0, min(len(self.entries) - 1, int(payload["index"])))
                self.epoch += 1
                self._set_paused(not payload.get("playing", False))
                self.ended = self.waiting = False
                self.error = ""
                self.skipped.discard(self.index)
                self.worker.skip_speech()
                self._emit()
                self._enqueue()
            elif action == "skip-voice":
                self.skipped.add(self.index)
                self.waiting = False
                self.error = ""
                self.worker.skip_speech()
                self._emit()
            self.condition.notify_all()

    def voice(self, payload):
        with self.condition:
            if payload.get("id") != self.id:
                return
            entry = next((e for e in self.entries if e["key"] == payload.get("key")), None)
            if entry is None:
                return
            entry["paths"] = payload.get("paths", [])
            entry["voiceError"] = payload.get("error", "")
            if payload.get("paths"):
                entry["voiceSource"] = payload.get("voiceSource", entry.get("voiceSource", ""))
                entry["voiceLabel"] = payload.get("voiceLabel", entry.get("voiceLabel", ""))
            if self.entries[self.index] is entry:
                self.error = entry["voiceError"]
                self._emit()
            self.condition.notify_all()

    def _valid(self, message):
        return message.replay_id == self.id and message.epoch == self.epoch

    def _gate(self, message):
        while self._valid(message) and self.paused:
            self.condition.wait(0.1)
        return self._valid(message)

    def _pace(self, message, seconds):
        remaining = max(0, seconds)
        while remaining > 0 and self._gate(message):
            started = time.monotonic()
            self.condition.wait(min(remaining, 0.05))
            remaining -= time.monotonic() - started
            if self.worker.task_done_requested.is_set():
                break
        return self._gate(message)

    def present(self, message):
        with self.condition:
            if not self._valid(message):
                return
            if not message.preview and not self._gate(message):
                return
            self.index = message.index
            self.waiting = False
            entry = self.entries[self.index]
            self.error = entry.get("voiceError", "")
            self._emit()
            frame = entry.get("frame") or {}
            self.ui._emit({"type": "presentation.restore", "presentation": self._urls({
                "backgroundPath": frame.get("backgroundPath", ""),
                "bgmPath": frame.get("bgmPath", ""), "cgPath": frame.get("cgPath", ""),
                "sprites": frame.get("sprites", []), "stats": frame.get("stats", []),
                "options": [], "systemMessageText": "", "playerPortrait": None,
            })})
            # Use the same dialog event/typewriter and options component as live play.
            self.ui._emit({"type": "dialog.end", "speaker": entry["speaker"],
                           "animate": not self.paused, "color": "",
                           "isSystem": False, "fullHtml": f"<p>{html.escape(entry['body'])}</p>"})
            text_started = self._clock()
            if entry.get("options"):
                self.ui._emit({"type": "options.show", "options": entry["options"],
                               "selectedIndex": entry.get("selectedIndex")})
            if not self._gate(message):
                return
            while (entry.get("waitForVoice") and not entry.get("paths")
                   and self.index not in self.skipped and self._valid(message)):
                self.waiting = True
                self.error = entry.get("voiceError", "")
                self._emit()
                self.condition.wait(0.15)
                if not self._gate(message):
                    return
            if not self._valid(message):
                return
            self.waiting = False
            self._emit()
            paths = list(entry.get("paths") or []) if self.index not in self.skipped else []

        controller = self.worker.playback_controller
        for path in paths:
            with self.condition:
                if not self._gate(message) or self.index in self.skipped:
                    break
            controller.play_and_wait(character_name=entry["speaker"], audio_path=path,
                                     volume=entry.get("voiceVolume", 1.0), timeout_seconds=86400)
            if self.worker.task_done_requested.is_set():
                break
        with self.condition:
            # Text-only lines use the same reading pace as ordinary presentation.
            if not self._pace(message, max(len(entry["body"]) / 8, 0.5) - (self._clock() - text_started)):
                return
            if not self._gate(message):
                return
            if message.index == len(self.entries) - 1:
                self.ended = True
                self._set_paused(True)
                self._emit()
