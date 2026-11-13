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

    def notify_conversation_activity(self) -> None:
        """Record that a real user or assistant message occurred."""
        with self._lock:
            self._last_conversation_activity_at = self._monotonic()

    def notify_proactive_fired(self) -> None:
        """Record that a proactive perception turn was admitted."""
        now = self._monotonic()
        with self._lock:
            self._last_proactive_at = now
            self._last_conversation_activity_at = now

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
        effective_salience = cache.pending_salience(max_age_sec=PROACTIVE_EVENT_MAX_AGE_SEC)
        urgent = effective_salience >= URGENT_SCREEN_SALIENCE
        if cache.player_busy and not urgent:
            # Avoid interrupting high-APM combat with full TTS dialogue unless critical (>=0.95)
            return GatekeeperVerdict(False, "player_busy", salience=cache.latest_salience)

        playback_stopped = screen_audio == "stopped" and cache.has_recent_pending_observations()
        if screen_audio is not None and not urgent and screen_audio != "quiet" and not playback_stopped:
            return GatekeeperVerdict(False, "waiting_for_screen_audio_gap", salience=effective_salience)

        if not playback_stopped and (effective_salience <= 0.0 or effective_salience < config.salience_threshold):
            return GatekeeperVerdict(
                False,
                "below_salience_threshold",
                salience=effective_salience,
            )

        cooldown_sec = config.proactive_cooldown_sec
        if screen_audio == "quiet" and not urgent:
            cooldown_sec = max(cooldown_sec, cache.policy.quiet_screen_min_reply_interval_sec)
        now = self._monotonic()
        with self._lock:
            if (
                self._last_proactive_at > 0.0
                and (now - self._last_proactive_at) < cooldown_sec
            ):
                return GatekeeperVerdict(
                    False,
                    "proactive_cooldown",
                    salience=effective_salience,
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
                )

        if playback_stopped:
            return GatekeeperVerdict(True, "playback_stopped", salience=effective_salience)
        if screen_audio is not None:
            reason = "urgent_screen" if urgent else "quiet_screen"
            return GatekeeperVerdict(True, reason, salience=effective_salience)
        return GatekeeperVerdict(True, "admitted", salience=effective_salience)
