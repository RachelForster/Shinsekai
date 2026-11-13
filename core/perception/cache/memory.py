"""Session Vision Memory (`RPInputCache`) coordinating tracks, dual episodes, policy, and watermarks."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import replace
import threading
import time
from typing import Any

from core.perception.cache.episodes import EpisodeArchive
from core.perception.cache.formatter import (
    PROACTIVE_EVENT_MAX_AGE_SEC,
    render_rp_context,
)
from core.perception.cache.tracks import (
    SubtitleTrack,
    VisualTrack,
    clean_visual_summary,
    is_ambient_reaction_bark,
    observation_key,
    text_source_label,
)
from core.perception.models import (
    CachedPerceptionEvent,
    PerceptionDigestResult,
    ReflexDecision,
    TextObservationSource,
    VisionEpisode,
    normalize_scene_mood,
    normalize_visual_change,
)
from core.perception.policy import PerceptionMemoryPolicy


class RPInputCache:
    """Thread-safe Tier-1 Vision Memory with adaptive policy, dual-stage summaries, and `seq` watermarks."""

    def __init__(
        self,
        *,
        policy: PerceptionMemoryPolicy | None = None,
        max_recent_digests: int | None = None,
        max_subtitles: int | None = None,
        max_episodes: int | None = None,
        archive_batch_size: int | None = None,
        max_notable_events: int | None = None,
        notable_salience_floor: float | None = None,
    ) -> None:
        self._lock = threading.RLock()
        effective_policy = policy if policy is not None else PerceptionMemoryPolicy()
        if max_recent_digests is not None:
            effective_policy.max_visual_track_beats = max(2, int(max_recent_digests))
        if max_subtitles is not None:
            effective_policy.max_subtitle_track_items = max(4, int(max_subtitles))
        if max_episodes is not None:
            effective_policy.max_archived_episodes = max(2, int(max_episodes))
        if archive_batch_size is not None:
            effective_policy.archive_batch_size = max(4, int(archive_batch_size))
        if max_notable_events is not None:
            effective_policy.max_notable_events = max(4, int(max_notable_events))
        if notable_salience_floor is not None:
            effective_policy.notable_salience_floor = max(
                0.1, min(1.0, float(notable_salience_floor))
            )
        effective_policy._baseline = effective_policy.to_dict()
        self.policy: PerceptionMemoryPolicy = effective_policy

        self._visual = VisualTrack(max_beats=self.policy.max_visual_track_beats)
        self._subtitles = SubtitleTrack(max_items=self.policy.max_subtitle_track_items)
        self._episodes = EpisodeArchive(
            max_episodes=self.policy.max_archived_episodes,
            batch_size=self.policy.archive_batch_size,
        )
        self._max_notable_events = self.policy.max_notable_events

        self._next_seq: int = 0
        self._consumed_seq: int = 0
        self._frozen_turns: OrderedDict[str, str] = OrderedDict()

        self._current_mood: str = "unclear"
        self._current_mood_at: float = 0.0
        self._notable_events: deque[CachedPerceptionEvent] = deque(maxlen=self._max_notable_events)
        self._latest_salience: float = 0.0
        self._player_busy: bool = False
        self._active_game: str = ""
        self._last_reflex: ReflexDecision | None = None
        self._updated_at: float = 0.0
        self._last_latency_ms: float = 0.0
        self._digest_count: int = 0

    def _alloc_seq(self) -> int:
        self._next_seq += 1
        return self._next_seq

    def apply_cloud_guidance(self, guidance: Mapping[str, Any] | None) -> dict[str, Any]:
        """Thread-safely apply adaptive parameter adjustments from the Cloud LLM."""
        with self._lock:
            return self.policy.apply_cloud_guidance(guidance)

    def record_screen_text(
        self,
        text: str,
        *,
        captured_at: float,
        source: TextObservationSource = "subtitle",
    ) -> bool:
        with self._lock:
            changed = self._subtitles.record_text(
                text,
                captured_at=captured_at,
                alloc_seq=self._alloc_seq,
                on_evict=self._episodes.stage,
                source=source,
            )
            if str(text or "").strip():
                self._updated_at = max(self._updated_at, captured_at)
            return changed

    def record_highlighted_text(self, text: str, *, captured_at: float | None = None) -> bool:
        ts = time.time() if captured_at is None else float(captured_at)
        return self.record_screen_text(text, captured_at=ts, source="highlight")

    def record_cursor_text(self, text: str, *, captured_at: float | None = None) -> bool:
        ts = time.time() if captured_at is None else float(captured_at)
        return self.record_screen_text(text, captured_at=ts, source="cursor")

    def record_decision(
        self,
        result: PerceptionDigestResult,
        *,
        proactive_threshold: float | None = None,
    ) -> None:
        raw_digest = str(result.digest or "").strip()
        salience = max(0.0, min(1.0, float(result.salience or 0.0)))
        now = float(result.created_at or time.time())
        mood = normalize_scene_mood(result.mood)
        visual_change = normalize_visual_change(result.visual_change, has_digest=bool(raw_digest))

        with self._lock:
            self._latest_salience = salience
            self._player_busy = bool(result.player_busy)
            if result.game:
                self._active_game = str(result.game).strip()[:64]
            if mood and mood != "unclear":
                self._current_mood = mood
                self._current_mood_at = now
            elif self._current_mood_at > 0 and now - self._current_mood_at > 25.0:
                self._current_mood = "unclear"

            if result.reflex.act and not is_ambient_reaction_bark(result.reflex.bark):
                self._last_reflex = result.reflex
            elif result.reflex.act and self._last_reflex is None:
                self._last_reflex = replace(result.reflex, bark="")

            self._updated_at = max(self._updated_at, now)
            self._last_latency_ms = float(result.latency_ms or 0.0)
            self._digest_count += 1

            # Subtitles come strictly from OCR (`result.ocr_text` or `record_screen_text`), never Qwen `screen_text`.
            if result.ocr_text:
                self.record_screen_text(result.ocr_text, captured_at=now)

            subtitle_keys = self._subtitles.subtitle_keys(recent=10)
            cleaned_visual = clean_visual_summary(raw_digest, subtitle_keys) if raw_digest else ""
            self._visual.record_visual(
                cleaned_visual,
                visual_change=visual_change,
                salience=salience,
                now=now,
                alloc_seq=self._alloc_seq,
                on_evict=self._episodes.stage,
            )

            floor = self.policy.notable_salience_floor
            if proactive_threshold is not None:
                floor = min(floor, proactive_threshold)
            if salience >= floor:
                event_summary = cleaned_visual
                if not event_summary:
                    unconsumed_sub = next(
                        (
                            item.text
                            for item in reversed(self._subtitles.items)
                            if item.seq > self._consumed_seq
                        ),
                        "",
                    )
                    event_summary = unconsumed_sub or raw_digest or self._visual.scene_anchor
                if event_summary and (
                    not self._notable_events
                    or observation_key(self._notable_events[-1].summary) != observation_key(event_summary)
                ):
                    self._notable_events.append(
                        CachedPerceptionEvent(
                            summary=event_summary,
                            salience=salience,
                            game=self._active_game,
                            timestamp=now,
                            consumed=False,
                            seq=self._alloc_seq(),
                        )
                    )

    @property
    def current_digest(self) -> str:
        with self._lock:
            return self._visual.current_digest or self._visual.scene_anchor

    @property
    def scene_anchor(self) -> str:
        with self._lock:
            return self._visual.scene_anchor

    @property
    def current_mood(self) -> str:
        with self._lock:
            return self._current_mood

    @property
    def overall_summary(self) -> str:
        with self._lock:
            return self._episodes.overall_summary

    @property
    def episodes(self) -> list[VisionEpisode]:
        with self._lock:
            return list(self._episodes.episodes)

    def recent_subtitles(self, *, limit: int = 4, max_age_sec: float = 45.0) -> list[str]:
        with self._lock:
            return self._subtitles.recent_lines(now=time.time(), limit=limit, max_age_sec=max_age_sec)

    def sweep_expired_live_window(self, *, now: float | None = None) -> int:
        """Move beats and subtitles older than `policy.live_window_sec` into episodic staging."""
        ts = time.time() if now is None else float(now)
        with self._lock:
            cutoff = ts - self.policy.live_window_sec
            aged: list[tuple[float, str, str]] = []
            self._visual.evict_older_than(cutoff, lambda t, k, s: aged.append((t, k, s)))
            self._subtitles.evict_older_than(cutoff, lambda t, k, s: aged.append((t, k, s)))
            aged.sort(key=lambda item: item[0])
            for item_ts, kind, text in aged:
                self._episodes.stage(item_ts, kind, text)
            return len(aged)

    def prepare_summary_job(
        self,
        *,
        now: float | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        """Sweep aged-out live items and pop a due 2-minute summary job for the Cloud LLM."""
        ts = time.time() if now is None else float(now)
        with self._lock:
            self.sweep_expired_live_window(now=ts)
            batch = self._episodes.pop_due_batch(
                now=ts,
                interval_sec=self.policy.minute_summary_interval_sec,
                min_items=self.policy.min_items_per_summary,
                force=force,
            )
            if not batch:
                return None
            return {
                "batch": batch,
                "previous_overall_summary": self._episodes.overall_summary,
                "recent_episodes": list(self._episodes.episodes)[-3:],
                "policy_snapshot": self.policy.to_prompt_snapshot(),
                "minute_max_chars": self.policy.minute_summary_max_chars,
                "overall_max_chars": self.policy.overall_summary_max_chars,
                "active_game": self._active_game,
                "current_mood": self._current_mood,
            }

    def commit_summary_job(
        self,
        *,
        minute_summary: str,
        overall_summary: str,
        start_ts: float,
        end_ts: float,
        mood: str = "unclear",
        guidance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store dual-stage Cloud LLM summaries and apply any returned adaptive guidance."""
        with self._lock:
            self._episodes.record_dual_summary(
                minute_summary=minute_summary,
                overall_summary=overall_summary,
                start_ts=start_ts,
                end_ts=end_ts,
                mood=mood or self._current_mood,
                minute_max_chars=self.policy.minute_summary_max_chars,
                overall_max_chars=self.policy.overall_summary_max_chars,
                alloc_seq=self._alloc_seq,
            )
            return self.policy.apply_cloud_guidance(guidance)

    def needs_episode_compaction(self, *, min_items: int | None = None) -> bool:
        with self._lock:
            return self._episodes.needs_compaction(min_items=min_items)

    def pop_archive_batch(
        self,
        *,
        min_items: int | None = None,
        max_items: int = 20,
        force: bool = False,
    ) -> list[tuple[float, str, str]]:
        with self._lock:
            return self._episodes.pop_batch(min_items=min_items, max_items=max_items, force=force)

    def append_episode(
        self,
        summary: str,
        *,
        start_ts: float,
        end_ts: float,
        mood: str = "unclear",
        overall_summary: str | None = None,
    ) -> VisionEpisode | None:
        with self._lock:
            return self._episodes.append(
                summary,
                start_ts=start_ts,
                end_ts=end_ts,
                mood=mood,
                alloc_seq=self._alloc_seq,
                overall_summary=overall_summary,
                minute_max_chars=max(140, self.policy.minute_summary_max_chars),
                overall_max_chars=self.policy.overall_summary_max_chars,
            )

    @property
    def latest_salience(self) -> float:
        with self._lock:
            return self._latest_salience

    @property
    def unconsumed_peak_salience(self) -> float:
        return self.pending_salience()

    def pending_salience(self, *, max_age_sec: float = 0.0) -> float:
        with self._lock:
            cutoff = time.time() - max_age_sec if max_age_sec > 0 else 0.0
            return max(
                (
                    ev.salience
                    for ev in self._notable_events
                    if not ev.consumed and ev.seq > self._consumed_seq and ev.timestamp >= cutoff
                ),
                default=0.0,
            )

    @property
    def player_busy(self) -> bool:
        with self._lock:
            return self._player_busy

    def has_context(self) -> bool:
        with self._lock:
            return bool(
                self._episodes.overall_summary
                or self._episodes.episodes
                or self._visual.scene_anchor
                or self._visual.beats
                or self._subtitles.items
                or self._notable_events
            )

    def has_unconsumed_notable(self) -> bool:
        with self._lock:
            return any(
                not ev.consumed and ev.seq > self._consumed_seq for ev in self._notable_events
            )

    def mark_consumed(self, *, up_to_seq: int | None = None) -> None:
        with self._lock:
            target_seq = self._next_seq if up_to_seq is None else max(self._consumed_seq, int(up_to_seq))
            self._consumed_seq = target_seq
            for ev in self._notable_events:
                if ev.seq <= target_seq:
                    ev.consumed = True

    def format_for_rp_context(
        self,
        *,
        consume: bool = True,
        max_age_sec: float = 300.0,
        include_recent_events: bool = False,
        pending_only: bool = False,
    ) -> str:
        now = time.time()
        with self._lock:
            block, snapshot_seq = self._render_locked(
                now=now,
                max_age_sec=max_age_sec,
                include_recent_events=include_recent_events,
                pending_only=pending_only,
            )
            if consume and block and snapshot_seq > self._consumed_seq:
                self.mark_consumed(up_to_seq=snapshot_seq)
            return block

    def _render_locked(
        self,
        *,
        now: float,
        max_age_sec: float,
        include_recent_events: bool,
        pending_only: bool,
    ) -> tuple[str, int]:
        return render_rp_context(
            now=now,
            max_age_sec=max_age_sec,
            include_recent_events=include_recent_events,
            pending_only=pending_only,
            consumed_seq=self._consumed_seq,
            active_game=self._active_game,
            player_busy=self._player_busy,
            updated_at=self._updated_at,
            visual_track=self._visual,
            subtitle_track=self._subtitles,
            episode_archive=self._episodes,
            notable_events=tuple(self._notable_events),
            policy=self.policy,
        )

    def take_turn_context(
        self,
        *,
        turn_id: str = "",
        proactive: bool = False,
        salience_threshold: float = 0.0,
        allow_consumed_context: bool = False,
    ) -> str:
        clean_turn_id = str(turn_id or "").strip()
        with self._lock:
            if clean_turn_id and clean_turn_id in self._frozen_turns:
                return self._frozen_turns[clean_turn_id]

            now = time.time()
            if proactive:
                peak = self.pending_salience(max_age_sec=PROACTIVE_EVENT_MAX_AGE_SEC)
                if peak < salience_threshold:
                    return ""
                block, snapshot_seq = self._render_locked(
                    now=now,
                    max_age_sec=45.0 if salience_threshold else PROACTIVE_EVENT_MAX_AGE_SEC,
                    include_recent_events=False,
                    pending_only=True,
                )
            elif allow_consumed_context:
                block, snapshot_seq = self._render_locked(
                    now=now,
                    max_age_sec=self.policy.live_window_sec,
                    include_recent_events=True,
                    pending_only=False,
                )
            else:
                block, snapshot_seq = self._render_locked(
                    now=now,
                    max_age_sec=self.policy.live_window_sec,
                    include_recent_events=False,
                    pending_only=True,
                )

            if snapshot_seq > self._consumed_seq:
                self.mark_consumed(up_to_seq=snapshot_seq)
            if clean_turn_id:
                self._frozen_turns[clean_turn_id] = block
                while len(self._frozen_turns) > 12:
                    self._frozen_turns.popitem(last=False)
            return block

    def has_recent_pending_observations(self) -> bool:
        with self._lock:
            block, _ = self._render_locked(
                now=time.time(),
                max_age_sec=PROACTIVE_EVENT_MAX_AGE_SEC,
                include_recent_events=False,
                pending_only=True,
            )
            return bool(block)

    def format_proactive_trigger_prompt(self, *, consume: bool = True) -> str:
        context_block = self.format_for_rp_context(
            consume=consume,
            max_age_sec=PROACTIVE_EVENT_MAX_AGE_SEC,
            include_recent_events=False,
            pending_only=True,
        )
        if not context_block:
            return ""
        return (
            f"{context_block}\n\n"
            "[系统事件：玩家并未打字发言，但上述游戏/屏幕画面刚刚发生了值得你主动搭话的关键一幕。"
            "请以角色身份自然地主动说一两句话做出反应。]"
        )

    def clear(self) -> None:
        with self._lock:
            self._next_seq = 0
            self._consumed_seq = 0
            self._frozen_turns.clear()
            self._visual.clear()
            self._subtitles.clear()
            self._episodes.clear()
            self.policy.reset_adaptive()
            self._current_mood = "unclear"
            self._current_mood_at = 0.0
            self._notable_events.clear()
            self._latest_salience = 0.0
            self._player_busy = False
            self._active_game = ""
            self._last_reflex = None
            self._updated_at = 0.0
            self._last_latency_ms = 0.0
            self._digest_count = 0

    def archive_live_window_for_pause(self) -> None:
        with self._lock:
            self.mark_consumed()
            self._subtitles.reset_raw_tracking()

    def reset_working_window_preserving_episodes(self) -> None:
        with self._lock:
            merged = [
                *((beat.timestamp, "画面", beat.summary) for beat in self._visual.beats),
                *(
                    (sub.timestamp, text_source_label(sub.source), sub.text)
                    for sub in self._subtitles.items
                ),
            ]
            merged.sort(key=lambda item: item[0])
            for ts, kind, text in merged:
                self._episodes.stage(ts, kind, text)
            self._visual.clear()
            self._subtitles.clear()
            self._current_mood = "unclear"
            self._current_mood_at = 0.0
            self._notable_events.clear()
            self._frozen_turns.clear()
            self.mark_consumed()

    def clear_screen_text(self, *, preserve_highlights: bool = False) -> None:
        with self._lock:
            self._subtitles.clear(preserve_highlights=preserve_highlights)

    def to_status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "currentDigest": self.current_digest,
                "sceneAnchor": self._visual.scene_anchor,
                "currentMood": self._current_mood,
                "overallSummary": self._episodes.overall_summary,
                "latestSalience": round(self._latest_salience, 3),
                "unconsumedPeakSalience": round(
                    self.pending_salience(max_age_sec=PROACTIVE_EVENT_MAX_AGE_SEC), 3
                ),
                "playerBusy": self._player_busy,
                "activeGame": self._active_game,
                "episodeCount": len(self._episodes.episodes),
                "episodes": [ep.to_dict() for ep in list(self._episodes.episodes)[-4:]],
                "subtitleCount": len(self._subtitles.items),
                "policy": self.policy.to_dict(),
                "lastReflex": (
                    {
                        "act": self._last_reflex.act,
                        "sprite": self._last_reflex.sprite,
                        "bark": self._last_reflex.bark,
                    }
                    if self._last_reflex is not None
                    else None
                ),
                "notableEvents": [ev.to_dict() for ev in list(self._notable_events)[-6:]],
                "digestCount": self._digest_count,
                "lastLatencyMs": round(self._last_latency_ms, 1),
                "updatedAt": self._updated_at or None,
            }
