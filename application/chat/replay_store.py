"""Per-dialog presentation checkpoints and derived replay audio (no chat writes)."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.chat_history.storage import chat_history_session_dir


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
        elif kind == "stats.update":
            self.frame["stats"] = event.get("stats", [])
        elif kind == "dialog.end":
            match = re.search(r"data-dialog-id=['\"]([0-9a-f]{64})['\"]", event.get("fullHtml", ""))
            if match:
                self.store.write(match[1], "frame.json", portable_urls(copy.deepcopy(self.frame)))
