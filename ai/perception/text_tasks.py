"""Pure-text local VLM helpers: persistent character voice-style cache & episode compaction."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any

from ai.perception.parser import (
    DEFAULT_VOICE_STYLE,
    sanitize_episode_summary,
    sanitize_voice_style,
)
from ai.perception.prompts import (
    build_episode_summary_messages,
    build_voice_style_messages,
)
from core.perception.cache import build_fallback_episode_summary
from core.perception.models import PerceptionConfig

logger = logging.getLogger(__name__)

_DEFAULT_VOICE_STYLE_CACHE = (
    Path(__file__).resolve().parents[2] / "data" / "cache" / "perception_voice_styles.json"
)

TextCompletionFn = Callable[[list[dict[str, Any]], PerceptionConfig, int, float | None], str]


def _voice_style_cache_key(character_name: str, character_brief: str) -> str:
    digest = hashlib.sha1(character_brief.strip().encode("utf-8")).hexdigest()[:16]
    return f"{character_name.strip()}:{digest}"


class VoiceStyleStore:
    """Thread-safe memory + JSON disk store for lore-free character speaking styles."""

    def __init__(self, cache_path: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        self._path = Path(cache_path) if cache_path is not None else _DEFAULT_VOICE_STYLE_CACHE
        self._styles: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                if self._path.is_file():
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for key, val in raw.items():
                            if isinstance(key, str) and isinstance(val, str) and val.strip():
                                self._styles[key] = val.strip()[:40]
            except (OSError, ValueError):
                logger.debug("failed to load cached perception voice styles", exc_info=True)

    def _persist(self) -> None:
        with self._lock:
            payload = dict(self._styles)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.debug("failed to save cached perception voice styles", exc_info=True)

    def get_cached(self, character_name: str, character_brief: str) -> str | None:
        if not str(character_brief or "").strip():
            return None
        self._ensure_loaded()
        key = _voice_style_cache_key(character_name, character_brief)
        with self._lock:
            return self._styles.get(key)

    def extract(
        self,
        character_name: str,
        character_brief: str,
        config: PerceptionConfig,
        *,
        complete_text: TextCompletionFn,
    ) -> str:
        clean_brief = str(character_brief or "").strip()
        if not clean_brief:
            return DEFAULT_VOICE_STYLE
        cached = self.get_cached(character_name, clean_brief)
        if cached:
            return cached
        messages = build_voice_style_messages(character_name, clean_brief)
        try:
            raw = complete_text(messages, config, 48, min(4.0, config.request_timeout_sec))
        except Exception:
            logger.debug("voice style extraction failed; using default placeholder", exc_info=True)
            return DEFAULT_VOICE_STYLE
        style = sanitize_voice_style(raw, character_name=character_name)
        key = _voice_style_cache_key(character_name, clean_brief)
        with self._lock:
            self._styles[key] = style
        self._persist()
        return style


def summarize_episode_batch(
    batch: Sequence[tuple[float, str, str]],
    config: PerceptionConfig,
    *,
    complete_text: TextCompletionFn,
) -> str:
    """Summarize one slice of evicted working-window items via local VLM text completion."""
    items = list(batch)
    if not items:
        return ""
    messages = build_episode_summary_messages(items)
    try:
        raw = complete_text(messages, config, 140, min(6.0, config.request_timeout_sec))
        summary = sanitize_episode_summary(raw)
        if summary:
            return summary
    except Exception:
        logger.debug("episodic perception summary failed; using deterministic fallback", exc_info=True)
    return build_fallback_episode_summary(items)
