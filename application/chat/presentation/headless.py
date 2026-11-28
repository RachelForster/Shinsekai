"""Console/no-op UI presentation facade for workflows without a desktop window."""

from __future__ import annotations

import re
from typing import Any, Dict, List, MutableSequence, Optional

from .formatting import (
    _format_dialog_html,
    _format_user_html,
    _native_tool_confirmation_options,
)


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

    def post_options(
        self, option_list: List[Any], *, selected_index: int | None = None
    ) -> None:
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

    def post_background(self, path: str, *, transition: str = "") -> None:
        del transition
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

    def set_player_character(self, name: str) -> None:
        self.player_character = str(name or "").strip()
        if self.player_character:
            self.set_user_display_name(self.player_character)

    def update_dialog(
        self,
        name: str,
        speech: str,
        color: str,
        is_system: bool = True,
        voice_id: str = "",
    ) -> None:
        formatted = _format_dialog_html(name, speech, color, is_system)
        if re.fullmatch(r"[0-9a-f]{32}", voice_id):
            formatted = formatted.replace("<p ", f"<p data-voice-id='{voice_id}' ", 1)
        if str(speech or "").strip() or str(name or "").strip():
            self.chat_history.append(formatted)
            print(f"{name}: {speech}" if name else str(speech or ""))

    def record_user_message(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        self.chat_history.append(_format_user_html(value))
        try:
            print(f"你: {value}")
        except UnicodeEncodeError:
            print(
                f"你: {value}".encode("ascii", errors="backslashreplace").decode("ascii")
            )

    def update_sprite(
        self,
        character_name: str,
        sprite_id: int | None,
        *,
        slot: int | None = None,
        display_name: str = "",
    ) -> None:
        pass

    def post_sprite_reaction(
        self,
        character_name: str,
        text: str,
        *,
        duration_ms: int = 3600,
    ) -> None:
        pass

    def post_sprite_motion(self, character_name: str, motion: str) -> None:
        pass

    def update_player_portrait(self, character_name: str, sprite_id: int) -> None:
        pass

    def switch_bgm(self, new_bgm_path: str) -> None:
        self.current_bgm_path = new_bgm_path or None
        if new_bgm_path:
            print(f"bgm: {new_bgm_path}")

    def resolve_effect(self, *args: Any, **kwargs: Any) -> bool:
        return False
