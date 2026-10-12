"""Per-conversation voice references and optional saved audio."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from pathlib import Path

from core.chat_history.storage import chat_history_session_dir


_VOICE_ID = re.compile(r"[0-9a-f]{32}\Z")


class VoiceArchive:
    def __init__(self, history_path: str | Path) -> None:
        self.audio_dir = chat_history_session_dir(history_path) / "audio"
        self.index_path = self.audio_dir / "index.json"
        self.cache_dir = (Path.cwd() / "cache" / "audio").resolve()
        self._lock = threading.RLock()
        self._data = {"enabled": False, "voices": {}}
        if self.index_path.is_file():
            try:
                loaded = json.loads(self.index_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("voices"), dict):
                    self._data = loaded
            except (OSError, ValueError):
                pass

    @property
    def enabled(self) -> bool:
        return self._data.get("enabled") is True

    @staticmethod
    def _digest(path: Path) -> str:
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        return value.hexdigest()

    def _write(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def _saved_path(self, relative: str) -> Path | None:
        candidate = (self.audio_dir / relative).resolve()
        if candidate.is_relative_to(self.audio_dir.resolve()):
            return candidate
        return None

    def _cache_path(self, segment: dict) -> Path | None:
        path = Path(str(segment.get("cache") or "")).resolve()
        if not path.is_relative_to(self.cache_dir) or not path.is_file():
            return None
        return path if self._digest(path) == segment.get("sha256") else None

    def _segment_source(self, segment: dict) -> Path:
        for key in ("manual", "saved"):
            saved = self._saved_path(str(segment.get(key) or "")) if segment.get(key) else None
            if saved is not None and saved.is_file():
                return saved
        cache = self._cache_path(segment)
        if cache is not None:
            return cache
        raise ValueError("语音失效（未开启语音存档）")

    def _segments(self, voice_id: str) -> list[dict]:
        if not _VOICE_ID.fullmatch(voice_id):
            raise ValueError("语音记录无效")
        segments = self._data.get("voices", {}).get(voice_id)
        if not isinstance(segments, list) or not segments:
            raise ValueError("语音记录不存在")
        return segments

    def count(self, voice_id: str) -> int:
        return len(self._segments(voice_id))

    def has_voice(self, voice_id: str) -> bool:
        try:
            return self.count(voice_id) > 0
        except ValueError:
            return False

    def source(self, voice_id: str, index: int) -> Path:
        segments = self._segments(voice_id)
        if index < 0 or index >= len(segments):
            raise ValueError("语音片段不存在")
        return self._segment_source(segments[index])

    def _copy(self, source: Path, voice_id: str, index: int, *, manual: bool) -> str:
        relative = f"{'save/' if manual else ''}{voice_id}-{index}{source.suffix.lower()}"
        target = self.audio_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copy2(source, target)
        return relative

    def record(self, voice_id: str, audio_path: str) -> None:
        if not _VOICE_ID.fullmatch(voice_id):
            return
        path = Path(audio_path).resolve()
        if not path.is_relative_to(self.cache_dir) or not path.is_file():
            return
        with self._lock:
            segments = self._data["voices"].setdefault(voice_id, [])
            index = len(segments)
            segment = {"cache": str(path), "sha256": self._digest(path)}
            if self.enabled:
                segment["saved"] = self._copy(path, voice_id, index, manual=False)
            segments.append(segment)
            self._write()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            if enabled:
                for voice_id, segments in self._data["voices"].items():
                    for index, segment in enumerate(segments):
                        saved = self._saved_path(segment["saved"]) if segment.get("saved") else None
                        if saved is not None and saved.is_file():
                            continue
                        source = self._cache_path(segment)
                        if source is not None:
                            segment["saved"] = self._copy(source, voice_id, index, manual=False)
            self._data["enabled"] = bool(enabled)
            self._write()

    def save_voice(self, voice_id: str) -> None:
        with self._lock:
            segments = self._segments(voice_id)
            sources = [self._segment_source(segment) for segment in segments]
            for index, segment in enumerate(segments):
                key = "manual" if self.enabled else "saved"
                existing = self._saved_path(segment[key]) if segment.get(key) else None
                if existing is not None and existing.is_file():
                    continue
                segment[key] = self._copy(sources[index], voice_id, index, manual=self.enabled)
            self._write()
