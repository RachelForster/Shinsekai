"""Gatekeeper policy controlling when digested perception triggers the main RP LLM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading
import time
from typing import Literal

from core.perception.cache import PROACTIVE_EVENT_MAX_AGE_SEC, RPInputCache
from core.perception.models import PerceptionConfig


ScreenPlaybackAudio = Literal["unavailable", "playing", "quiet", "stopped"]
URGENT_SCREEN_SALIENCE = 0.95


@dataclass(frozen=True, slots=True)
class GatekeeperVerdict:
    """Result of evaluating whether to fire a proactive main-RP turn."""

    allow: bool
    reason: str
    salience: float = 0.0
    scene: str = "auto"


class PerceptionGatekeeper:
    """Decide when `RPInputCache` warrants an unsolicited main RP LLM turn."""

    def __init__(
        self,
        *,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._monotonic = monotonic_fn
        self._lock = threading.RLock()
        self._last_proactive_at: float = 0.0
        self._last_conversation_activity_at: float = 0.0
        self._last_user_activity_at: float = 0.0
        self._unanswered_proactive_count: int = 0
        self._last_observed_scene: str = "auto"

    def reset(self) -> None:
        """Clear cooldown and conversational engagement tracking."""
        with self._lock:
            self._last_proactive_at = 0.0
            self._last_conversation_activity_at = 0.0
            self._last_user_activity_at = 0.0
            self._unanswered_proactive_count = 0
            self._last_observed_scene = "auto"

    def notify_conversation_activity(self, *, from_user: bool = False) -> None:
        """Record that a real user or assistant message occurred."""
        now = self._monotonic()
        with self._lock:
            self._last_conversation_activity_at = now
            if from_user:
                self._last_user_activity_at = now
                self._unanswered_proactive_count = 0

    def notify_proactive_fired(self) -> None:
        """Record that a proactive perception turn was admitted."""
        now = self._monotonic()
        with self._lock:
            self._last_proactive_at = now
            self._last_conversation_activity_at = now
            self._unanswered_proactive_count += 1

    def engagement_state(self, *, now: float | None = None) -> tuple[int, float | None]:
        """Return `(unanswered_proactive_count, seconds_since_user_reply)`."""
        mono = self._monotonic() if now is None else float(now)
        with self._lock:
            since_user = (
                max(0.0, mono - self._last_user_activity_at)
                if self._last_user_activity_at > 0.0
                else None
            )
            return self._unanswered_proactive_count, since_user

    def evaluate(
        self,
        cache: RPInputCache,
        config: PerceptionConfig,
        *,
        chat_busy: bool = False,
        screen_audio: ScreenPlaybackAudio | None = None,
    ) -> GatekeeperVerdict:
        """Return whether `cache` should trigger a proactive RP turn right now."""
        if not config.enabled:
            return GatekeeperVerdict(False, "perception_disabled")
        if not config.proactive_enabled:
            return GatekeeperVerdict(False, "proactive_disabled")
        if chat_busy:
            return GatekeeperVerdict(False, "chat_busy")
        if not cache.has_context():
            return GatekeeperVerdict(False, "empty_cache")

        now = self._monotonic()
        unanswered, since_user = self.engagement_state(now=now)
        pacing = cache.adaptive_pacing(
            config,
            unanswered_proactive_count=unanswered,
            seconds_since_user_reply=since_user,
        )
        if pacing.scene != "auto":
            with self._lock:
                if (
                    self._last_observed_scene != "auto"
                    and pacing.scene != self._last_observed_scene
                    and pacing.scene != "idle"
                    and self._unanswered_proactive_count > 0
                ):
                    self._unanswered_proactive_count = max(0, self._unanswered_proactive_count - 1)
                    unanswered = self._unanswered_proactive_count
                    pacing = cache.adaptive_pacing(
                        config,
                        unanswered_proactive_count=unanswered,
                        seconds_since_user_reply=since_user,
                    )
                self._last_observed_scene = pacing.scene

        event_max_age = max(PROACTIVE_EVENT_MAX_AGE_SEC, pacing.pending_event_max_age_sec)
        effective_salience = cache.pending_salience(max_age_sec=event_max_age)
        urgent = effective_salience >= URGENT_SCREEN_SALIENCE
        if cache.player_busy and not urgent:
            # Avoid interrupting high-APM combat with full TTS dialogue unless critical (>=0.95)
            return GatekeeperVerdict(
                False,
                "player_busy",
                salience=cache.latest_salience,
                scene=pacing.scene,
            )

        playback_stopped = screen_audio == "stopped" and cache.has_recent_pending_observations(
            max_age_sec=event_max_age
        )
        if screen_audio == "playing" and not urgent and not playback_stopped:
            return GatekeeperVerdict(
                False,
                "waiting_for_screen_audio_gap",
                salience=effective_salience,
                scene=pacing.scene,
            )
        if screen_audio == "unavailable" and not urgent and not playback_stopped:
            if not pacing.allow_without_audio:
                return GatekeeperVerdict(
                    False,
                    "waiting_for_screen_audio_gap",
                    salience=effective_salience,
                    scene=pacing.scene,
                )
            since_sub = cache.seconds_since_last_subtitle()
            if (
                pacing.require_subtitle_lull_without_audio_sec > 0.0
                and since_sub is not None
                and since_sub < pacing.require_subtitle_lull_without_audio_sec
            ):
                return GatekeeperVerdict(
                    False,
                    "waiting_for_subtitle_gap",
                    salience=effective_salience,
                    scene=pacing.scene,
                )

        threshold = pacing.proactive_salience_threshold
        if (pacing.scene == "video_call" or not playback_stopped) and (
            effective_salience <= 0.0 or effective_salience < threshold
        ):
            return GatekeeperVerdict(
                False,
                "below_salience_threshold",
                salience=effective_salience,
                scene=pacing.scene,
            )

        if urgent or playback_stopped:
            cooldown_sec = config.proactive_cooldown_sec
            if playback_stopped and unanswered >= 3:
                cooldown_sec = min(600.0, cooldown_sec * 1.5)
        else:
            cooldown_sec = pacing.proactive_cooldown_sec
            if screen_audio == "quiet":
                cooldown_sec = max(cooldown_sec, pacing.quiet_audio_min_interval_sec)
            elif (
                screen_audio == "unavailable"
                and not pacing.recent_highlight
                and not pacing.post_combat_breather
            ):
                cooldown_sec = min(600.0, cooldown_sec * 1.2)

        with self._lock:
            if (
                self._last_proactive_at > 0.0
                and (now - self._last_proactive_at) < cooldown_sec
            ):
                return GatekeeperVerdict(
                    False,
                    "proactive_cooldown",
                    salience=effective_salience,
                    scene=pacing.scene,
                )
            # Small grace window (3.0s) right after user/assistant activity so turns don't collide
            if (
                self._last_conversation_activity_at > 0.0
                and (now - self._last_conversation_activity_at) < 3.0
            ):
                return GatekeeperVerdict(
                    False,
                    "recent_turn_grace",
                    salience=effective_salience,
                    scene=pacing.scene,
                )

        if playback_stopped:
            return GatekeeperVerdict(True, "playback_stopped", salience=effective_salience, scene=pacing.scene)
        if urgent and screen_audio is not None:
            return GatekeeperVerdict(True, "urgent_screen", salience=effective_salience, scene=pacing.scene)
        if pacing.post_combat_breather and not urgent:
            return GatekeeperVerdict(True, "post_combat_breather", salience=effective_salience, scene=pacing.scene)
        if pacing.recent_highlight and not urgent and screen_audio != "quiet":
            return GatekeeperVerdict(True, "highlight_focus", salience=effective_salience, scene=pacing.scene)
        if screen_audio is not None:
            reason = "quiet_screen" if screen_audio == "quiet" else "adaptive_screen"
            return GatekeeperVerdict(True, reason, salience=effective_salience, scene=pacing.scene)
        return GatekeeperVerdict(True, "admitted", salience=effective_salience, scene=pacing.scene)
