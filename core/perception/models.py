"""Domain data models for the universal real-time perception pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

from config.perception import DEFAULT_PERCEPTION_MODEL, GGUF_MODEL_ID


@dataclass(frozen=True, slots=True)
class PerceptionConfig:
    """Normalized runtime configuration for the perception subsystem."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8091/v1"
    api_key: str = "EMPTY"
    model: str = DEFAULT_PERCEPTION_MODEL
    interval_sec: float = 2.0
    frame_max_side: int = 512
    diff_threshold: float = 0.06
    reflex_enabled: bool = True
    reflex_cooldown_sec: float = 15.0
    proactive_enabled: bool = True
    salience_threshold: float = 0.78
    proactive_cooldown_sec: float = 25.0
    request_timeout_sec: float = 10.0
    ocr_enabled: bool = False
    capture_interval_sec: float = 0.5
    ocr_interval_sec: float = 1.0

    @property
    def use_local_ocr(self) -> bool:
        if not self.ocr_enabled:
            return False
        try:
            return urlsplit(self.base_url).hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            return False

    @classmethod
    def from_api_config(cls, api_config: Any) -> "PerceptionConfig":
        if api_config is None:
            return cls()
        return cls(
            enabled=bool(getattr(api_config, "perception_enabled", False)),
            base_url=str(
                getattr(api_config, "perception_base_url", "http://127.0.0.1:8091/v1")
                or "http://127.0.0.1:8091/v1"
            ).strip(),
            api_key=str(getattr(api_config, "perception_api_key", "") or "EMPTY").strip(),
            model=(
                GGUF_MODEL_ID if getattr(api_config, "perception_use_gguf", False)
                else str(getattr(api_config, "perception_model", "") or "").strip() or DEFAULT_PERCEPTION_MODEL
            ),
            interval_sec=max(
                0.4,
                min(60.0, float(getattr(api_config, "perception_interval_sec", 2.0) or 2.0)),
            ),
            frame_max_side=max(
                256,
                min(1280, int(getattr(api_config, "perception_frame_max_side", 512) or 512)),
            ),
            diff_threshold=max(
                0.0,
                min(0.5, float(getattr(api_config, "perception_diff_threshold", 0.06) or 0.0)),
            ),
            reflex_enabled=bool(getattr(api_config, "perception_reflex_enabled", True)),
            reflex_cooldown_sec=max(
                0.5,
                min(
                    60.0,
                    float(getattr(api_config, "perception_reflex_cooldown_sec", 15.0) or 15.0),
                ),
            ),
            proactive_enabled=bool(getattr(api_config, "perception_proactive_enabled", True)),
            salience_threshold=max(
                0.1,
                min(1.0, float(getattr(api_config, "perception_salience_threshold", 0.78) or 0.78)),
            ),
            proactive_cooldown_sec=max(
                3.0,
                min(
                    600.0,
                    float(getattr(api_config, "perception_proactive_cooldown_sec", 25.0) or 25.0),
                ),
            ),
            ocr_enabled=bool(getattr(api_config, "perception_ocr_enabled", False)),
            capture_interval_sec=max(
                0.2, min(5.0, float(getattr(api_config, "perception_capture_interval_sec", 0.5) or 0.5)),
            ),
            ocr_interval_sec=max(
                0.5, min(10.0, float(getattr(api_config, "perception_ocr_interval_sec", 1.0) or 1.0)),
            ),
        )


