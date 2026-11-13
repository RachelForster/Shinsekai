"""Unified Vision Memory policy & Cloud-LLM adaptive guidance parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any, Literal

from config.perception import DEFAULT_SALIENCE_THRESHOLD

ScenePace = Literal["auto", "dialogue_heavy", "action_heavy", "quiet"]
_VALID_SCENE_PACES: frozenset[str] = frozenset({"auto", "dialogue_heavy", "action_heavy", "quiet"})


def _clamp_float(value: Any, low: float, high: float, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


def _sanitize_focus_hint(value: Any, max_chars: int = 48) -> str:
    clean = re.sub(r"\s+", " ", str(value or "").strip()).strip(" \"'“”‘’。；;")
    return clean[:max_chars].rstrip()


@dataclass(slots=True)
class PerceptionMemoryPolicy:
    """Centralized Vision Memory & RP Input Cache policy supporting Cloud LLM self-adaptation."""

    # 1) Live observation window & Cloud LLM episodic summary schedule
    live_window_sec: float = 60.0
    minute_summary_interval_sec: float = 120.0
    max_recent_minute_episodes: int = 2
    max_archived_episodes: int = 12
    min_items_per_summary: int = 2
    archive_batch_size: int = 16

    # 2) Dual-stage summary character budgets
    overall_summary_max_chars: int = 180
    minute_summary_max_chars: int = 120

    # 3) Live-window visual / OCR subtitle budgets
    subtitle_heavy_threshold: int = 3
    visual_beats_subtitle_heavy: int = 2
    visual_beats_visual_heavy: int = 5
    max_live_subtitles: int = 14
    max_visual_track_beats: int = 10
    max_subtitle_track_items: int = 24

    # 4) Salience gating thresholds
    notable_salience_floor: float = DEFAULT_SALIENCE_THRESHOLD
    proactive_salience_threshold: float = DEFAULT_SALIENCE_THRESHOLD
    max_notable_events: int = 16

    # 5) Text recognition priority timing (highlight > subtitle > cursor)
    cursor_subtitle_quiet_sec: float = 4.5
    cursor_hover_dwell_sec: float = 0.55
    cursor_suppress_after_highlight_sec: float = 4.0

    # Shared playback timing and volume thresholds
    quiet_screen_min_reply_interval_sec: float = 120.0
    screen_audio_quiet_window_ms: int = 1500
    screen_audio_pause_silence_ms: int = 2200
    screen_audio_pause_still_ms: int = 1200
    screen_audio_min_playback_ms: int = 300
    screen_audio_silence_rms: float = 0.003
    screen_audio_quiet_ratio: float = 0.35

    # 6) Active Cloud-LLM runtime guidance
    scene_pace: ScenePace = "auto"
    focus_hint: str = ""

    _baseline: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._normalize_in_place()
        self._baseline = self.to_dict()

    def _normalize_in_place(self) -> None:
        self.live_window_sec = _clamp_float(self.live_window_sec, 15.0, 300.0, 60.0)
        self.minute_summary_interval_sec = _clamp_float(
            self.minute_summary_interval_sec, 30.0, 600.0, 120.0
        )
        self.max_recent_minute_episodes = _clamp_int(self.max_recent_minute_episodes, 1, 6, 2)
        self.max_archived_episodes = _clamp_int(self.max_archived_episodes, 2, 32, 12)
        self.min_items_per_summary = _clamp_int(self.min_items_per_summary, 1, 12, 2)
        self.archive_batch_size = _clamp_int(self.archive_batch_size, 4, 48, 16)
        self.overall_summary_max_chars = _clamp_int(self.overall_summary_max_chars, 60, 400, 180)
        self.minute_summary_max_chars = _clamp_int(self.minute_summary_max_chars, 40, 240, 120)
        self.subtitle_heavy_threshold = _clamp_int(self.subtitle_heavy_threshold, 1, 10, 3)
        self.visual_beats_subtitle_heavy = _clamp_int(self.visual_beats_subtitle_heavy, 1, 4, 2)
        self.visual_beats_visual_heavy = _clamp_int(self.visual_beats_visual_heavy, 2, 8, 5)
        self.max_live_subtitles = _clamp_int(self.max_live_subtitles, 4, 30, 14)
        self.max_visual_track_beats = _clamp_int(self.max_visual_track_beats, 2, 32, 10)
        self.max_subtitle_track_items = _clamp_int(self.max_subtitle_track_items, 4, 64, 24)
        self.notable_salience_floor = _clamp_float(
            self.notable_salience_floor, 0.1, 1.0, DEFAULT_SALIENCE_THRESHOLD
        )
        self.proactive_salience_threshold = _clamp_float(
            self.proactive_salience_threshold, 0.1, 1.0, DEFAULT_SALIENCE_THRESHOLD
        )
        self.max_notable_events = _clamp_int(self.max_notable_events, 4, 64, 16)
        self.cursor_subtitle_quiet_sec = _clamp_float(
            self.cursor_subtitle_quiet_sec, 1.5, 30.0, 4.5
        )
        self.cursor_hover_dwell_sec = _clamp_float(
            self.cursor_hover_dwell_sec, 0.2, 5.0, 0.55
        )
        self.cursor_suppress_after_highlight_sec = _clamp_float(
            self.cursor_suppress_after_highlight_sec, 1.0, 20.0, 4.0
        )
        pace = str(self.scene_pace or "auto").strip().lower()
        self.scene_pace = pace if pace in _VALID_SCENE_PACES else "auto"  # type: ignore[assignment]
        self.focus_hint = _sanitize_focus_hint(self.focus_hint)

    def visual_beat_budget(self, live_subtitle_count: int) -> int:
        """Compute how many incremental visual beats to inject alongside live subtitles."""
        if self.scene_pace == "dialogue_heavy" or live_subtitle_count >= self.subtitle_heavy_threshold:
            return self.visual_beats_subtitle_heavy
        if self.scene_pace == "quiet":
            return max(1, min(3, self.visual_beats_visual_heavy))
        return self.visual_beats_visual_heavy

    def screen_playback_audio_settings(self) -> dict[str, int | float]:
        """Send the local playback detector its thresholds with the chat state."""
        return {
            "quietWindowMs": self.screen_audio_quiet_window_ms,
            "pauseSilenceMs": self.screen_audio_pause_silence_ms,
            "pauseStillMs": self.screen_audio_pause_still_ms,
            "minPlaybackMs": self.screen_audio_min_playback_ms,
            "silenceRms": self.screen_audio_silence_rms,
            "quietRatio": self.screen_audio_quiet_ratio,
        }

    def apply_cloud_guidance(self, guidance: Mapping[str, Any] | None) -> dict[str, Any]:
        """Apply bounded runtime adjustments suggested by the Cloud LLM."""
        if not isinstance(guidance, Mapping) or not guidance:
            return {}
        applied: dict[str, Any] = {}

        float_rules: tuple[tuple[str, float, float], ...] = (
            ("live_window_sec", 30.0, 180.0),
            ("minute_summary_interval_sec", 60.0, 300.0),
            ("notable_salience_floor", 0.70, 0.96),
            ("proactive_salience_threshold", 0.70, 0.96),
            ("cursor_subtitle_quiet_sec", 2.0, 15.0),
            ("cursor_hover_dwell_sec", 0.25, 2.5),
        )
        for field_name, low, high in float_rules:
            if field_name in guidance and guidance[field_name] is not None:
                current = getattr(self, field_name)
                updated = round(_clamp_float(guidance[field_name], low, high, current), 3)
                setattr(self, field_name, updated)
                applied[field_name] = updated

        int_rules: tuple[tuple[str, int, int], ...] = (
            ("max_recent_minute_episodes", 1, 6),
            ("subtitle_heavy_threshold", 1, 8),
            ("visual_beats_subtitle_heavy", 1, 4),
            ("visual_beats_visual_heavy", 2, 8),
            ("max_live_subtitles", 6, 24),
        )
        for field_name, low, high in int_rules:
            if field_name in guidance and guidance[field_name] is not None:
                current = getattr(self, field_name)
                updated = _clamp_int(guidance[field_name], low, high, current)
                setattr(self, field_name, updated)
                applied[field_name] = updated

        if "scene_pace" in guidance and guidance["scene_pace"] is not None:
            raw_pace = str(guidance["scene_pace"]).strip().lower()
            if raw_pace in _VALID_SCENE_PACES:
                self.scene_pace = raw_pace  # type: ignore[assignment]
                applied["scene_pace"] = self.scene_pace

        if "focus_hint" in guidance and guidance["focus_hint"] is not None:
            self.focus_hint = _sanitize_focus_hint(guidance["focus_hint"])
            applied["focus_hint"] = self.focus_hint

        return applied

    def reset_adaptive(self) -> None:
        """Restore initial baseline values and clear transient Cloud LLM focus hints."""
        for key, val in self._baseline.items():
            setattr(self, key, val)

    def to_prompt_snapshot(self) -> dict[str, Any]:
        """Compact view shown to the Cloud LLM so it can steer adaptive parameters."""
        return {
            "live_window_sec": self.live_window_sec,
            "minute_summary_interval_sec": self.minute_summary_interval_sec,
            "subtitle_heavy_threshold": self.subtitle_heavy_threshold,
            "visual_beats_subtitle_heavy": self.visual_beats_subtitle_heavy,
            "visual_beats_visual_heavy": self.visual_beats_visual_heavy,
            "notable_salience_floor": round(self.notable_salience_floor, 3),
            "scene_pace": self.scene_pace,
            "focus_hint": self.focus_hint,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "live_window_sec": self.live_window_sec,
            "minute_summary_interval_sec": self.minute_summary_interval_sec,
            "max_recent_minute_episodes": self.max_recent_minute_episodes,
            "max_archived_episodes": self.max_archived_episodes,
            "min_items_per_summary": self.min_items_per_summary,
            "archive_batch_size": self.archive_batch_size,
            "overall_summary_max_chars": self.overall_summary_max_chars,
            "minute_summary_max_chars": self.minute_summary_max_chars,
            "subtitle_heavy_threshold": self.subtitle_heavy_threshold,
            "visual_beats_subtitle_heavy": self.visual_beats_subtitle_heavy,
            "visual_beats_visual_heavy": self.visual_beats_visual_heavy,
            "max_live_subtitles": self.max_live_subtitles,
            "max_visual_track_beats": self.max_visual_track_beats,
            "max_subtitle_track_items": self.max_subtitle_track_items,
            "notable_salience_floor": round(self.notable_salience_floor, 3),
            "proactive_salience_threshold": round(self.proactive_salience_threshold, 3),
            "max_notable_events": self.max_notable_events,
            "cursor_subtitle_quiet_sec": round(self.cursor_subtitle_quiet_sec, 2),
            "cursor_hover_dwell_sec": round(self.cursor_hover_dwell_sec, 2),
            "cursor_suppress_after_highlight_sec": round(
                self.cursor_suppress_after_highlight_sec, 2
            ),
            "quiet_screen_min_reply_interval_sec": self.quiet_screen_min_reply_interval_sec,
            "screen_audio_quiet_window_ms": self.screen_audio_quiet_window_ms,
            "screen_audio_pause_silence_ms": self.screen_audio_pause_silence_ms,
            "screen_audio_pause_still_ms": self.screen_audio_pause_still_ms,
            "screen_audio_min_playback_ms": self.screen_audio_min_playback_ms,
            "screen_audio_silence_rms": self.screen_audio_silence_rms,
            "screen_audio_quiet_ratio": self.screen_audio_quiet_ratio,
            "scene_pace": self.scene_pace,
            "focus_hint": self.focus_hint,
        }


VisionMemoryPolicy = PerceptionMemoryPolicy

__all__ = [
    "PerceptionMemoryPolicy",
    "ScenePace",
    "VisionMemoryPolicy",
]
