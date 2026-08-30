"""Framework-neutral presentation adapters for headless and React/Tauri chat."""

from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, MutableSequence, Optional

if TYPE_CHECKING:
    from application.runtime.event_sink import ChatEventSink

from core.messaging.stat_payload import parse_stat_payload
from application.chat.history_state import serialize_chat_history_entries

SOUND_EFFECTS_PATH = {
    "DISAPPOINTED": "./assets/system/sound/disappointed.wav",
    "SHOCKED": "./assets/system/sound/shocked.wav",
    "ATTENTION": "./assets/system/sound/attention.wav",
}

_config_manager = None


def _get_config_manager():
    global _config_manager
    if _config_manager is None:
        from config.config_manager import ConfigManager

        _config_manager = ConfigManager()
    return _config_manager


def get_character_by_name(name: str):
    try:
        return _get_config_manager().get_character_by_name(name)
    except ModuleNotFoundError:
        return None


def _native_tool_confirmation_options(
    *,
    confirmation_id: str,
    tool_name: str,
    detail: str = "",
) -> list[dict[str, str]]:
    from i18n import tr

    confirm_label = tr("tool_confirmation.confirm", tool=tool_name)
    if detail:
        confirm_label = f"{confirm_label}\n{detail}"
    base = {
        "confirmationId": str(confirmation_id or ""),
        "kind": "tool-confirmation",
    }
    return [
        {
            **base,
            "action": "cancel",
            "label": tr("common.cancel"),
        },
        {
            **base,
            "action": "confirm",
            "label": confirm_label,
        },
    ]


def _format_token_count(value: Any) -> str:
    try:
        count = max(0, int(value or 0))
    except (TypeError, ValueError):
        count = 0
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}m"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def format_context_token_estimate(estimate: Dict[str, Any]) -> str:
    """Compact one-line token budget status for the desktop overlay."""
    return (
        "tokens "
        f"sys {_format_token_count(estimate.get('system_prompt_tokens'))} | "
        f"hist {_format_token_count(estimate.get('history_tokens'))} | "
        f"tools {_format_token_count(estimate.get('tool_definition_tokens'))} | "
        f"total {_format_token_count(estimate.get('estimated_total_tokens'))}"
    )


def _format_dialog_html(name: str, speech: str, color: str, is_system: bool) -> str:
    separator = "\uff1a"
    safe_name = html.escape(str(name or ""), quote=False)
    safe_speech = html.escape(str(speech or ""), quote=False).replace("\n", "<br>")
    safe_color = _safe_css_color(color, "#84C2D5" if is_system else "#FFFFFF")
    if is_system:
        return (
            f"<p style='line-height: 135%; letter-spacing: 2px; color:{safe_color};'>"
            f"<b>{safe_name}</b>{separator}{safe_speech}</p>"
        )
    return (
        f"<p style='line-height: 135%; letter-spacing: 2px;'>"
        f"<b style='color:{safe_color};'>{safe_name}</b>{separator}{safe_speech}</p>"
    )


def _format_user_html(text: str) -> str:
    created_at = int(time.time() * 1000)
    safe_text = html.escape(str(text or ""), quote=False).replace("\n", "<br>")
    return (
        f"<p data-created-at='{created_at}' style='line-height: 135%; letter-spacing: 2px; color:white;'>"
        f"<b style='color:white;'>你</b>: {safe_text}</p>"
    )


