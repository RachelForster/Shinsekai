"""Scene recognition and adaptive speaking/reaction pacing for real-time perception."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from config.perception import DEFAULT_SALIENCE_THRESHOLD
from core.perception.models import (
    PerceptionConfig,
    SceneType,
    normalize_scene_mood,
    normalize_scene_type,
)
from core.perception.policy import PerceptionMemoryPolicy

DEFAULT_PENDING_EVENT_MAX_AGE_SEC = 8.0
POST_COMBAT_BREATHER_WINDOW_SEC = 14.0
RECENT_HIGHLIGHT_WINDOW_SEC = 15.0
RECENT_CURSOR_WINDOW_SEC = 18.0
STATIC_IDLE_THRESHOLD_SEC = 25.0
WARM_RAPPORT_WINDOW_SEC = 90.0
TURN_GRACE_SEC = 3.0


@dataclass(frozen=True, slots=True)
class SceneActivitySignals:
    """Multi-modal temporal signals fused to identify the current activity scene."""

    explicit_scene: str = ""
    cloud_scene: str = "auto"
    scene_pace: str = "auto"
    mood: str = "unclear"
    player_busy: bool = False
    post_combat_breather_sec: float | None = None
    combat_peak_salience: float = 0.0
    active_game: str = ""
    subtitle_count_30s: int = 0
    seconds_since_last_subtitle: float | None = None
    seconds_since_last_highlight: float | None = None
    seconds_since_last_cursor: float | None = None
    visual_cuts_30s: int = 0
    static_duration_sec: float = 0.0
    unanswered_proactive_count: int = 0
    seconds_since_user_reply: float | None = None


@dataclass(frozen=True, slots=True)
class AdaptivePacingProfile:
    """Resolved scene and dynamically scaled thresholds/cooldowns for both channels."""

    scene: SceneType = "auto"
    post_combat_breather: bool = False
    recent_highlight: bool = False
    proactive_salience_threshold: float = DEFAULT_SALIENCE_THRESHOLD
    proactive_cooldown_sec: float = 25.0
    quiet_audio_min_interval_sec: float = 120.0
    pending_event_max_age_sec: float = DEFAULT_PENDING_EVENT_MAX_AGE_SEC
    allow_without_audio: bool = False
    require_subtitle_lull_without_audio_sec: float = 0.0
    reflex_cooldown_sec: float = 15.0
    ambient_reflex_cooldown_sec: float = 15.0
    allow_ambient_reflex: bool = True
    unanswered_backoff_factor: float = 1.0
    rapport_boost_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "postCombatBreather": self.post_combat_breather,
            "recentHighlight": self.recent_highlight,
            "proactiveSalienceThreshold": round(self.proactive_salience_threshold, 3),
            "proactiveCooldownSec": round(self.proactive_cooldown_sec, 1),
            "quietAudioMinIntervalSec": round(self.quiet_audio_min_interval_sec, 1),
            "pendingEventMaxAgeSec": round(self.pending_event_max_age_sec, 1),
            "allowWithoutAudio": self.allow_without_audio,
            "reflexCooldownSec": round(self.reflex_cooldown_sec, 1),
            "ambientReflexCooldownSec": round(self.ambient_reflex_cooldown_sec, 1),
            "allowAmbientReflex": self.allow_ambient_reflex,
            "unansweredBackoffFactor": round(self.unanswered_backoff_factor, 2),
            "rapportBoostActive": self.rapport_boost_active,
        }


def majority_scene_vote(
    votes: Sequence[tuple[float, str]],
    *,
    now: float,
    window_sec: float = 20.0,
) -> str:
    """Return recency-weighted scene consensus across recent VLM decisions."""
    cutoff = now - max(2.0, window_sec)
    recent = [
        (ts, norm)
        for ts, raw in votes
        if ts >= cutoff and (norm := normalize_scene_type(raw)) and norm != "auto"
    ]
    if not recent:
        return ""
    weights: Counter[str] = Counter()
    for idx, (_ts, scene_label) in enumerate(recent):
        weight = 1.6 if idx == len(recent) - 1 else 1.0
        weights[scene_label] += weight
    best_scene, _score = max(
        weights.items(),
        key=lambda item: (item[1], item[0] == recent[-1][1]),
    )
    return best_scene


def resolve_effective_scene(signals: SceneActivitySignals) -> SceneType:
    """Fuse VLM scene tags, OCR/cursor density, combat state, stillness, and Cloud guidance."""
    mood = normalize_scene_mood(signals.mood) or "unclear"
    explicit = normalize_scene_type(signals.explicit_scene)
    cloud = normalize_scene_type(signals.cloud_scene) or "auto"
    pace = str(signals.scene_pace or "auto").strip().lower()

    if signals.player_busy:
        return "combat"

    if (
        signals.post_combat_breather_sec is not None
        and 0.0 <= signals.post_combat_breather_sec <= POST_COMBAT_BREATHER_WINDOW_SEC
    ):
        return "combat"

    recent_hl = (
        signals.seconds_since_last_highlight is not None
        and 0.0 <= signals.seconds_since_last_highlight <= 20.0
    )
    recent_cur = (
        signals.seconds_since_last_cursor is not None
        and 0.0 <= signals.seconds_since_last_cursor <= RECENT_CURSOR_WINDOW_SEC
    )
    recent_sub = (
        signals.seconds_since_last_subtitle is not None
        and 0.0 <= signals.seconds_since_last_subtitle <= 15.0
    )

    if signals.static_duration_sec >= STATIC_IDLE_THRESHOLD_SEC and not recent_hl and not recent_sub:
        return "idle"
    if explicit == "idle" and signals.static_duration_sec >= 8.0 and not recent_hl and not recent_sub:
        return "idle"

    if recent_hl and signals.subtitle_count_30s < 3 and not signals.active_game:
        return "reading_work"
    if recent_cur and signals.subtitle_count_30s == 0 and not signals.active_game:
        return "reading_work"
    if explicit == "reading_work":
        return "reading_work"

    if explicit in {"story_media", "casual_media", "combat", "exploration"}:
        if explicit == "casual_media" and mood in {"sad", "serious"} and signals.subtitle_count_30s >= 4:
            return "story_media"
        return explicit  # type: ignore[return-value]

    if signals.active_game:
        if mood in {"tense", "hyped"} and signals.visual_cuts_30s >= 3:
            return "combat"
        if (
            signals.visual_cuts_30s >= 2
            or cloud in {"exploration", "combat"}
            or pace == "action_heavy"
        ):
            return "exploration"

    if signals.subtitle_count_30s >= 4:
        if mood in {"serious", "sad", "tense"} or pace == "dialogue_heavy":
            return "story_media"
        return "casual_media"

    if cloud != "auto":
        return cloud  # type: ignore[return-value]

    if pace == "dialogue_heavy":
        return "story_media" if mood in {"serious", "sad", "tense"} else "casual_media"
    if pace == "action_heavy":
        return "exploration"
    if pace == "quiet":
        return "idle" if signals.static_duration_sec >= 15.0 else "reading_work"

    return "auto"


def _unanswered_backoff(count: int) -> tuple[float, float]:
    """Return `(cooldown_multiplier, salience_increment)` when proactive turns go unanswered."""
    if count <= 1:
        return 1.0, 0.0
    if count == 2:
        return 1.45, 0.03
    if count == 3:
        return 2.0, 0.06
    extra = min(3.2, 2.0 + 0.5 * (count - 3))
    return extra, 0.09


def compute_adaptive_pacing(
    signals: SceneActivitySignals,
    config: PerceptionConfig,
    policy: PerceptionMemoryPolicy | None = None,
) -> AdaptivePacingProfile:
    """Compute scene-adaptive proactive and reflex thresholds/cooldowns around user baselines."""
    effective_policy = policy or PerceptionMemoryPolicy()
    scene = resolve_effective_scene(signals)
    mood = normalize_scene_mood(signals.mood) or "unclear"

    post_combat_breather = (
        not signals.player_busy
        and signals.post_combat_breather_sec is not None
        and 0.0 <= signals.post_combat_breather_sec <= POST_COMBAT_BREATHER_WINDOW_SEC
    )
    recent_highlight = (
        signals.seconds_since_last_highlight is not None
        and 0.0 <= signals.seconds_since_last_highlight <= RECENT_HIGHLIGHT_WINDOW_SEC
    )

    cloud_delta = 0.0
    if abs(effective_policy.proactive_salience_threshold - DEFAULT_SALIENCE_THRESHOLD) >= 0.005:
        cloud_delta = max(
            -0.08,
            min(0.08, (effective_policy.proactive_salience_threshold - DEFAULT_SALIENCE_THRESHOLD) * 0.5),
        )
    base_salience = config.salience_threshold + cloud_delta
    base_proactive_cd = config.proactive_cooldown_sec
    base_quiet_cd = effective_policy.quiet_screen_min_reply_interval_sec
    base_reflex_cd = config.reflex_cooldown_sec

    salience_delta = 0.0
    proactive_cd_mult = 1.0
    quiet_cd_mult = 1.0
    event_max_age = DEFAULT_PENDING_EVENT_MAX_AGE_SEC
    allow_without_audio = recent_highlight
    subtitle_lull_sec = 0.0
    reflex_cd_mult = 1.0
    ambient_reflex_mult = 1.0
    allow_ambient = True

    if scene == "story_media":
        heavy_mood = mood in {"sad", "serious"}
        salience_delta = 0.03 if heavy_mood else 0.01
        proactive_cd_mult = 1.65 if heavy_mood else 1.45
        quiet_cd_mult = 1.0 if heavy_mood else 0.85
        event_max_age = 22.0
        allow_without_audio = True
        subtitle_lull_sec = 3.5
        reflex_cd_mult = 1.35
        ambient_reflex_mult = 1.85
        allow_ambient = True
    elif scene == "casual_media":
        lively_mood = mood in {"joyful", "hyped"}
        salience_delta = -0.17 if lively_mood else -0.15
        proactive_cd_mult = 0.80
        quiet_cd_mult = 0.38
        event_max_age = 16.0
        allow_without_audio = True
        subtitle_lull_sec = 2.6
        reflex_cd_mult = 0.78
        ambient_reflex_mult = 1.60
        allow_ambient = True
    elif scene == "combat":
        if post_combat_breather:
            salience_delta = -0.18
            proactive_cd_mult = 0.70
            quiet_cd_mult = 0.30
            event_max_age = 16.0
            allow_without_audio = True
            subtitle_lull_sec = 0.0
            reflex_cd_mult = 0.80
            ambient_reflex_mult = 1.50
            allow_ambient = False
        else:
            salience_delta = 0.0
            proactive_cd_mult = 1.0
            quiet_cd_mult = 0.50
            event_max_age = 16.0
            allow_without_audio = True
            subtitle_lull_sec = 0.0
            reflex_cd_mult = 0.65
            ambient_reflex_mult = 2.0
            allow_ambient = False
    elif scene == "exploration":
        salience_delta = -0.12
        proactive_cd_mult = 0.92
        quiet_cd_mult = 0.42
        event_max_age = 14.0
        allow_without_audio = True
        subtitle_lull_sec = 1.5
        reflex_cd_mult = 0.90
        ambient_reflex_mult = 1.40
        allow_ambient = True
    elif scene == "reading_work":
        if recent_highlight:
            salience_delta = -0.22
            proactive_cd_mult = 0.90
            quiet_cd_mult = 0.45
        else:
            salience_delta = -0.05
            proactive_cd_mult = 1.80
            quiet_cd_mult = 0.75
        event_max_age = 15.0
        allow_without_audio = True
        subtitle_lull_sec = 0.0
        reflex_cd_mult = 1.55
        ambient_reflex_mult = 2.40
        allow_ambient = True
    elif scene == "idle":
        idle_extra = min(2.0, max(0.0, (signals.static_duration_sec - STATIC_IDLE_THRESHOLD_SEC) / 45.0))
        salience_delta = 0.07
        proactive_cd_mult = 2.40 + idle_extra
        quiet_cd_mult = 1.50 + idle_extra * 0.5
        event_max_age = 10.0
        allow_without_audio = False
        subtitle_lull_sec = 0.0
        reflex_cd_mult = 2.20
        ambient_reflex_mult = 3.0
        allow_ambient = False

    backoff_factor, backoff_salience_add = _unanswered_backoff(signals.unanswered_proactive_count)

    rapport_boost = (
        signals.unanswered_proactive_count == 0
        and signals.seconds_since_user_reply is not None
        and TURN_GRACE_SEC <= signals.seconds_since_user_reply <= WARM_RAPPORT_WINDOW_SEC
    )
    rapport_cd_mult = 0.78 if rapport_boost else 1.0
    rapport_quiet_mult = 0.65 if rapport_boost else 1.0
    rapport_salience_delta = -0.04 if rapport_boost else 0.0

    min_salience = min(0.35, config.salience_threshold)
    max_salience = max(0.94, config.salience_threshold)
    effective_salience = max(
        min_salience,
        min(
            max_salience,
            base_salience + salience_delta + backoff_salience_add + rapport_salience_delta,
        ),
    )

    effective_proactive_cd = max(
        3.0,
        min(600.0, base_proactive_cd * proactive_cd_mult * backoff_factor * rapport_cd_mult),
    )
    effective_quiet_cd = max(
        effective_proactive_cd,
        min(
            600.0,
            base_quiet_cd * quiet_cd_mult * backoff_factor * rapport_quiet_mult,
        ),
    )

    reflex_backoff = 1.0 + max(0.0, backoff_factor - 1.0) * 0.35 if signals.unanswered_proactive_count >= 3 else 1.0
    effective_reflex_cd = max(0.5, min(120.0, base_reflex_cd * reflex_cd_mult * reflex_backoff))
    effective_ambient_cd = max(
        effective_reflex_cd,
        min(180.0, base_reflex_cd * ambient_reflex_mult * reflex_backoff),
    )

    return AdaptivePacingProfile(
        scene=scene,
        post_combat_breather=post_combat_breather,
        recent_highlight=recent_highlight,
        proactive_salience_threshold=effective_salience,
        proactive_cooldown_sec=effective_proactive_cd,
        quiet_audio_min_interval_sec=effective_quiet_cd,
        pending_event_max_age_sec=event_max_age,
        allow_without_audio=allow_without_audio,
        require_subtitle_lull_without_audio_sec=subtitle_lull_sec,
        reflex_cooldown_sec=effective_reflex_cd,
        ambient_reflex_cooldown_sec=effective_ambient_cd,
        allow_ambient_reflex=allow_ambient,
        unanswered_backoff_factor=backoff_factor,
        rapport_boost_active=rapport_boost,
    )


def proactive_scene_delivery_hint(profile: AdaptivePacingProfile) -> str:
    """Return a concise delivery-posture hint for proactive main-RP turns when scene is known."""
    if profile.post_combat_breather:
        return "- 表达节奏：激烈操作刚告一段落，可顺势简短点评或关心一句刚才的交锋。"
    if profile.scene == "story_media":
        return "- 表达节奏：当前处于剧情沉浸阶段，简短轻声回应一句即可，避免剧透或长篇大论。"
    if profile.scene == "casual_media":
        return "- 表达节奏：当前内容轻松日常，可用自然口语简短吐槽或搭话一两句。"
    if profile.scene == "exploration":
        return "- 表达节奏：当前正在探索或整备，自然随口聊一两句眼前的发现即可。"
    if profile.scene == "reading_work":
        if profile.recent_highlight:
            return "- 表达节奏：用户刚划选了重点内容，围绕所选文字简短回应一两句即可。"
        return "- 表达节奏：用户正在阅读或处理内容，保持安静陪伴感，简短点到关键处即可。"
    return ""


__all__ = [
    "AdaptivePacingProfile",
    "DEFAULT_PENDING_EVENT_MAX_AGE_SEC",
    "POST_COMBAT_BREATHER_WINDOW_SEC",
    "RECENT_HIGHLIGHT_WINDOW_SEC",
    "SceneActivitySignals",
    "compute_adaptive_pacing",
    "majority_scene_vote",
    "proactive_scene_delivery_hint",
    "resolve_effective_scene",
]
