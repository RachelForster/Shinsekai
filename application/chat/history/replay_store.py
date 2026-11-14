"""Persist per-dialog presentation checkpoints and derived replay audio."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.chat_history.storage import chat_history_session_dir
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.text import parse_assistant_dialog_content
from core.messaging.dialog_tokens import match_scene_name
from sdk.messages import LLMDialogMessage


def replay_history_messages(history_file: Path):
    try:
        messages = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [message for message in messages if isinstance(message, dict)] if isinstance(messages, list) else []


def _index_dialog(by_id, by_text, identity, key, value):
    if identity:
        by_id[identity] = value
    if key not in by_text:
        by_text[key] = value
    elif by_text[key] != value:
        by_text[key] = None


def replay_dialog_inputs(messages):
    """Index original speech and recover explicit sprite instructions from saved turns."""
    by_id, by_text, sprites = {}, {}, {}
    speech_by_id, speech_by_text = {}, {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        identities = DialogIdentities(message.get(CHAT_TURN_ID))
        for item in parse_assistant_dialog_content(message.get("content", "")):
            try:
                dialog = LLMDialogMessage.model_validate(item)
            except (TypeError, ValueError):
                continue
            identity = identities.next(item)
            speaker, text = dialog.name.strip(), (dialog.text or "").strip()
            if match_scene_name(speaker):
                sprites.clear()
                continue
            key = (speaker, text)
            speech = (dialog.translate or "").strip() or text
            if speech:
                _index_dialog(speech_by_id, speech_by_text, identity, key, speech)
            asset_id = str(dialog.asset_id or "")
            if re.fullmatch(r"[1-9][0-9]{0,8}", asset_id):
                sprites[speaker] = asset_id
            if not text or speaker not in sprites:
                continue
            payload = {"asset_id": sprites[speaker], "effect": dialog.effect or ""}
            _index_dialog(by_id, by_text, identity, key, payload)
    return by_id, by_text, speech_by_id, speech_by_text


def portable_urls(value):
    if isinstance(value, dict):
        return {key: portable_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_urls(item) for item in value]
    if isinstance(value, str) and "/api/" in value:
        url = urlsplit(value)
        if url.path.startswith("/api/"):
            query = [(k, v) for k, v in parse_qsl(url.query) if k not in {"token", "shinsekai_bridge_token"}]
            return urlunsplit(("", "", url.path, urlencode(query), ""))
    return value


class ReplayStore:
    def __init__(self, history_path):
        self.directory = chat_history_session_dir(history_path) / "replay"

    def path(self, key: str, suffix: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key) or suffix not in {"frame.json", "voice.json", "wav"}:
            raise ValueError("Invalid replay resource")
        return self.directory / f"{key}.{suffix}"

    def read(self, key, suffix):
        try:
            value = json.loads(self.path(key, suffix).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def write(self, key, suffix, value):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".replay-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path(key, suffix))
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


class ReplayRecorder:
    """Observe resolved stage output; never re-run media selection on playback."""
    def __init__(self, store):
        self.store = store
        self.frame = {"backgroundPath": "", "bgmPath": "", "cgPath": "", "sprites": [], "stats": []}
        self.message = None

    def record_message(self, message):
        if message.dialog_id and message.text:
            # Replay resolves archived audio separately from the original temporary path.
            self.message = (message.dialog_id, message.model_dump(exclude={"audio_path", "voice_id"}))

    def observe(self, event):
        kind = event.get("type")
        if kind == "background.change":
            if self.frame["backgroundPath"] != event.get("url", ""):
                self.frame["sprites"] = []
            self.frame["backgroundPath"] = event.get("url", "")
        elif kind == "bgm.change":
            self.frame["bgmPath"] = event.get("url", "")
        elif kind in {"cg.show", "cg.hide"}:
            self.frame["cgPath"] = event.get("url", "") if kind == "cg.show" else ""
        elif kind == "sprite.show":
            sprite = {k: v for k, v in event.items() if k != "type"}
            sprite["id"] = str(event.get("characterName") or event.get("slot", 0))
            sprite["label"] = str(event.get("characterName") or "")
            sprite["path"] = sprite.pop("url", "")
            sprite["applyMode"] = "restore"
            sprite.pop("transitions", None)
            self.frame["sprites"] = [s for s in self.frame["sprites"]
                                     if s.get("slot") != sprite.get("slot") and s["id"] != sprite["id"]] + [sprite]
        elif kind == "sprites.clear":
            self.frame["sprites"] = []
        elif kind == "sprite.remove":
            name = event.get("characterName")
            self.frame["sprites"] = [sprite for sprite in self.frame["sprites"] if sprite["label"] != name]
        elif kind == "stats.update":
            self.frame["stats"] = event.get("stats", [])
        elif kind == "player.portrait.show":
            self.frame["playerPortrait"] = {
                "characterName": event.get("characterName", ""),
                "url": event.get("url", ""),
                "crop": event.get("crop"),
            }
        elif kind == "dialog.end":
            match = re.search(r"data-dialog-id=['\"]([0-9a-f]{64})['\"]", event.get("fullHtml", ""))
            if match:
                frame = copy.deepcopy(self.frame)
                if self.message and self.message[0] == match[1]:
                    frame["message"] = self.message[1]
                    self.message = None
                self.store.write(match[1], "frame.json", portable_urls(frame))