def _safe_css_color(value: Any, fallback: str) -> str:
    color = str(value or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", color):
        return color
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", color):
        return color
    if re.fullmatch(r"rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)", color):
        return color
    return fallback


class HeadlessUIUpdateManager:
    """Console/no-op UI facade for workflows that run without a desktop window."""

    def __init__(self, chat_history: Optional[MutableSequence[str]] = None) -> None:
        self.chat_history: MutableSequence[str] = (
            chat_history if chat_history is not None else []
        )
        self.current_bgm_path: Optional[str] = None
        self.current_background_path: Optional[str] = None
        self.bg_group: List = []
        self.user_display_name: str = "你"

    def post_notification(self, text: str) -> None:
        if text:
            print(text)

    def post_busy_bar(self, text: str, timeout: float = 0.0) -> None:
        if text:
            print(text)

    def hide_busy_bar(self) -> None:
        pass

    def post_options(self, option_list: List[Any]) -> None:
        if option_list:
            print(" / ".join(str(x) for x in option_list))

    def post_tool_confirmation(
        self,
        *,
        confirmation_id: str,
        tool_name: str,
        detail: str = "",
        risk: str = "high",
    ) -> None:
        del risk
        self.post_options(
            _native_tool_confirmation_options(
                confirmation_id=confirmation_id,
                tool_name=tool_name,
                detail=detail,
            )
        )

    def clear_tool_confirmation(self, confirmation_id: str) -> None:
        del confirmation_id
        self.post_options([])

    def post_numeric_value(self, text: str) -> None:
        if text:
            print(text)

    def post_context_token_estimate(self, estimate: Dict[str, Any]) -> None:
        pass

    def post_background(self, path: str) -> None:
        self.current_background_path = path or None
        if path:
            print(f"background: {path}")

    def post_cg(self, path: str) -> None:
        if path:
            print(f"cg: {path}")

    def post_llm_reply_finished(self) -> None:
        pass

    def post_pause_asr(self) -> None:
        pass

    def post_tts_play(
        self,
        character_name: str,
        audio_path: str,
        *,
        playback_id: str = "",
        volume: float | None = None,
    ) -> None:
        pass

    def post_tts_skip(self, *, playback_id: str = "") -> None:
        pass

    def post_session_closed(self, reason: str = "聊天会话已结束。") -> None:
        self.post_notification(reason)

    def set_user_display_name(self, name: str) -> None:
        value = str(name or "").strip()
        if value:
            self.user_display_name = value

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        formatted = _format_dialog_html(name, speech, color, is_system)
        if str(speech or "").strip() or str(name or "").strip():
            self.chat_history.append(formatted)
            print(f"{name}: {speech}" if name else str(speech or ""))

    def record_user_message(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        self.chat_history.append(_format_user_html(value))
        print(f"你: {value}")

    def update_sprite(self, character_name: str, sprite_id: int) -> None:
        pass

    def switch_bgm(self, new_bgm_path: str) -> None:
        self.current_bgm_path = new_bgm_path or None
        if new_bgm_path:
            print(f"bgm: {new_bgm_path}")

    def resolve_effect(self, *args: Any, **kwargs: Any) -> None:
        pass


class StreamingUIUpdateManager(HeadlessUIUpdateManager):
    """把演出输出序列化成 chat stage 事件流的无 Qt 实现（M0 占位骨架）。

    复刻已退役桌面 presenter 的下行契约：生产者（application handlers 的
    ``*UiHandler`` 等）照旧调用 ``post_*``/``update_*``，本类把每次调用翻译成事件 dict
    并 ``emit`` 到 ``ChatEventSink``。详见设计文档"演出方法→事件映射"表。

    M0：事件映射搭好骨架；立绘 URL 转换、CG 显隐区分、token 估算等在 M2 补全。
    """

    def __init__(
        self,
        sink: "ChatEventSink",
        chat_history: Optional[MutableSequence[str]] = None,
        bg_group: Optional[List] = None,
    ) -> None:
        super().__init__(chat_history=chat_history)
        self._sink = sink
        self.bg_group = list(bg_group or [])
        self._looping_effects: dict[str, str] = {}
        self.audio_playback_owner = "frontend"

    def _media_url(self, raw_path: str) -> str:
        if hasattr(self._sink, "media_url"):
            return str(getattr(self._sink, "media_url")(raw_path) or "")
        return str(raw_path or "")

    def sync_history_entries(self) -> None:
        self._sink.emit({"type": "history.replace", "entries": serialize_chat_history_entries(list(self.chat_history))})

    # --- 低层 post_* → 事件 ---

    def post_notification(self, text: str) -> None:
        self._sink.emit({"type": "notification.change", "text": text})

    def post_busy_bar(self, text: str, timeout: float = 0.0) -> None:
        if text:
            self._sink.emit({"type": "busy.show", "text": text, "durationSeconds": float(timeout)})
        else:
            self._sink.emit({"type": "busy.hide"})

    def hide_busy_bar(self) -> None:
        self._sink.emit({"type": "busy.hide"})

    def post_options(self, option_list: List[Any]) -> None:
        options = [str(x) for x in (option_list or [])]
        if options:
            self._sink.emit({"type": "options.show", "options": options})
        else:
            self._sink.emit({"type": "options.clear"})
        self.sync_history_entries()

    def post_tool_confirmation(
        self,
        *,
        confirmation_id: str,
        tool_name: str,
        detail: str = "",
        risk: str = "high",
    ) -> None:
        normalized_risk = "medium" if str(risk).casefold() == "medium" else "high"
        self._sink.emit(
            {
                "type": "tool.confirmation.show",
                "confirmationId": str(confirmation_id or ""),
                "detail": str(detail or ""),
                "risk": normalized_risk,
                "toolName": str(tool_name or ""),
            }
        )

    def clear_tool_confirmation(self, confirmation_id: str) -> None:
        self._sink.emit(
            {
                "type": "tool.confirmation.clear",
                "confirmationId": str(confirmation_id or ""),
            }
        )

    def post_numeric_value(self, text: str) -> None:
        stats = parse_stat_payload(text)
        if stats or not str(text or "").strip():
            self._sink.emit({"type": "stats.update", "stats": stats})

    def post_context_token_estimate(self, estimate: Dict[str, Any]) -> None:
        self._sink.emit({"type": "numeric.update", "html": format_context_token_estimate(estimate)})

    def post_background(self, path: str) -> None:
        self.current_background_path = path or None
        self._sink.emit({"type": "background.change", "url": self._media_url(path)})

    def switch_bgm(self, new_bgm_path: str) -> None:
        path = str(new_bgm_path or "").strip()
        self.current_bgm_path = path or None
        self._sink.emit({"type": "bgm.change", "url": self._media_url(path)})

    def post_cg(self, path: str) -> None:
        if path:
            self._sink.emit({"type": "cg.show", "url": self._media_url(path)})
        else:
            self._sink.emit({"type": "cg.hide"})

    def post_llm_reply_finished(self) -> None:
        self._sink.emit({"type": "reply.finished"})
        self._sink.emit({"type": "status.change", "status": "idle"})

    def post_pause_asr(self) -> None:
        self._sink.emit({"type": "asr.state", "running": False})

    def post_tts_play(
        self,
        character_name: str,
        audio_path: str,
        *,
        playback_id: str = "",
        volume: float | None = None,
    ) -> None:
        resolved_volume = volume
        if resolved_volume is None:
            resolved_volume = 1.0
            try:
                character = get_character_by_name(character_name)
                if character is not None:
                    resolved_volume = float(
                        getattr(character, "speech_volume", 1.0) or 1.0
                    )
            except Exception:
                pass
        resolved_volume = min(1.0, max(0.0, float(resolved_volume)))
        payload = {
            "type": "tts.play",
            "characterName": str(character_name or ""),
            "url": self._media_url(audio_path),
            "volume": resolved_volume,
        }
        if playback_id:
            payload["playbackId"] = str(playback_id)
        self._sink.emit(payload)

    def post_tts_skip(self, *, playback_id: str = "") -> None:
        payload = {"type": "tts.skip"}
        if playback_id:
            payload["playbackId"] = str(playback_id)
        self._sink.emit(payload)

    def play_sound_effect(self, sound_effect_path: str) -> None:
        path = str(sound_effect_path or "").strip()
        if not path or not Path(path).exists():
            return
        self._sink.emit({"type": "effect.play", "url": self._media_url(path)})

    def start_loop_effect(self, keyword: str, audio_path: str) -> None:
        key = str(keyword or "").strip()
        path = str(audio_path or "").strip()
        if not key or not path or not Path(path).exists() or key in self._looping_effects:
            return
        self._looping_effects[key] = path
        self._sink.emit(
            {
                "type": "effect.loop.start",
                "key": key,
                "url": self._media_url(path),
            }
        )

    def stop_loop_effect(self, keyword: str) -> None:
        key = str(keyword or "").strip()
        if not key or key not in self._looping_effects:
            return
        self._looping_effects.pop(key, None)
        self._sink.emit({"type": "effect.loop.stop", "key": key})

    def stop_all_loop_effects(self) -> None:
        if not self._looping_effects:
            return
        self._looping_effects.clear()
        self._sink.emit({"type": "effect.loop.stop-all"})

    def post_session_closed(self, reason: str = "聊天会话已结束。") -> None:
        self._sink.emit({"type": "session.closed", "reason": str(reason or "聊天会话已结束。")})

    def set_user_display_name(self, name: str) -> None:
        super().set_user_display_name(name)
        value = str(name or "").strip()
        if value:
            self._sink.emit({"type": "user.display_name.change", "name": value})

    # --- 高层业务组装 → 事件 ---

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        formatted = _format_dialog_html(name, speech, color, is_system)
        if str(speech or "").strip() or str(name or "").strip():
            self.chat_history.append(formatted)
        self._sink.emit(
            {
                "type": "dialog.end",
                "speaker": name or "",
                "color": color or "",
                "isSystem": bool(is_system),
                "fullHtml": formatted,
            }
        )
        self.sync_history_entries()

    def record_user_message(self, text: str) -> None:
        super().record_user_message(text)
        self.sync_history_entries()

    def post_dialog_html(
        self,
        full_html: str,
        *,
        append_history: bool = True,
        speaker: str = "",
        color: str = "",
        is_system: bool = True,
    ) -> None:
        if append_history and str(full_html or "").strip():
            self.chat_history.append(full_html)
        self._sink.emit(
            {
                "type": "dialog.end",
                "speaker": speaker,
                "color": color,
                "isSystem": bool(is_system),
                "fullHtml": full_html,
            }
        )
        self.sync_history_entries()

    def update_sprite(self, character_name: str, sprite_id: int) -> None:
        try:
            character_config = get_character_by_name(character_name)
            if character_config is None:
                raise ValueError(f"未找到角色配置: {character_name}")
            sprite = character_config.sprites[sprite_id]
            image_path = str(
                Path(sprite.get("path", "")) if isinstance(sprite, dict) else Path(getattr(sprite, "path", ""))
            )
            scale = float(getattr(character_config, "sprite_scale", 1.0) or 1.0)
        except Exception as e:
            print(f"StreamingUIUpdateManager: 立绘解析失败: {e}")
            return
        self._sink.emit(
            {
                "type": "sprite.show",
                "characterName": character_name,
                "url": self._media_url(image_path),
                "scale": scale,
            }
        )

    def update_sprite_from_path(
        self,
        image_path: str,
        *,
        character_name: str = "",
        scale: float = 1.0,
    ) -> bool:
        path = str(image_path or "").strip()
        if not path:
            return False
        resolved_character_name = character_name or Path(path).stem or "initial"
        self._sink.emit(
            {
                "type": "sprite.show",
                "characterName": resolved_character_name,
                "url": self._media_url(path),
                "scale": float(scale or 1.0),
            }
        )
        return True

    def remove_character_sprite(self, character_name: str) -> None:
        self._sink.emit({"type": "sprite.remove", "characterName": character_name})

    def resolve_effect(self, effect: str, args: Dict[str, Any], after_dialog: bool = False) -> None:
        raw = str(effect or "").strip()
        if not raw:
            return
        if raw.upper() == "LEAVE" and after_dialog:
            self.remove_character_sprite(str(args.get("character_name") or ""))
            return

        mode = "once"
        if raw.startswith("loop:"):
            mode = "loop"
            raw = raw[5:]
        elif raw.startswith("stop:"):
            mode = "stop"
            raw = raw[5:]
        else:
            timing = "before"
            if raw.startswith("before:"):
                raw = raw[7:]
            elif raw.startswith("after:"):
                timing = "after"
                raw = raw[6:]
            if (timing == "before" and after_dialog) or (
                timing == "after" and not after_dialog
            ):
                return

        keyword = raw.strip()
        if not keyword:
            return
        audio_path = str(SOUND_EFFECTS_PATH.get(keyword.upper()) or "").strip()
        if not audio_path:
            try:
                from application.runtime.context import get_app_runtime

                keyword_map = getattr(get_app_runtime(), "effect_keyword_map", {}) or {}
                audio_path = next(
                    (
                        str(path or "").strip()
                        for configured_keyword, path in keyword_map.items()
                        if str(configured_keyword or "").strip().lower()
                        == keyword.lower()
                    ),
                    "",
                )
            except Exception:
                audio_path = ""
        if mode != "stop" and not audio_path:
            return
        if mode == "loop":
            self.start_loop_effect(keyword, audio_path)
        elif mode == "stop":
            self.stop_loop_effect(keyword)
        else:
            self.play_sound_effect(audio_path)
