"""Framework-neutral presentation adapters for headless and React/Tauri chat."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, MutableSequence, Optional

if TYPE_CHECKING:
    from application.runtime.event_sink import ChatEventSink

from application.media.resource_urls import ResourceUrls
from core.messaging.stage_effects import normalize_scene_transition, scene_transition_duration_ms
from core.messaging.stat_payload import parse_stat_payload

from .ambient_controller import StageAmbientController
from .character_lookup import bind_presentation_character_catalog, get_character_by_name
from .character_visual import resolve_character_visual
from .dialog_controller import StageDialogController
from .effect_controller import StageEffectController
from .effect_resolution import (
    IMAGE_EFFECT_DURATION_MS, SOUND_EFFECTS_PATH, find_running_effect_key,
    match_ambient_asset, same_effect_asset,
)
from .formatting import (
    _format_dialog_html, _format_token_count, _format_user_html,
    _native_tool_confirmation_options, _safe_css_color, format_context_token_estimate,
)
from .headless import HeadlessUIUpdateManager
from .sprite_controller import StageSpriteController

logger = logging.getLogger(__name__)


class StreamingUIUpdateManager(HeadlessUIUpdateManager):
    """Streaming event presenter delegating dialog, sprite, ambient, and effect controllers."""

    _find_running_effect_key = staticmethod(find_running_effect_key)
    _same_loop_asset = staticmethod(same_effect_asset)
    _match_ambient_asset = staticmethod(match_ambient_asset)

    def __init__(
        self, sink: "ChatEventSink", chat_history: Optional[MutableSequence[str]] = None,
        bg_group: Optional[List] = None, max_sprite_slots: int = 3, *, resource_urls: ResourceUrls,
    ) -> None:
        super().__init__(chat_history=chat_history)
        if not isinstance(resource_urls, ResourceUrls):
            raise TypeError("Chat presentation requires both media and model resource URL methods")
        self._sink = sink
        self._resource_urls = resource_urls
        self.bg_group = list(bg_group or [])
        self._background_url = ""
        self.audio_playback_owner = "frontend"
        self._notification_lock = threading.Lock()
        self._notification_version = 0
        self._presentation_emit_lock = threading.RLock()

        # Pass module-level lookups through lambdas so tests patching attributes on
        # ``application.chat.presentation.updates`` or methods on this instance keep working.
        self._sprites = StageSpriteController(
            emit=self._emit, resource_urls=resource_urls, max_sprite_slots=max_sprite_slots,
            character_lookup=lambda name: get_character_by_name(name),
            visual_resolver=lambda ch, sid, urls: resolve_character_visual(ch, sid, urls),
        )
        self.max_sprite_slots = self._sprites.max_sprite_slots
        self._ambient = StageAmbientController(emit=self._emit, media_url=self._media_url)
        self._effects = StageEffectController(
            emit=self._emit, media_url=self._media_url,
            remove_sprite=lambda name: self.remove_character_sprite(name), ambient=self._ambient,
        )
        self._dialog = StageDialogController(
            emit=self._emit, chat_history_getter=lambda: self.chat_history,
            voice_archive_getter=lambda: getattr(self, "voice_archive", None),
            player_character_getter=lambda: str(getattr(self, "player_character", "") or ""),
            show_player_portrait=lambda name, sid: self.update_player_portrait(name, sid),
            record_console_user_message=super().record_user_message,
        )

    @property
    def _sprite_lru(self) -> OrderedDict[str, int]:
        return self._sprites.sprite_lru

    @property
    def _looping_effects(self) -> dict[str, str]:
        return self._effects.looping_effects

    @property
    def _ambient_effects(self) -> dict[str, dict[str, str]]:
        return self._ambient.ambient_effects

    @property
    def _ambient_aliases(self) -> dict[str, str]:
        return self._ambient.ambient_aliases

    def _emit(self, event: dict) -> None:
        with self._presentation_emit_lock:
            recorder = getattr(self, "replay_recorder", None)
            if recorder is not None and not getattr(self, "replay_active", False):
                try:
                    recorder.observe(event)
                except (OSError, ValueError):
                    # Optional replay storage must not interrupt the live performance.
                    logger.warning("Could not save replay frame", exc_info=True)
            self._sink.emit(event)

    def _media_url(self, raw_path: str) -> str:
        return self._resource_urls.media_url(raw_path)

    def sync_history_entries(self) -> None:
        self._dialog.sync_history_entries()

    # --- Low-level stage state notifications ---

    def post_notification(self, text: str) -> None:
        with self._notification_lock:
            self._notification_version += 1
            version = self._notification_version
            self._emit({"type": "notification.change", "text": text})
        if text == "语音已保存":
            def clear_saved_notification() -> None:
                with self._notification_lock:
                    if version == self._notification_version:
                        self._emit({"type": "notification.change", "text": ""})

            timer = threading.Timer(2.5, clear_saved_notification)
            timer.daemon = True
            timer.start()

    def post_busy_bar(self, text: str, timeout: float = 0.0) -> None:
        if text:
            self._emit({"type": "busy.show", "text": text, "durationSeconds": float(timeout)})
        else:
            self._emit({"type": "busy.hide"})

    def hide_busy_bar(self) -> None:
        self._emit({"type": "busy.hide"})

    def post_options(self, option_list: List[Any], *, selected_index: int | None = None) -> None:
        options = [str(x) for x in (option_list or [])]
        if options:
            payload: dict[str, Any] = {"type": "options.show", "options": options}
            if selected_index is not None:
                payload["selectedIndex"] = selected_index
            self._emit(payload)
        else:
            self._emit({"type": "options.clear"})
        if not getattr(self, "replay_active", False):
            self.sync_history_entries()

    def post_tool_confirmation(
        self, *, confirmation_id: str, tool_name: str, detail: str = "", risk: str = "high"
    ) -> None:
        self._emit({
            "type": "tool.confirmation.show",
            "confirmationId": str(confirmation_id or ""),
            "detail": str(detail or ""),
            "risk": "medium" if str(risk).casefold() == "medium" else "high",
            "toolName": str(tool_name or ""),
        })

    def clear_tool_confirmation(self, confirmation_id: str) -> None:
        self._emit({"type": "tool.confirmation.clear", "confirmationId": str(confirmation_id or "")})

    def post_numeric_value(self, text: str) -> None:
        stats = parse_stat_payload(text)
        if stats or not str(text or "").strip():
            self._emit({"type": "stats.update", "stats": stats})

    def post_context_token_estimate(self, estimate: Dict[str, Any]) -> None:
        self._emit({"type": "numeric.update", "html": format_context_token_estimate(estimate)})

    def post_background(self, path: str, *, transition: str = "") -> None:
        url = self._media_url(path)
        if url != self._background_url:
            self._sprites.clear_slots()
        self._background_url = url
        self.current_background_path = path or None
        payload: dict[str, Any] = {"type": "background.change", "url": url}
        normalized_transition = normalize_scene_transition(transition)
        if normalized_transition:
            payload["transition"] = normalized_transition
            payload["transitionDurationMs"] = scene_transition_duration_ms(normalized_transition)
        self._emit(payload)

    def switch_bgm(self, new_bgm_path: str) -> None:
        path = str(new_bgm_path or "").strip()
        self.current_bgm_path = path or None
        self._emit({"type": "bgm.change", "url": self._media_url(path)})

    def post_cg(self, path: str) -> None:
        self._emit({"type": "cg.show", "url": self._media_url(path)} if path else {"type": "cg.hide"})

    def post_llm_reply_finished(self) -> None:
        self._emit({"type": "reply.finished"})
        self._emit({"type": "status.change", "status": "idle"})

    def post_pause_asr(self) -> None:
        self._emit({"type": "asr.state", "running": False})

    def post_tts_play(
        self, character_name: str, audio_path: str, *,
        playback_id: str = "", volume: float | None = None,
    ) -> None:
        resolved_volume = volume
        if resolved_volume is None:
            resolved_volume = 1.0
            try:
                character = get_character_by_name(character_name)
                if character is not None:
                    resolved_volume = float(getattr(character, "speech_volume", 1.0) or 1.0)
            except Exception:
                pass
        payload: dict[str, Any] = {
            "type": "tts.play", "characterName": str(character_name or ""),
            "url": self._media_url(audio_path), "volume": min(1.0, max(0.0, float(resolved_volume))),
        }
        if playback_id:
            payload["playbackId"] = str(playback_id)
        self._emit(payload)

    def post_tts_skip(self, *, playback_id: str = "") -> None:
        payload = {"type": "tts.skip"}
        if playback_id:
            payload["playbackId"] = str(playback_id)
        self._emit(payload)

    def post_session_closed(self, reason: str = "聊天会话已结束。") -> None:
        self._emit({"type": "session.closed", "reason": str(reason or "聊天会话已结束。")})

    def set_user_display_name(self, name: str) -> None:
        super().set_user_display_name(name)
        value = str(name or "").strip()
        if value:
            self._emit({"type": "user.display_name.change", "name": value})

    # --- Effect, ambient, dialog, and sprite delegation ---

    def play_sound_effect(self, sound_effect_path: str) -> None:
        self._effects.play_sound_effect(sound_effect_path)

    def show_image_effect(self, keyword: str, image_effect_path: str) -> None:
        self._effects.show_image_effect(keyword, image_effect_path)

    def start_loop_effect(self, keyword: str, audio_path: str) -> None:
        self._effects.start_loop_effect(keyword, audio_path)

    def stop_loop_effect(self, keyword: str) -> None:
        self._effects.stop_loop_effect(keyword)

    def stop_all_loop_effects(self) -> None:
        self._effects.stop_all_loop_effects()

    def start_ambient_effect(self, keyword: str, asset: Any, layer: str = "") -> bool:
        return self._ambient.start_ambient_effect(keyword, asset, layer=layer)

    def stop_ambient_effect(self, keyword: str) -> bool:
        return self._ambient.stop_ambient_effect(keyword)

    def stop_all_ambient_effects(self) -> None:
        self._ambient.stop_all_ambient_effects()

    def restore_ambient_directives(self, directives: Any) -> None:
        self._ambient.restore_ambient_directives(directives)

    def resolve_effect(
        self, effect: str, args: Dict[str, Any], after_dialog: bool = False
    ) -> bool:
        return self._effects.resolve_effect(effect, args, after_dialog=after_dialog)

    def queue_player_portrait(self, name: str, sprite_id: int) -> None:
        self._dialog.queue_player_portrait(name, sprite_id)

    def _apply_player_portrait_for_dialog(self, name: str, speech: str) -> None:
        self._dialog.apply_player_portrait_for_dialog(name, speech)

    def update_dialog(
        self, name: str, speech: str, color: str, is_system: bool = True,
        voice_id: str = "", dialog_id: str = "", *, animate: bool | None = None,
    ) -> None:
        self._dialog.update_dialog(
            name, speech, color, is_system, voice_id=voice_id, dialog_id=dialog_id, animate=animate
        )

    def record_user_message(self, text: str) -> None:
        self._dialog.record_user_message(text)

    def post_dialog_html(
        self, full_html: str, *, append_history: bool = True,
        speaker: str = "", color: str = "", is_system: bool = True,
    ) -> None:
        self._dialog.post_dialog_html(
            full_html, append_history=append_history, speaker=speaker, color=color, is_system=is_system
        )

    def _get_or_create_sprite_slot(self, character_name: str) -> int:
        return self._sprites.get_or_create_slot(character_name)

    def _resolve_replay_sprite(self, character: Any, preferred_index: int | None):
        return self._sprites.resolve_replay_sprite(character, preferred_index)

    def update_sprite(
        self, character_name: str, sprite_id: int | None, *,
        slot: int | None = None, display_name: str = "",
    ) -> None:
        self._sprites.update_sprite(character_name, sprite_id, slot=slot, display_name=display_name)

    def update_player_portrait(self, character_name: str, sprite_id: int) -> None:
        self._sprites.update_player_portrait(character_name, sprite_id)

    def update_sprite_from_path(
        self, image_path: str, *, character_name: str = "", scale: float = 1.0
    ) -> bool:
        return self._sprites.update_sprite_from_path(
            image_path, character_name=character_name, scale=scale
        )

    def remove_character_sprite(self, character_name: str) -> None:
        self._sprites.remove_character_sprite(character_name)

    def post_sprite_reaction(
        self, character_name: str, text: str, *, duration_ms: int = 3600
    ) -> None:
        self._sprites.post_sprite_reaction(character_name, text, duration_ms=duration_ms)

    def post_sprite_motion(self, character_name: str, motion: str) -> None:
        self._sprites.post_sprite_motion(character_name, motion)


__all__ = [
    "HeadlessUIUpdateManager", "IMAGE_EFFECT_DURATION_MS", "SOUND_EFFECTS_PATH",
    "StreamingUIUpdateManager", "_format_dialog_html", "_format_token_count",
    "_format_user_html", "_native_tool_confirmation_options", "_safe_css_color",
    "bind_presentation_character_catalog", "format_context_token_estimate",
    "get_character_by_name", "resolve_character_visual",
]
