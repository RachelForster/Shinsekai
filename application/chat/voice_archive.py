"""Per-conversation voice references and optional saved audio."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from core.chat_history.storage import (
    VOICE_ARCHIVE_DIRECTORY,
    VOICE_INDEX_FILENAME,
    VOICE_INDEX_TEMP_PREFIX,
    chat_history_session_dir,
)
from sdk.file_io import durable_mkdir, durable_rename


_VOICE_ID = re.compile(r"[0-9a-f]{32}\Z")


class VoiceArchive:
    def __init__(self, history_path: str | Path) -> None:
        self.audio_dir = chat_history_session_dir(history_path) / VOICE_ARCHIVE_DIRECTORY
        self.index_path = self.audio_dir / VOICE_INDEX_FILENAME
        self.cache_dir = (Path.cwd() / "cache" / "audio").resolve()
        self._lock = threading.RLock()
        self._data = {"enabled": False, "voices": {}, "dialogs": {}}
        self._loaded = False
        self.refresh()

    def refresh(self) -> None:
        """Readers keep their last valid snapshot through transient read failures."""
        with self._lock:
            try:
                loaded = json.loads(self.index_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not isinstance(loaded.get("voices"), dict):
                    raise ValueError("语音索引格式无效")
                if not isinstance(loaded.get("dialogs", {}), dict):
                    raise ValueError("语音对话索引格式无效")
                if any(
                    not re.fullmatch(r"[0-9a-f]{64}", dialog_id)
                    or not isinstance(voice_id, str) or not _VOICE_ID.fullmatch(voice_id)
                    for dialog_id, voice_id in loaded.get("dialogs", {}).items()
                ):
                    raise ValueError("语音对话索引格式无效")
                for voice_id, voice in loaded["voices"].items():
                    segments = voice.get("segments") if isinstance(voice, dict) else voice
                    if (
                        not _VOICE_ID.fullmatch(voice_id)
                        or not isinstance(segments, list)
                        or any(not isinstance(segment, dict) for segment in segments)
                    ):
                        raise ValueError("语音片段索引格式无效")
            except FileNotFoundError:
                self._data = {"enabled": False, "voices": {}, "dialogs": {}}
                self._loaded = False
            except (OSError, ValueError):
                if not self._loaded:
                    raise
            else:
                self._data, self._loaded = loaded, True

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

    def _write(self, data: dict) -> None:
        durable_mkdir(self.audio_dir)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.audio_dir,
                prefix=VOICE_INDEX_TEMP_PREFIX, suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            durable_rename(temporary, self.index_path, replace=True)
            self._data, self._loaded = data, True
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

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
        if isinstance(segments, dict):
            if segments.get("complete") is not True:
                raise ValueError("语音仍在生成，请稍后重试")
            segments = segments.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("语音记录不存在")
        return segments

    def count(self, voice_id: str) -> int:
        with self._lock:
            return len(self._segments(voice_id))

    def has_voice(self, voice_id: str) -> bool:
        try:
            return self.count(voice_id) > 0
        except ValueError:
            return False

    def source(self, voice_id: str, index: int) -> Path:
        with self._lock:
            segments = self._segments(voice_id)
            if index < 0 or index >= len(segments):
                raise ValueError("语音片段不存在")
            return self._segment_source(segments[index])

    def voice_for_dialog(self, dialog_id: str) -> str:
        with self._lock:
            voice_id = self._data.get("dialogs", {}).get(dialog_id, "")
            return voice_id if self.has_voice(voice_id) else ""

    def complete(self, voice_id: str) -> None:
        with self._lock:
            voice = self._data["voices"].get(voice_id)
            if not isinstance(voice, dict) or not voice.get("segments"):
                return
            data = copy.deepcopy(self._data)
            data["voices"][voice_id]["complete"] = True
            self._write(data)

    def _copy(self, source: Path, voice_id: str, index: int, *, manual: bool) -> str:
        relative = f"{'save/' if manual else ''}{voice_id}-{index}{source.suffix.lower()}"
        target = self.audio_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copy2(source, target)
        return relative

    def record(self, voice_id: str, audio_path: str, *, dialog_id: str = "") -> bool:
        if not _VOICE_ID.fullmatch(voice_id):
            return False
        path = Path(audio_path).resolve()
        if not path.is_relative_to(self.cache_dir) or not path.is_file():
            return False
        with self._lock:
            data = copy.deepcopy(self._data)
            voice = data["voices"].setdefault(voice_id, {"segments": [], "complete": False})
            if isinstance(voice, list):
                voice = data["voices"][voice_id] = {"segments": voice, "complete": False}
            segments = voice["segments"]
            index = len(segments)
            segment = {"cache": str(path), "sha256": self._digest(path)}
            if self.enabled:
                segment["saved"] = self._copy(path, voice_id, index, manual=False)
            segments.append(segment)
            voice["complete"] = False
            if re.fullmatch(r"[0-9a-f]{64}", dialog_id):
                data.setdefault("dialogs", {})[dialog_id] = voice_id
            self._write(data)
            return True

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            data = copy.deepcopy(self._data)
            if enabled:
                for voice_id, voice in data["voices"].items():
                    segments = voice.get("segments", []) if isinstance(voice, dict) else voice
                    for index, segment in enumerate(segments):
                        saved = self._saved_path(segment["saved"]) if segment.get("saved") else None
                        if saved is not None and saved.is_file():
                            continue
                        source = self._cache_path(segment)
                        if source is not None:
                            segment["saved"] = self._copy(source, voice_id, index, manual=False)
            data["enabled"] = bool(enabled)
            self._write(data)

    def save_voice(self, voice_id: str) -> None:
        with self._lock:
            self._segments(voice_id)
            data = copy.deepcopy(self._data)
            voice = data["voices"][voice_id]
            segments = voice["segments"] if isinstance(voice, dict) else voice
            sources = [self._segment_source(segment) for segment in segments]
            for index, segment in enumerate(segments):
                key = "manual" if self.enabled else "saved"
                existing = self._saved_path(segment[key]) if segment.get(key) else None
                if existing is not None and existing.is_file():
                    continue
                segment[key] = self._copy(sources[index], voice_id, index, manual=self.enabled)
            self._write(data)
