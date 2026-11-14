"""Runtime coordinator connecting raw ingestion, local VLM reflex/digest, and RP Gatekeeper."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import replace
import logging
import threading
import time
from typing import Any

from ai.perception.cloud_summary import CloudTextCompletionFn, summarize_vision_window
from ai.perception.decision_client import PerceptionDecisionClient, PerceptionInferenceError
from ai.perception.parser import InvalidPerceptionDecision
from application.perception.cursor_reader import (
    CursorObservation,
    CursorProbe,
    CursorReadingTracker,
)
from application.perception.expressions import (
    expression_sprite_candidates,
    sprite_prompt_choices,
)
from application.perception.reflex_policy import (
    ReflexPolicy,
    comparison_text,
    observation_bark,
    short_reading_focus,
)
from config.character_assets import get_character_assets
from core.perception.cache import (
    PROACTIVE_EVENT_MAX_AGE_SEC,
    PROACTIVE_TURN_INSTRUCTION,
    RPInputCache,
)
from core.perception.gatekeeper import (
    URGENT_SCREEN_SALIENCE,
    PerceptionGatekeeper,
    ScreenPlaybackAudio,
)
from core.perception.models import (
    PerceptionConfig,
    PerceptionFrame,
    ReflexDecision,
    ScreenOcrScope,
)
from core.perception.raw_buffer import PerceptionRawBuffer

logger = logging.getLogger(__name__)


class PerceptionCoordinator:
    """Orchestrate Tier-0 raw buffer -> local Qwen3-VL-2B -> fast reflex + Vision Memory."""

    def __init__(
        self,
        *,
        get_api_config: Callable[[], Any],
        resolve_character: Callable[[], Any | None],
        is_chat_busy: Callable[[], bool],
        apply_reflex: Callable[[str, int | None, str], None],
        enqueue_proactive_turn: Callable[[str], bool],
        publish_state: Callable[[dict[str, Any]], None] | None = None,
        notify_once: Callable[[str], None] | None = None,
        raw_buffer: PerceptionRawBuffer | None = None,
        rp_input_cache: RPInputCache | None = None,
        gatekeeper: PerceptionGatekeeper | None = None,
        decision_client: PerceptionDecisionClient | None = None,
        cloud_complete: CloudTextCompletionFn | None = None,
        cursor_probe: CursorProbe | None = None,
    ) -> None:
        self._get_api_config = get_api_config
        self._resolve_character = resolve_character
        self._is_chat_busy = is_chat_busy
        self._apply_reflex = apply_reflex
        self._enqueue_proactive_turn = enqueue_proactive_turn
        self._publish_state = publish_state or (lambda _state: None)
        self._notify_once = notify_once or (lambda _msg: None)
        self._cloud_complete = cloud_complete
        self._cursor_probe = cursor_probe
        self._cursor_tracker = CursorReadingTracker()

        self.raw_buffer = raw_buffer or PerceptionRawBuffer()
        self.rp_input_cache = rp_input_cache or RPInputCache()
        self.gatekeeper = gatekeeper or PerceptionGatekeeper()
        self.decision_client = decision_client or PerceptionDecisionClient()
        self._reflex_policy = ReflexPolicy()

        self._lock = threading.RLock()
        self._analysis_progress = threading.Condition(self._lock)
        self._processed_revision = 0
        self._analysis_epoch = 0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._ocr_wake_event = threading.Event()
        self._cursor_wake_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._ocr_worker: threading.Thread | None = None
        self._cursor_worker: threading.Thread | None = None
        self._summary_worker: threading.Thread | None = None

        self._screen_share_active = False
        self._screen_generation = 0
        self._screen_audio: ScreenPlaybackAudio = "unavailable"
        self._screen_audio_at = 0.0
        self._playback_stopped_at = 0.0
        self._ocr_scope_revision = 0
        self._latest_screen_frame: PerceptionFrame | None = None
        self._previous_vision_frame: PerceptionFrame | None = None
        self._latest_ocr: tuple[float, str] = (0.0, "")
        self._last_subtitle_monotonic: float = 0.0
        self._latest_highlight: tuple[float, str] = (0.0, "")
        self._latest_cursor_ocr: tuple[float, str] = (0.0, "")
        self._recent_screen_text: deque[tuple[float, str]] = deque(maxlen=2)
        self._last_vision_ocr_key = ""
        self._screen_digest = ""
        self._screen_digest_at = 0.0
        self._last_infer_monotonic = 0.0
        self._attempted_voice_styles: set[tuple[str, str]] = set()
        self._server_verified = False
        self._last_error = ""
        self._warned_unreachable = False

    def current_config(self) -> PerceptionConfig:
        return PerceptionConfig.from_api_config(self._get_api_config())

    def is_effectively_enabled(self) -> bool:
        with self._lock:
            share_active = self._screen_share_active
        return share_active or self.current_config().enabled

    def start(self) -> None:
        with self._lock:
            if any(
                worker is not None and worker.is_alive()
                for worker in (self._worker, self._ocr_worker, self._cursor_worker)
            ):
                return
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._run_loop,
                name="shinsekai-perception-worker",
                daemon=True,
            )
            self._ocr_worker = threading.Thread(
                target=self._run_ocr_loop,
                name="shinsekai-screen-ocr",
                daemon=True,
            )
            self._worker.start()
            self._ocr_worker.start()
            if self._cursor_probe is not None:
                self._cursor_worker = threading.Thread(
                    target=self._run_cursor_loop,
                    name="shinsekai-cursor-reader",
                    daemon=True,
                )
                self._cursor_worker.start()
        self._emit_state()

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._analysis_progress:
            self._stop_event.set()
            self._wake_event.set()
            self._ocr_wake_event.set()
            self._cursor_wake_event.set()
            workers = (self._worker, self._ocr_worker, self._cursor_worker, self._summary_worker)
            self._analysis_progress.notify_all()
        deadline = time.monotonic() + max(0.1, timeout)
        for worker in workers:
            if worker is not None and worker.is_alive():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._cursor_probe is not None:
            try:
                self._cursor_probe.close()
            except Exception:
                logger.debug("cursor probe close failed", exc_info=True)

    def clear(self) -> dict[str, Any]:
        with self._analysis_progress:
            self.raw_buffer.clear()
            self.rp_input_cache.clear()
            self._reflex_policy.reset()
            self._cursor_tracker.reset()
            self._analysis_epoch += 1
            self._playback_stopped_at = 0.0
            self._processed_revision = self.raw_buffer.stats()["revision"]
            self._latest_screen_frame = None
            self._previous_vision_frame = None
            self._latest_ocr = (0.0, "")
            self._last_subtitle_monotonic = 0.0
            self._latest_highlight = (0.0, "")
            self._latest_cursor_ocr = (0.0, "")
            self._recent_screen_text.clear()
            self._last_vision_ocr_key = ""
            self._screen_digest = ""
            self._screen_digest_at = 0.0
            self._last_infer_monotonic = 0.0
            self._last_error = ""
            self._analysis_progress.notify_all()
        state = self.status_snapshot()
        self._publish_state(state)
        return state

    def set_screen_share_active(self, active: bool) -> dict[str, Any]:
        with self._lock:
            changed = self._screen_share_active != bool(active)
            self._screen_share_active = bool(active)
            if changed:
                self._screen_generation += 1
                self._screen_audio = "unavailable"
                self._screen_audio_at = self._playback_stopped_at = 0.0
                self._latest_screen_frame = None
                self._previous_vision_frame = None
                self._latest_ocr = (0.0, "")
                self._last_subtitle_monotonic = 0.0
                self._latest_highlight = (0.0, "")
                self._latest_cursor_ocr = (0.0, "")
                self._cursor_tracker.reset()
                self._recent_screen_text.clear()
                self._last_vision_ocr_key = ""
                self._screen_digest = ""
                self._screen_digest_at = 0.0
                self._reflex_policy.reset()
                if active:
                    self.rp_input_cache.reset_working_window_preserving_episodes()
                    self._warned_unreachable = False
                    self._last_infer_monotonic = 0.0
                else:
                    self.rp_input_cache.archive_live_window_for_pause()
                    self.raw_buffer.discard_frame("screen_share")
                    if not self.raw_buffer.has_dirty():
                        self._processed_revision = self.raw_buffer.stats()["revision"]
                        self._analysis_progress.notify_all()
        if changed:
            self._wake_event.set()
            self._ocr_wake_event.set()
            self._cursor_wake_event.set()
            self._emit_state()
        return self.status_snapshot()

    def wait_for_buffered_context(self, timeout: float = 1.8) -> None:
        """Wait for the current raw revision to finish without changing its schedule."""
        with self._analysis_progress:
            if self._worker is None or not self._worker.is_alive():
                return
            revision = self.raw_buffer.stats()["revision"]
            self._wake_event.set()
            self._analysis_progress.wait_for(
                lambda: self._processed_revision >= revision or self._stop_event.is_set(),
                timeout=timeout,
            )

    def ingest(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Accept normalized JSON/frame payload from HTTP route, frontend command, or plugin SDK."""
        if not isinstance(payload, Mapping):
            raise ValueError("perception payload must be an object")

        if "screenShareActive" in payload:
            self.set_screen_share_active(bool(payload.get("screenShareActive")))

        source = str(payload.get("source") or "external").strip()[:64] or "external"
        audio = payload.get("screenPlaybackAudio")
        if source == "screen_share" and audio in ("unavailable", "playing", "quiet", "stopped"):
            self._ingest_screen_audio(audio, payload.get("capturedAtMs"))
        game = str(payload.get("game") or "").strip()[:64]
        replace_state = bool(payload.get("replaceState", False))

        raw_state = payload.get("state")
        if isinstance(raw_state, Mapping) and raw_state:
            self.raw_buffer.ingest_state(
                raw_state,
                source=source,
                game=game,
                replace=replace_state,
            )

        single_event = payload.get("event")
        if isinstance(single_event, str) and single_event.strip():
            event_data = payload.get("data")
            self.raw_buffer.ingest_event(
                single_event.strip(),
                event_data if isinstance(event_data, Mapping) else None,
                source=source,
                game=game,
            )
        elif isinstance(single_event, Mapping):
            ev_type = str(single_event.get("type") or single_event.get("event") or "").strip()
            if ev_type:
                ev_data = single_event.get("data")
                self.raw_buffer.ingest_event(
                    ev_type,
                    ev_data if isinstance(ev_data, Mapping) else single_event,
                    source=source,
                    game=game,
                )

        raw_events = payload.get("events")
        if isinstance(raw_events, list):
            for item in raw_events[:32]:
                if isinstance(item, Mapping):
                    ev_type = str(item.get("type") or item.get("event") or "").strip()
                    if ev_type:
                        ev_data = item.get("data")
                        self.raw_buffer.ingest_event(
                            ev_type,
                            ev_data if isinstance(ev_data, Mapping) else item,
                            source=source,
                            game=game,
                        )

        image_b64 = str(payload.get("imageBase64") or "").strip()
        if image_b64:
            received_at = time.time()
            captured_at_ms = payload.get("capturedAtMs")
            captured_at = received_at
            if isinstance(captured_at_ms, (int, float)) and captured_at_ms > 0:
                captured_at = min(received_at, captured_at_ms / 1000)
            if source == "screen_share" and "screenShareActive" not in payload:
                self.set_screen_share_active(True)
            frame = PerceptionFrame(
                image_base64=image_b64,
                mime_type=str(payload.get("mimeType") or "image/jpeg").strip()[:64],
                width=max(0, int(payload.get("width") or 0)),
                height=max(0, int(payload.get("height") or 0)),
                source=source,
                game=game,
                captured_at=captured_at,
                ocr_scope=(
                    ScreenOcrScope.from_payload(payload["ocrScope"])
                    if source == "screen_share" and "ocrScope" in payload else None
                ),
            )
            with self._lock:
                if source != "screen_share":
                    self.raw_buffer.ingest_frame(frame)
                elif self._screen_share_active:
                    if self._latest_screen_frame is None or captured_at >= self._latest_screen_frame.captured_at:
                        previous_scope = self._latest_screen_frame.ocr_scope if self._latest_screen_frame else None
                        if (previous_scope or ScreenOcrScope()) != (frame.ocr_scope or ScreenOcrScope()):
                            self._ocr_scope_revision += 1
                            self._latest_ocr = (0.0, "")
                            self._last_subtitle_monotonic = 0.0
                            self._recent_screen_text.clear()
                            self._last_vision_ocr_key = ""
                            self.rp_input_cache.clear_screen_text(preserve_highlights=True)
                        self._latest_screen_frame = frame
                        self._ocr_wake_event.set()
                    if not payload.get("ocrOnly"):
                        self.raw_buffer.ingest_frame(frame)

        if self.raw_buffer.has_dirty():
            self._wake_event.set()

        return self.status_snapshot()

    def status_snapshot(self) -> dict[str, Any]:
        cfg = self.current_config()
        with self._lock:
            share_active = self._screen_share_active
            last_error = self._last_error
        return {
            "enabled": cfg.enabled,
            "active": share_active or cfg.enabled,
            "screenShareActive": share_active,
            "model": cfg.model,
            "baseUrl": cfg.base_url,
            "intervalSec": cfg.interval_sec,
            "captureIntervalSec": cfg.capture_interval_sec,
            "ocrIntervalSec": cfg.ocr_interval_sec,
            "frameMaxSide": cfg.frame_max_side,
            "diffThreshold": cfg.diff_threshold,
            "ocrEnabled": cfg.use_local_ocr,
            "screenPlaybackAudioSettings": self.rp_input_cache.policy.screen_playback_audio_settings(),
            "reflexEnabled": cfg.reflex_enabled,
            "proactiveEnabled": cfg.proactive_enabled,
            "salienceThreshold": cfg.salience_threshold,
            "lastError": last_error,
            "rawBuffer": self.raw_buffer.stats(),
            "rpCache": self.rp_input_cache.to_status_dict(),
        }

    def _emit_state(self) -> None:
        try:
            self._publish_state(self.status_snapshot())
        except Exception:
            logger.debug("failed to publish perception state", exc_info=True)

    def _character_prompt_metadata(self) -> tuple[str, str, dict[str, tuple[int, ...]], dict[int, str], int]:
        character = self._resolve_character()
        if character is None:
            return ("", "", {}, {}, 0)
        name = str(getattr(character, "name", "") or "").strip()
        brief = str(
            getattr(character, "character_brief", "")
            or getattr(character, "character_setting", "")
            or ""
        ).strip()
        try:
            assets = get_character_assets(character)
            sprites = assets.sprites
            emotion_tags = str(assets.emotion_tags or "")
        except Exception:
            sprites = getattr(character, "sprites", None) or []
            emotion_tags = str(getattr(character, "emotion_tags", "") or "")
        expressions = expression_sprite_candidates(sprites, emotion_tags)
        return name, brief, expressions, sprite_prompt_choices(sprites, emotion_tags, expressions), len(sprites)

    def _maybe_fire_reflex(
        self,
        reflex: ReflexDecision,
        *,
        character_name: str,
        expressions: Mapping[str, tuple[int, ...]],
        sprite_count: int,
        config: PerceptionConfig,
        sprite_choices: Mapping[int, str] | None = None,
        fallback_bark: str = "",
        now_mono: float | None = None,
    ) -> ReflexDecision | None:
        if not config.reflex_enabled or not reflex.act or not character_name:
            return None
        if self._is_chat_busy():
            logger.debug("Perception reaction skipped while chat is busy")
            return None
        now = time.monotonic() if now_mono is None else float(now_mono)
        with self._lock:
            emitted = self._reflex_policy.select_emission(
                reflex,
                character_name=character_name,
                expressions=expressions,
                sprite_count=sprite_count,
                config=config,
                sprite_choices=sprite_choices,
                fallback_bark=fallback_bark,
                now=now,
            )
        if emitted is None:
            logger.debug("Perception reaction suppressed by cooldown or deduplication")
            return None
        self._apply_reflex(character_name, emitted.sprite, emitted.bark)
        logger.info(
            "Perception reaction emitted (character=%s, sprite_id=%s, bark=%s)",
            character_name,
            emitted.sprite + 1 if emitted.sprite is not None else None,
            emitted.bark,
            extra={"event": "perception.reflex.emitted"},
        )
        return emitted

    def _run_ocr_loop(self) -> None:
        previous_frame = None
        previous_scope = None
        last_run = 0.0
        wake_timeout = 1.0
        warned = False
        while not self._stop_event.is_set():
            self._ocr_wake_event.wait(timeout=wake_timeout)
            self._ocr_wake_event.clear()
            wake_timeout = 1.0
            if self._stop_event.is_set():
                break
            cfg = self.current_config()
            if not cfg.use_local_ocr:
                continue
            with self._lock:
                scope = self._screen_generation, self._analysis_epoch, self._ocr_scope_revision
                if scope != previous_scope:
                    previous_scope, previous_frame, last_run, warned = scope, None, 0.0, False
                frame = self._latest_screen_frame
                if (
                    not self._screen_share_active or frame is None or frame is previous_frame
                    or time.time() - frame.captured_at > max(3.0, cfg.ocr_interval_sec * 2)
                ):
                    continue
            delay = last_run + cfg.ocr_interval_sec - time.monotonic()
            if delay > 0:
                wake_timeout = delay
                continue
            previous_frame = frame
            last_run = time.monotonic()
            try:
                text = self.decision_client.read_screen_text(frame, cfg)
            except Exception as exc:
                if not warned:
                    logger.warning("screen OCR failed: %s", exc)
                    warned = True
                continue
            warned = False
            with self._lock:
                if (
                    scope != (self._screen_generation, self._analysis_epoch, self._ocr_scope_revision)
                    or self._stop_event.is_set() or not self.current_config().use_local_ocr
                    or time.time() - frame.captured_at > max(3.0, cfg.ocr_interval_sec * 2)
                ):
                    continue
                had_subtitle = bool(comparison_text(self._latest_ocr[1]))
                self._latest_ocr = (frame.captured_at, text)
                key = comparison_text(text)
                if key or had_subtitle:
                    self._last_subtitle_monotonic = time.monotonic()
                if key:
                    sample = (frame.captured_at, text)
                    if self._recent_screen_text and comparison_text(self._recent_screen_text[-1][1]) == key:
                        self._recent_screen_text[-1] = sample
                    else:
                        self._recent_screen_text.append(sample)
                        latest = self._latest_screen_frame
                        if latest and 0 <= latest.captured_at - frame.captured_at <= max(2.0, cfg.ocr_interval_sec * 2):
                            self.raw_buffer.ingest_frame(latest)
                            self._wake_event.set()
                self.rp_input_cache.record_screen_text(text, captured_at=frame.captured_at)

    def _are_subtitles_active_locked(self, now_mono: float) -> bool:
        """Return True when screen OCR currently sees subtitles or is within the dialogue gap."""
        _ocr_at, ocr_text = self._latest_ocr
        if comparison_text(ocr_text):
            return True
        if self._last_subtitle_monotonic <= 0.0:
            return False
        return (now_mono - self._last_subtitle_monotonic) < self.rp_input_cache.policy.cursor_subtitle_quiet_sec

    def step_cursor_once(
        self,
        *,
        now_mono: float | None = None,
        now_wall: float | None = None,
    ) -> CursorObservation | None:
        """Run one `高亮 > 识别字幕 > 识别手边文字` tick and commit any recognized reading focus."""
        probe = self._cursor_probe
        if probe is None:
            return None
        mono = time.monotonic() if now_mono is None else float(now_mono)
        wall = time.time() if now_wall is None else float(now_wall)
        with self._lock:
            if self._stop_event.is_set() or not self._screen_share_active:
                return None
            scope = (self._screen_generation, self._analysis_epoch)
            subtitles_active = self._are_subtitles_active_locked(mono)
            policy = self.rp_input_cache.policy

        cfg = self.current_config()
        try:
            sample = probe.sample()
            obs = self._cursor_tracker.step(
                sample=sample,
                probe=probe,
                ocr_fn=lambda patch_frame: self.decision_client.read_screen_text(patch_frame, cfg),
                use_local_ocr=cfg.use_local_ocr,
                subtitles_active=subtitles_active,
                policy=policy,
                ocr_interval_sec=cfg.ocr_interval_sec,
                now_mono=mono,
                now_wall=wall,
            )
        except Exception:
            logger.debug("cursor text probe failed", exc_info=True)
            return None
        if obs is None:
            return None

        with self._lock:
            if (
                self._stop_event.is_set()
                or not self._screen_share_active
                or scope != (self._screen_generation, self._analysis_epoch)
            ):
                return None
            check_mono = time.monotonic() if now_mono is None else mono
            if obs.source == "cursor" and self._are_subtitles_active_locked(check_mono):
                # Subtitle arrived while cursor ROI OCR was running (`识别字幕 > 识别手边文字`)
                return None
            if obs.source == "highlight":
                changed = self.rp_input_cache.record_highlighted_text(
                    obs.text,
                    captured_at=obs.captured_at,
                )
                self._latest_highlight = (obs.captured_at, obs.text)
            else:
                changed = self.rp_input_cache.record_cursor_text(
                    obs.text,
                    captured_at=obs.captured_at,
                )
                self._latest_cursor_ocr = (obs.captured_at, obs.text)

        if changed:
            reading = short_reading_focus(obs.text)
            if reading:
                char_name, _brief, expressions, sprite_choices, sprite_count = self._character_prompt_metadata()
                effective_cfg = (
                    replace(cfg, reflex_cooldown_sec=min(3.5, cfg.reflex_cooldown_sec))
                    if obs.source == "highlight"
                    else cfg
                )
                self._maybe_fire_reflex(
                    ReflexDecision(act=True, bark=f"（正在读：{reading}）"),
                    character_name=char_name,
                    expressions=expressions,
                    sprite_count=sprite_count,
                    config=effective_cfg,
                    sprite_choices=sprite_choices,
                    now_mono=mono,
                )
            self._emit_state()
        return obs

    def _run_cursor_loop(self) -> None:
        probe = self._cursor_probe
        if probe is None:
            return
        try:
            probe.prepare_thread()
        except Exception:
            logger.debug("cursor probe thread init failed", exc_info=True)
        while not self._stop_event.is_set():
            with self._lock:
                active = self._screen_share_active
            if not active:
                self._cursor_wake_event.wait(timeout=1.0)
                self._cursor_wake_event.clear()
                continue
            self.step_cursor_once()
            self._stop_event.wait(timeout=0.05)

    def _execute_summary_job(
        self,
        job: Mapping[str, Any],
        epoch: int,
    ) -> bool:
        batch = list(job.get("batch") or ())
        if not batch:
            return False
        result = summarize_vision_window(
            job,
            cloud_complete=self._cloud_complete,
        )
        with self._lock:
            if epoch != self._analysis_epoch or self._stop_event.is_set():
                return False
            self.rp_input_cache.commit_summary_job(
                minute_summary=result.minute_summary,
                overall_summary=result.overall_summary,
                start_ts=batch[0][0],
                end_ts=batch[-1][0],
                mood=result.mood,
                guidance=result.guidance,
            )
        self._emit_state()
        return True

    def run_due_cloud_summary(
        self,
        *,
        now: float | None = None,
        force: bool = False,
    ) -> bool:
        """Synchronously execute a due 2-minute Cloud LLM summary job if available."""
        with self._lock:
            if self._stop_event.is_set():
                return False
            epoch = self._analysis_epoch
            job = self.rp_input_cache.prepare_summary_job(now=now, force=force)
        if job is None:
            return False
        return self._execute_summary_job(job, epoch)

    def _maybe_schedule_cloud_summary(self) -> None:
        """Launch out-of-band Cloud LLM summarization when a 2-minute window is due."""
        with self._lock:
            if self._stop_event.is_set():
                return
            if self._summary_worker is not None and self._summary_worker.is_alive():
                return
            epoch = self._analysis_epoch
            job = self.rp_input_cache.prepare_summary_job(now=time.time())
            if job is None:
                return
            worker = threading.Thread(
                target=self._execute_summary_job,
                args=(job, epoch),
                name="shinsekai-perception-cloud-summary",
                daemon=True,
            )
            self._summary_worker = worker
        worker.start()

    def _maybe_run_idle_maintenance(self, cfg: PerceptionConfig) -> None:
        """Run one-off voice style extraction when idle, and schedule Cloud LLM summaries."""
        self._maybe_schedule_cloud_summary()
        if self.raw_buffer.has_dirty() or self._stop_event.is_set():
            return
        custom_client = type(self.decision_client) is not PerceptionDecisionClient
        can_query_llm = self._server_verified or custom_client

        if self._screen_share_active and can_query_llm:
            char_name, char_brief, *_ = self._character_prompt_metadata()
            if char_brief:
                get_cached = getattr(self.decision_client, "get_cached_voice_style", None)
                extract_fn = getattr(self.decision_client, "extract_voice_style", None)
                attempt_key = (char_name, char_brief[:160])
                if (
                    callable(get_cached)
                    and callable(extract_fn)
                    and attempt_key not in self._attempted_voice_styles
                    and get_cached(char_name, char_brief) is None
                ):
                    self._attempted_voice_styles.add(attempt_key)
                    try:
                        extract_fn(char_name, char_brief, cfg)
                    except Exception:
                        logger.debug("background voice style extraction failed", exc_info=True)

    def _run_loop(self) -> None:
        wake_timeout = 1.0
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=wake_timeout)
            self._wake_event.clear()
            wake_timeout = 1.0
            if self._stop_event.is_set():
                break

            cfg = self.current_config()
            if not (cfg.enabled or self._screen_share_active):
                self._maybe_schedule_cloud_summary()
                continue

            if not self.raw_buffer.has_dirty():
                self._maybe_trigger_proactive(cfg)
                self._maybe_run_idle_maintenance(cfg)
                continue

            with self._lock:
                remaining = self._last_infer_monotonic + cfg.interval_sec - time.monotonic()
                if self._last_infer_monotonic > 0.0 and remaining > 0.0:
                    wake_timeout = min(1.0, remaining)
                    continue
                epoch = self._analysis_epoch
                screen_generation = self._screen_generation
                snapshot = self.raw_buffer.drain_snapshot()
            if snapshot.is_empty:
                continue

            char_name, char_brief, expressions, sprite_choices, sprite_count = self._character_prompt_metadata()
            displayed_reflex: ReflexDecision | None = None
            frame = snapshot.frame
            live_screen = frame is not None and frame.source == "screen_share"
            frame_max_age = max(3.0, min(8.0, cfg.interval_sec * 2 + 1.0))

            def current_screen_frame() -> bool:
                return (
                    self._screen_share_active
                    and screen_generation == self._screen_generation
                    and frame is not None
                    and time.time() - frame.captured_at <= frame_max_age
                )

            def on_reflex(reflex: ReflexDecision, *, fallback_bark: str = "") -> None:
                nonlocal displayed_reflex
                with self._lock:
                    if epoch != self._analysis_epoch or self._stop_event.is_set():
                        return
                    if live_screen and not current_screen_frame():
                        return
                displayed_reflex = self._maybe_fire_reflex(
                    reflex,
                    character_name=char_name,
                    expressions=expressions,
                    sprite_count=sprite_count,
                    config=cfg,
                    sprite_choices=sprite_choices,
                    fallback_bark=fallback_bark,
                )

            def on_early_reflex(reflex: ReflexDecision) -> None:
                if comparison_text(reflex.bark):
                    on_reflex(reflex)

            try:
                previous_frame = None
                ocr_scope_revision = None
                screen_text = ""
                previous_screen_text = ""
                screen_text_changed = False
                scene_anchor = ""
                recent_subtitles: list[str] = []
                voice_style = ""
                with self._lock:
                    if live_screen and not current_screen_frame():
                        snapshot = replace(snapshot, frame=None)
                        live_screen = False
                        frame = None
                        if snapshot.is_empty:
                            continue
                    if live_screen:
                        ocr_scope_revision = self._ocr_scope_revision
                        if self._latest_screen_frame is not None and frame.ocr_scope != self._latest_screen_frame.ocr_scope:
                            snapshot = replace(snapshot, frame=replace(frame, ocr_scope=self._latest_screen_frame.ocr_scope))
                        previous_digest = self._screen_digest if time.time() - self._screen_digest_at < 8.0 else ""
                        scene_anchor = self.rp_input_cache.scene_anchor
                        recent_subtitles = self.rp_input_cache.recent_subtitles(limit=4)
                        if char_brief:
                            get_cached_style = getattr(self.decision_client, "get_cached_voice_style", None)
                            if callable(get_cached_style):
                                voice_style = get_cached_style(char_name, char_brief) or ""
                        earlier = self._previous_vision_frame
                        if earlier and 0 < frame.captured_at - earlier.captured_at <= max(8.0, cfg.interval_sec * 2):
                            previous_frame = earlier
                        self._previous_vision_frame = frame
                        hl_at, hl_text = self._latest_highlight
                        ocr_at, sub_text = self._latest_ocr
                        cur_at, cur_text = self._latest_cursor_ocr
                        now_wall = time.time()
                        # Priority: highlight > subtitle > cursor-adjacent text
                        if comparison_text(hl_text) and 0 <= now_wall - hl_at <= max(6.0, cfg.interval_sec * 3):
                            screen_text = hl_text
                            screen_text_changed = comparison_text(hl_text) != self._last_vision_ocr_key
                        elif cfg.use_local_ocr and 0 <= frame.captured_at - ocr_at <= max(2.0, cfg.ocr_interval_sec * 2) and comparison_text(sub_text):
                            screen_text = sub_text
                            key = comparison_text(sub_text)
                            screen_text_changed = key != self._last_vision_ocr_key
                            if screen_text_changed and len(self._recent_screen_text) == 2:
                                previous_at, previous_text = self._recent_screen_text[0]
                                if 0 <= ocr_at - previous_at <= max(4.0, cfg.ocr_interval_sec * 2):
                                    previous_screen_text = previous_text
                        elif cfg.use_local_ocr and comparison_text(cur_text) and 0 <= now_wall - cur_at <= max(5.0, cfg.interval_sec * 2):
                            screen_text = cur_text
                            screen_text_changed = comparison_text(cur_text) != self._last_vision_ocr_key
                    else:
                        previous_digest = self.rp_input_cache.current_digest
                    now = time.monotonic()
                    self._last_infer_monotonic = now
                    recent_barks = self._reflex_policy.recent_spoken_barks(char_name, now=now)
                    focus_hint = self.rp_input_cache.policy.focus_hint
                decide_kwargs: dict[str, Any] = {
                    "previous_digest": previous_digest,
                    "character_name": char_name,
                    "character_brief": char_brief,
                    "voice_style": voice_style,
                    "scene_anchor": scene_anchor,
                    "recent_subtitles": recent_subtitles,
                    "recent_barks": recent_barks,
                    "sprite_choices": sprite_choices,
                    "previous_frame": previous_frame,
                    "screen_text": screen_text,
                    "previous_screen_text": previous_screen_text,
                    "screen_text_changed": screen_text_changed,
                    "retry_unreadable": not live_screen,
                    "on_early_reflex": None if live_screen else on_early_reflex,
                }
                if focus_hint:
                    decide_kwargs["reaction_guidance"] = f"当前观察侧重：{focus_hint}。"
                result = self.decision_client.decide(snapshot, cfg, **decide_kwargs)
            except Exception as exc:
                err_text = str(exc)
                with self._lock:
                    if epoch != self._analysis_epoch or (
                        live_screen and (
                            not current_screen_frame() or ocr_scope_revision != self._ocr_scope_revision
                        )
                    ):
                        continue
                    if live_screen and isinstance(exc, InvalidPerceptionDecision):
                        logger.debug("Skipping unreadable live screen frame: %s", exc)
                        continue
                    self._last_error = err_text[:300]
                    should_warn = not self._warned_unreachable
                    self._warned_unreachable = True
                if should_warn:
                    logger.warning("perception inference failed: %s", exc)
                    if isinstance(exc, InvalidPerceptionDecision):
                        message = "这帧没有可用的识别结果，继续采样。"
                    elif isinstance(exc, PerceptionInferenceError):
                        message = f"视觉推理失败：{err_text[:160]}"
                    else:
                        message = f"视觉请求失败：{err_text[:160]}"
                    self._notify_once(message)
                self._emit_state()
                continue

            else:
                logger.debug(
                    "Perception decision (source=%s, latency_ms=%.0f, sprite_id=%s, bark=%r)",
                    frame.source if frame else "game_event",
                    result.latency_ms,
                    result.reflex.sprite_id,
                    result.reflex.bark,
                    extra={"event": "perception.reflex.decision"},
                )
                with self._lock:
                    if epoch != self._analysis_epoch or self._stop_event.is_set() or (
                        live_screen and (
                            not current_screen_frame() or ocr_scope_revision != self._ocr_scope_revision
                        )
                    ):
                        continue
                    self._server_verified = True
                    now_mono = time.monotonic()
                    if live_screen:
                        if screen_text_changed:
                            self._last_vision_ocr_key = comparison_text(screen_text)
                        scene = comparison_text(result.digest)
                        if scene and scene == comparison_text(self._screen_digest):
                            result = replace(result, digest=self._screen_digest)
                        reflex = self._reflex_policy.refine_for_context(
                            result,
                            live_screen=True,
                            screen_text=screen_text,
                            screen_text_changed=screen_text_changed,
                            config=cfg,
                            now=now_mono,
                        )
                        if reflex.act:
                            on_reflex(
                                reflex,
                                fallback_bark=observation_bark(
                                    result, fresh_screen_text=screen_text if screen_text_changed else "",
                                ),
                            )
                    elif displayed_reflex is None and result.reflex.act:
                        reflex = self._reflex_policy.refine_for_context(
                            result,
                            live_screen=False,
                            screen_text=screen_text,
                            screen_text_changed=False,
                            config=cfg,
                            now=now_mono,
                        )
                        if reflex.act:
                            on_reflex(reflex, fallback_bark=observation_bark(result, fresh_screen_text=""))
                    self._last_error = ""
                    self._warned_unreachable = False
                    observed_at = frame.captured_at if frame else max(
                        (event.timestamp for event in snapshot.events), default=result.created_at,
                    )
                    if live_screen and result.digest:
                        self._screen_digest = result.digest
                        self._screen_digest_at = observed_at
                    self.rp_input_cache.record_decision(
                        replace(result, reflex=displayed_reflex or ReflexDecision(), created_at=observed_at),
                        proactive_threshold=cfg.salience_threshold,
                    )
            finally:
                with self._analysis_progress:
                    self._processed_revision = max(self._processed_revision, snapshot.revision)
                    self._analysis_progress.notify_all()

            self._emit_state()
            self._maybe_trigger_proactive(cfg)
            self._maybe_run_idle_maintenance(cfg)

    def _ingest_screen_audio(self, audio: ScreenPlaybackAudio, captured_at_ms: Any) -> None:
        now = time.time()
        captured_at = (
            min(now, captured_at_ms / 1000)
            if isinstance(captured_at_ms, (int, float)) and captured_at_ms > 0 else now
        )
        with self._lock:
            if not self._screen_share_active or captured_at < self._screen_audio_at:
                return
            if audio != self._screen_audio:
                self._playback_stopped_at = captured_at if audio == "stopped" else 0.0
            self._screen_audio = audio
            self._screen_audio_at = captured_at
        if audio in ("quiet", "stopped"):
            self._maybe_trigger_proactive(self.current_config())

    def _screen_audio_for_proactive(self) -> ScreenPlaybackAudio | None:
        if not self._screen_share_active:
            return None
        now = time.time()
        if now - self._screen_audio_at > 2.0:
            return "unavailable"
        if self._screen_audio == "stopped" and now - self._playback_stopped_at > PROACTIVE_EVENT_MAX_AGE_SEC:
            return "unavailable"
        return self._screen_audio

    def _maybe_trigger_proactive(self, cfg: PerceptionConfig) -> None:
        with self._lock:
            effective_cfg = replace(cfg, enabled=True) if self._screen_share_active and not cfg.enabled else cfg
            verdict = self.gatekeeper.evaluate(
                self.rp_input_cache,
                effective_cfg,
                chat_busy=self._is_chat_busy(),
                screen_audio=self._screen_audio_for_proactive(),
            )
            if verdict.allow and self._enqueue_proactive_turn(PROACTIVE_TURN_INSTRUCTION):
                logger.info(
                    "Perception proactive reply queued (reason=%s, salience=%.2f)",
                    verdict.reason,
                    verdict.salience,
                    extra={"event": "perception.proactive.queued", "reason": verdict.reason},
                )

    def proactive_turn_threshold(self) -> float | None:
        """Recheck settings when a queued proactive event reaches the chat worker."""
        with self._lock:
            cfg = replace(self.current_config(), enabled=self.is_effectively_enabled())
            verdict = self.gatekeeper.evaluate(
                self.rp_input_cache, cfg, screen_audio=self._screen_audio_for_proactive(),
            )
            if not verdict.allow:
                return None
            if verdict.reason == "playback_stopped":
                return 0.0
            if self.rp_input_cache.player_busy:
                return max(cfg.salience_threshold, URGENT_SCREEN_SALIENCE)
            return max(cfg.salience_threshold, 0.001)

    def mark_proactive_turn_admitted(self) -> None:
        with self._lock:
            self._playback_stopped_at = 0.0