@dataclass(frozen=True, slots=True)
class ScreenOcrScope:
    mode: Literal["bottom", "full", "region"] = "bottom"
    region: tuple[float, float, float, float] | None = None

    @classmethod
    def from_payload(cls, value: Any) -> "ScreenOcrScope":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("OCR scope must be an object")
        mode = value.get("mode")
        if mode in ("bottom", "full"):
            return cls(mode=mode)
        region = value.get("region")
        if mode != "region" or not isinstance(region, Mapping):
            raise ValueError("OCR scope requires a mode and a region for custom selection")
        try:
            x, y, width, height = (float(region[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("OCR region must contain normalized coordinates") from exc
        if not (
            0 <= x < 1 and 0 <= y < 1 and 0.01 <= width and 0.01 <= height
            and x + width <= 1.000001 and y + height <= 1.000001
        ):
            raise ValueError("OCR region must fit within the shared frame")
        return cls(mode="region", region=(x, y, min(width, 1 - x), min(height, 1 - y)))

    def to_payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"mode": self.mode}
        if self.region is not None:
            result["region"] = dict(zip(("x", "y", "width", "height"), self.region))
        return result


@dataclass(frozen=True, slots=True)
class PerceptionFrame:
    """Latest visual frame captured from screen share or a game plugin."""

    image_base64: str
    mime_type: str = "image/jpeg"
    width: int = 0
    height: int = 0
    source: str = "screen_share"
    game: str = ""
    captured_at: float = field(default_factory=time.time)
    ocr_scope: ScreenOcrScope | None = None

    def to_data_url(self) -> str:
        raw = self.image_base64.strip()
        if raw.startswith("data:image/"):
            return raw
        mime = (self.mime_type or "image/jpeg").strip()
        return f"data:{mime};base64,{raw}"


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """Discrete game or UI event queued in the Tier-0 raw buffer."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "plugin"
    game: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_compact_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"event": self.event_type}
        if self.game:
            payload["game"] = self.game
        if self.data:
            payload.update(self.data)
        return payload


@dataclass(frozen=True, slots=True)
class RawPerceptionSnapshot:
    """Atomic batch drained from PerceptionRawBuffer for local VLM digestion."""

    states: dict[str, dict[str, Any]]
    events: tuple[PerceptionEvent, ...]
    frame: PerceptionFrame | None
    revision: int
    drained_at: float = field(default_factory=time.time)

    @property
    def is_empty(self) -> bool:
        return not self.states and not self.events and self.frame is None

    @property
    def primary_game(self) -> str:
        for ev in reversed(self.events):
            if ev.game:
                return ev.game
        if self.frame and self.frame.game:
            return self.frame.game
        for key in self.states:
            _, _, game = key.partition(":")
            if game:
                return game
        return ""


@dataclass(frozen=True, slots=True)
class ReflexDecision:
    """Fast-path local decision output: sprite switch + transient reaction bark (no TTS)."""

    act: bool = False
    sprite: int | None = None
    bark: str = ""
    expression: str = ""
    sprite_id: int | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ReflexDecision":
        if not isinstance(raw, Mapping):
            return cls()
        raw_bark = raw.get("bark")
        bark = raw_bark.strip() if isinstance(raw_bark, str) else ""
        if len(bark) > 24:
            bark = bark[:23].rstrip() + "…"
        if "sprite_id" in raw:
            candidate = raw.get("sprite_id")
            if isinstance(candidate, str):
                digits = candidate.strip()
                if len(digits) <= 6 and digits.isascii() and digits.isdecimal():
                    candidate = int(digits)
            sprite_id = candidate if type(candidate) is int and candidate > 0 else None
            return cls(act=bool(bark or sprite_id is not None), bark=bark, sprite_id=sprite_id)

        act = bool(raw.get("act", False))
        raw_sprite = raw.get("sprite")
        sprite: int | None = None
        if raw_sprite is not None and not isinstance(raw_sprite, bool):
            try:
                val = int(raw_sprite)
                if val >= 0:
                    sprite = val
            except (TypeError, ValueError):
                sprite = None
        if not act:
            return cls(act=False, sprite=None, bark="")
        expression = str(raw.get("expression") or "").strip()[:24]
        return cls(act=bool(bark or sprite is not None or expression), sprite=sprite, bark=bark, expression=expression)


SCENE_MOODS = ("calm", "serious", "sad", "tense", "joyful", "hyped", "unclear")
VISUAL_CHANGES = ("none", "detail", "cut")


def normalize_scene_mood(raw: Any) -> str:
    value = str(raw or "").strip().casefold()
    if not value:
        return ""
    alias_map = {
        "neutral": "calm",
        "peaceful": "calm",
        "平静": "calm",
        "heavy": "serious",
        "solemn": "serious",
        "严肃": "serious",
        "沉重": "sad",
        "悲伤": "sad",
        "难过": "sad",
        "nervous": "tense",
        "紧张": "tense",
        "happy": "joyful",
        "funny": "joyful",
        "开心": "joyful",
        "轻松": "joyful",
        "excited": "hyped",
        "激动": "hyped",
        "高燃": "hyped",
    }
    mapped = alias_map.get(value, value)
    return mapped if mapped in SCENE_MOODS else "unclear"


def normalize_visual_change(raw: Any, *, has_digest: bool = True) -> str:
    value = str(raw or "").strip().casefold()
    alias_map = {
        "same": "none",
        "unchanged": "none",
        "static": "none",
        "无变化": "none",
        "action": "detail",
        "minor": "detail",
        "motion": "detail",
        "细节": "detail",
        "scene": "cut",
        "new": "cut",
        "switch": "cut",
        "切镜": "cut",
    }
    mapped = alias_map.get(value, value)
    if mapped in VISUAL_CHANGES:
        return mapped
    return "cut" if has_digest else "none"


@dataclass(frozen=True, slots=True)
class PerceptionDigestResult:
    """Complete structured decision produced by the local perception model."""

    reflex: ReflexDecision = field(default_factory=ReflexDecision)
    salience: float = 0.0
    player_busy: bool = False
    digest: str = ""
    game: str = ""
    latency_ms: float = 0.0
    created_at: float = field(default_factory=time.time)
    ocr_text: str = ""
    mood: str = ""
    visual_change: str = ""
    screen_text: str = ""


@dataclass(slots=True)
class VisualBeat:
    """One distinct visual observation beat in the working Vision Memory window."""

    seq: int
    timestamp: float
    kind: str
    summary: str
    salience: float = 0.0


@dataclass(slots=True)
class SubtitleItem:
    """One deduplicated subtitle / dialogue line ordered chronologically."""

    seq: int
    timestamp: float
    text: str


@dataclass(frozen=True, slots=True)
class VisionEpisode:
    """Archived episodic chapter covering an older slice of shared viewing / gameplay."""

    index: int
    start_ts: float
    end_ts: float
    summary: str
    mood: str = "unclear"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "startTs": self.start_ts,
            "endTs": self.end_ts,
            "summary": self.summary,
            "mood": self.mood,
        }


@dataclass(slots=True)
class CachedPerceptionEvent:
    """Salient digested milestone stored in Tier-1 RPInputCache."""

    summary: str
    salience: float
    game: str = ""
    timestamp: float = field(default_factory=time.time)
    consumed: bool = False
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "salience": round(self.salience, 3),
            "game": self.game,
            "timestamp": self.timestamp,
            "consumed": self.consumed,
        }
