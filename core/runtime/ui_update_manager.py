"""
集中定义从 worker 发往主界面的 Qt 信号，以及在此之上封装的对话/立绘/BGM/特效等操作。

这类方法从 UI 工作线程调用，内部通过信号跨线程更新主界面；BGM/音效使用 pygame，与 UIWorker 中的对话通道分离。
"""

from __future__ import annotations

import traceback
import html
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, MutableSequence, Optional

if TYPE_CHECKING:
    from core.runtime.event_sink import ChatEventSink

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    class QObject:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _NoopSignal:
        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def emit(self, *args: Any, **kwargs: Any) -> None:
            pass

    def Signal(*args: Any, **kwargs: Any) -> _NoopSignal:
        return _NoopSignal()

from core.messaging.stat_payload import format_stats_html, parse_stat_payload
from core.sprite.chat_history import serialize_chat_history_entries

SOUND_EFFECT_CHANNEL_ID = 6
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


class _EmptyImagePayload:
    size = 0


def _load_image_rgba_array(image_path: str) -> Optional[Any]:
    try:
        import numpy as np
    except ModuleNotFoundError:
        return None

    from PySide6.QtGui import QImage

    image = QImage(str(Path(image_path)))
    if image.isNull():
        return None
    image_format = getattr(getattr(QImage, "Format", QImage), "Format_RGBA8888")
    rgba_image = image.convertToFormat(image_format)
    width = rgba_image.width()
    height = rgba_image.height()
    bytes_per_line = rgba_image.bytesPerLine()
    image_bytes = rgba_image.bits()
    array = np.frombuffer(image_bytes, dtype=np.uint8).reshape((height, bytes_per_line))
    return array[:, : width * 4].reshape((height, width, 4)).copy()


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

    def post_options(self, option_list: List[str]) -> None:
        if option_list:
            print(" / ".join(str(x) for x in option_list))

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

    def post_tts_play(self, character_name: str, audio_path: str) -> None:
        pass

    def post_tts_skip(self) -> None:
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


class UIUpdateManager(QObject):
    update_sprite_signal = Signal(object, str, float)  # 图像, 角色名, 缩放
    update_dialog_signal = Signal(str)
    update_notification_signal = Signal(str)
    update_busy_bar_signal = Signal(str, float)  # 文案, 显示秒数（<=0 则不定时隐藏）；空文案表示关闭
    update_option_signal = Signal(list)
    update_value_signal = Signal(str)
    update_context_token_estimate_signal = Signal(str)
    update_bg = Signal(str)
    update_cg = Signal(str)
    llm_reply_finished_signal = Signal()
    pause_asr_signal = Signal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        chat_history: Optional[MutableSequence[str]] = None,
        bg_group: Optional[List] = None,
    ) -> None:
        super().__init__(parent)
        self.chat_history: MutableSequence[str] = chat_history if chat_history is not None else []
        self.bg_group: List = list(bg_group or [])
        self.current_bgm_path: Optional[str] = None
        self.current_background_path: Optional[str] = None
        self.user_display_name: str = "你"
        self._looping_effects: dict[str, Any] = {}  # keyword → Sound对象

    # --- 低层：仅发信号 ---

    def post_sprite_update(self, image: Any, character_name: str, scale: float) -> None:
        self.update_sprite_signal.emit(image, character_name, scale)

    def post_dialog(self, formatted_html: str) -> None:
        self.update_dialog_signal.emit(formatted_html)

    def post_notification(self, text: str) -> None:
        self.update_notification_signal.emit(text)

    def post_busy_bar(self, text: str, duration_seconds: float = 3.0) -> None:
        """主线程：在聊天窗底栏上方显示加载条。duration_seconds<=0 时显示到 ``hide_busy_bar`` 为止。"""
        self.update_busy_bar_signal.emit(text, float(duration_seconds))

    def hide_busy_bar(self) -> None:
        self.update_busy_bar_signal.emit("", 0.0)

    def post_options(self, option_list: List[str]) -> None:
        self.update_option_signal.emit(option_list)

    def post_numeric_value(self, text: str) -> None:
        stats = parse_stat_payload(text)
        self.update_value_signal.emit(format_stats_html(stats) if stats else text)

    def post_context_token_estimate(self, estimate: Dict[str, Any]) -> None:
        self.update_context_token_estimate_signal.emit(format_context_token_estimate(estimate))

    def post_background(self, path: str) -> None:
        self.current_background_path = path or None
        self.update_bg.emit(path)

    def post_cg(self, path: str) -> None:
        self.update_cg.emit(path)

    def post_llm_reply_finished(self) -> None:
        try:
            from asr.asr_adapter import get_asr_log

            get_asr_log().info("UIUpdateManager: post_llm_reply_finished → llm_reply_finished_signal")
        except Exception:
            pass
        self.llm_reply_finished_signal.emit()

    def post_pause_asr(self) -> None:
        try:
            from asr.asr_adapter import get_asr_log

            get_asr_log().info("UIUpdateManager: post_pause_asr → pause_asr_signal")
        except Exception:
            pass
        self.pause_asr_signal.emit()

    def post_tts_play(self, character_name: str, audio_path: str) -> None:
        return None

    def post_tts_skip(self) -> None:
        return None

    def post_session_closed(self, reason: str = "聊天会话已结束。") -> None:
        self.post_notification(reason)

    def set_user_display_name(self, name: str) -> None:
        value = str(name or "").strip()
        if value:
            self.user_display_name = value

    # --- 高层：业务组装（原 UIWorker 上的逻辑） ---

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        formatted = _format_dialog_html(name, speech, color, is_system)
        self.chat_history.append(formatted)
        self.post_dialog(formatted)

    def record_user_message(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        self.chat_history.append(_format_user_html(value))

    def update_sprite(self, character_name: str, sprite_id: int) -> None:
        try:
            character_config = get_character_by_name(character_name)
            if character_config is None:
                raise ValueError(f"未找到角色配置: {character_name}")
            image_path = str(Path(character_config.sprites[sprite_id]["path"]))
            image = _load_image_rgba_array(image_path)
            if image is None:
                print(f"UIUpdateManager: 无法加载图片: {image_path}")
                return
            self.post_sprite_update(image, character_name, character_config.sprite_scale)
        except Exception as e:
            traceback.print_exc()
            print(f"UIUpdateManager: 加载图片时出错: {e}")

    def update_sprite_from_path(
        self,
        image_path: str,
        *,
        character_name: str = "",
        scale: float = 1.0,
    ) -> bool:
        image = _load_image_rgba_array(image_path)
        if image is None:
            print(f"UIUpdateManager: 无法加载图片: {image_path}")
            return False
        self.post_sprite_update(image, character_name, scale)
        return True

    def remove_character_sprite(self, character_name: str) -> None:
        self.post_sprite_update(_EmptyImagePayload(), character_name, 1.0)

    def switch_bgm(self, new_bgm_path: str) -> None:
        try:
            import pygame
        except ModuleNotFoundError:
            return
        if not new_bgm_path or not Path(new_bgm_path).exists():
            return
        new_bgm_path = Path(new_bgm_path).as_posix()
        if new_bgm_path == self.current_bgm_path:
            if pygame.mixer.music.get_busy():
                return
            pygame.mixer.music.play(-1)
            print(f"BGM: 重新开始播放：{new_bgm_path}")
            return
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.music.load(new_bgm_path)
            volume = _get_config_manager().config.system_config.music_volumn / 100
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play(-1)
            self.current_bgm_path = new_bgm_path
        except pygame.error as e:
            print(f"BGM: 切换背景音乐失败 ({new_bgm_path}): {e}")
            self.current_bgm_path = None
        except Exception:
            print("切换bgm时发生错误")
            traceback.print_exc()

    LOOP_EFFECT_CHANNEL_ID = 5

    def play_sound_effect(self, sound_effect_path: str) -> None:
        try:
            import pygame
        except ModuleNotFoundError:
            return
        if not Path(sound_effect_path).exists():
            print(f"音效文件不存在: {sound_effect_path}")
            return
        try:
            effect_sound = pygame.mixer.Sound(sound_effect_path)
            sound_channel = pygame.mixer.Channel(SOUND_EFFECT_CHANNEL_ID)
            sound_channel.play(effect_sound)
        except Exception as e:
            print(f"播放音效失败: {e}")

    def start_loop_effect(self, keyword: str, audio_path: str) -> None:
        """循环播放特效音（用于持续性环境音效如雨声、风声）"""
        if not Path(audio_path).exists():
            print(f"[Effect] 循环音效文件不存在: {audio_path}")
            return
        # 如果已在循环同一音效则跳过
        if keyword in self._looping_effects:
            return
        try:
            effect_sound = pygame.mixer.Sound(audio_path)
            loop_channel = pygame.mixer.Channel(self.LOOP_EFFECT_CHANNEL_ID)
            loop_channel.play(effect_sound, loops=-1)
            self._looping_effects[keyword] = effect_sound
            print(f"[Effect] 开始循环: {keyword!r} → {audio_path}")
        except Exception as e:
            print(f"[Effect] 循环播放失败: {e}")

    def stop_loop_effect(self, keyword: str) -> None:
        """停止指定关键词的循环特效"""
        if keyword not in self._looping_effects:
            return
        try:
            loop_channel = pygame.mixer.Channel(self.LOOP_EFFECT_CHANNEL_ID)
            loop_channel.stop()
            del self._looping_effects[keyword]
            print(f"[Effect] 停止循环: {keyword!r}")
        except Exception as e:
            print(f"[Effect] 停止循环失败: {e}")

    def stop_all_loop_effects(self) -> None:
        """停止所有循环特效"""
        try:
            loop_channel = pygame.mixer.Channel(self.LOOP_EFFECT_CHANNEL_ID)
            loop_channel.stop()
            self._looping_effects.clear()
        except Exception:
            pass

    def check_and_play_keyword_effects(self, dialog_text: str) -> None:
        """检测对话文本中的关键词，播放匹配的特效音频。"""
        if not dialog_text:
            return
        try:
            from core.runtime.app_runtime import get_app_runtime
            rt = get_app_runtime()
            keyword_map = getattr(rt, "effect_keyword_map", {}) or {}
            if not keyword_map:
                return
            for keyword, audio_path in keyword_map.items():
                if keyword and keyword in dialog_text:
                    print(f"[Effect] 关键词匹配: {keyword!r} 在对话中 → 播放 {audio_path}")
                    self.play_sound_effect(audio_path)
        except Exception as e:
            import traceback
            print(f"[Effect] 关键词特效检测失败: {e}")
            traceback.print_exc()

    def resolve_effect(self, effect: str, args: Dict[str, Any], after_dialog: bool = False) -> None:
        if not effect:
            return
        try:
            match effect:
                case "LEAVE":
                    if after_dialog:
                        self.remove_character_sprite(args.get("character_name"))
                case _:
                    # 解析前缀：loop: / stop: / before: / after: / 无前缀
                    timing = "before"
                    raw = effect

                    # loop/stop 不受 timing 限制
                    if raw.startswith("loop:"):
                        self._play_by_keyword(raw[5:], mode="loop")
                        return
                    if raw.startswith("stop:"):
                        self._play_by_keyword(raw[5:], mode="stop")
                        return

                    if raw.startswith("before:"):
                        timing = "before"
                        raw = raw[7:]
                    elif raw.startswith("after:"):
                        timing = "after"
                        raw = raw[6:]

                    # 时机不匹配则跳过
                    if (timing == "before" and after_dialog) or (timing == "after" and not after_dialog):
                        return
                    self._play_by_keyword(raw, mode="once")
        except Exception as e:
            print("播放特效失败", e)

    def _play_by_keyword(self, keyword: str, mode: str) -> None:
        """按关键词查找音频并播放。mode: once / loop / stop"""
        # 1) 旧硬编码系统特效
        path = SOUND_EFFECTS_PATH.get(keyword.upper(), None)
        if path:
            if mode == "loop":
                self.start_loop_effect(keyword, path)
            elif mode == "stop":
                self.stop_loop_effect(keyword)
            else:
                self.play_sound_effect(path)
            return
        # 2) 加载的特效方案关键词映射
        try:
            from core.runtime.app_runtime import get_app_runtime
            rt = get_app_runtime()
            keyword_map = getattr(rt, "effect_keyword_map", {}) or {}
            for kw, audio_path in keyword_map.items():
                if kw and kw.lower() == keyword.lower():
                    if mode == "loop":
                        print(f"[Effect] LLM触发: loop:{keyword!r} → {audio_path}")
                        self.start_loop_effect(keyword, audio_path)
                    elif mode == "stop":
                        print(f"[Effect] LLM触发: stop:{keyword!r}")
                        self.stop_loop_effect(keyword)
                    else:
                        print(f"[Effect] LLM触发: {keyword!r} → {audio_path}")
                        self.play_sound_effect(audio_path)
                    return
        except Exception:
            pass


def connect_to_desktop_window(ui: UIUpdateManager, window: Any) -> None:
    """将 worker 侧 UI 更新信号全部接到主窗口上的对应槽（原 main_sprite 中分散的连接）。"""
    ui.update_sprite_signal.connect(window.update_image)
    ui.update_dialog_signal.connect(window.setDisplayWords)
    ui.update_notification_signal.connect(window.setNotification)
    ui.update_busy_bar_signal.connect(window.setBusyBar)
    ui.update_option_signal.connect(window.setOptions)
    ui.update_value_signal.connect(window.update_numeric_info)
    ui.update_context_token_estimate_signal.connect(window.setContextTokenEstimate)
    ui.update_bg.connect(window.setBackgroundImage)
    ui.update_cg.connect(window.show_cg_image)
    # 与主窗口均为 PySide6 Signal 时可直连中继。
    ui.llm_reply_finished_signal.connect(window.llm_reply_finished)
    ui.pause_asr_signal.connect(window.pause_asr_signal)


class StreamingUIUpdateManager(HeadlessUIUpdateManager):
    """把演出输出序列化成 chat stage 事件流的无 Qt 实现（M0 占位骨架）。

    复刻 ``connect_to_desktop_window`` 的下行契约：生产者（``core/handlers`` 的
    ``*UiHandler`` 等）照旧调用 ``post_*``/``update_*``，本类把每次调用翻译成事件 dict
    并 ``emit`` 到 ``ChatEventSink``。详见设计文档"演出方法→事件映射"表。

    M0：事件映射搭好骨架；立绘 URL 转换、CG 显隐区分、token 估算等在 M2 补全。
    """

    def __init__(
        self,
        sink: "ChatEventSink",
        chat_history: Optional[MutableSequence[str]] = None,
        bg_group: Optional[List] = None,
        max_sprite_slots: int = 3,
    ) -> None:
        super().__init__(chat_history=chat_history)
        self._sink = sink
        self.bg_group = list(bg_group or [])
        try:
            normalized_slot_count = int(max_sprite_slots)
        except (TypeError, ValueError):
            normalized_slot_count = 3
        self.max_sprite_slots = max(1, normalized_slot_count)
        self._sprite_lru: OrderedDict[str, int] = OrderedDict()

    def _get_or_create_sprite_slot(self, character_name: str) -> int:
        """Mirror the legacy Qt SpritePanel character-to-slot LRU."""
        if character_name in self._sprite_lru:
            slot = self._sprite_lru.pop(character_name)
            self._sprite_lru[character_name] = slot
            return slot

        used_slots = set(self._sprite_lru.values())
        if len(used_slots) < self.max_sprite_slots:
            slot = next(index for index in range(self.max_sprite_slots) if index not in used_slots)
        else:
            _oldest_character, slot = self._sprite_lru.popitem(last=False)
        self._sprite_lru[character_name] = slot
        return slot

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

    def post_options(self, option_list: List[str]) -> None:
        options = [str(x) for x in (option_list or [])]
        if options:
            self._sink.emit({"type": "options.show", "options": options})
        else:
            self._sink.emit({"type": "options.clear"})
        self.sync_history_entries()

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

    def post_tts_play(self, character_name: str, audio_path: str) -> None:
        self._sink.emit(
            {
                "type": "tts.play",
                "characterName": str(character_name or ""),
                "url": self._media_url(audio_path),
            }
        )

    def post_tts_skip(self) -> None:
        self._sink.emit({"type": "tts.skip"})

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
        display_slot = self._get_or_create_sprite_slot(character_name)
        self._sink.emit(
            {
                "type": "sprite.show",
                "characterName": character_name,
                "url": self._media_url(image_path),
                "scale": scale,
                "slot": display_slot,
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
                "slot": self._get_or_create_sprite_slot(resolved_character_name),
            }
        )
        return True

    def remove_character_sprite(self, character_name: str) -> None:
        self._sprite_lru.pop(character_name, None)
        self._sink.emit({"type": "sprite.remove", "characterName": character_name})

    def resolve_effect(self, effect: str, args: Dict[str, Any], after_dialog: bool = False) -> None:
        if str(effect or "").upper() == "LEAVE" and after_dialog:
            self.remove_character_sprite(str(args.get("character_name") or ""))


def connect_to_stream_sink(ui: UIUpdateManager, sink: "ChatEventSink") -> None:
    """把 ``UIUpdateManager`` 的 10 个输出信号接到事件 sink（Option B：与原生窗口并行输出，用于 M2 观察期比对）。

    需要存活的 ``QApplication``。M5 切默认后改用无 Qt 的 ``StreamingUIUpdateManager``（Option A）。
    """
    mirror = StreamingUIUpdateManager(sink, chat_history=ui.chat_history, bg_group=ui.bg_group)
    mirror.current_background_path = ui.current_background_path
    mirror.current_bgm_path = ui.current_bgm_path
    mirror.sync_history_entries()

    original_update_dialog = ui.update_dialog
    original_record_user_message = ui.record_user_message
    original_update_sprite = ui.update_sprite
    original_update_sprite_from_path = ui.update_sprite_from_path
    original_remove_character_sprite = ui.remove_character_sprite
    original_post_notification = ui.post_notification
    original_post_busy_bar = ui.post_busy_bar
    original_hide_busy_bar = ui.hide_busy_bar
    original_post_options = ui.post_options
    original_post_numeric_value = ui.post_numeric_value
    original_post_context_token_estimate = ui.post_context_token_estimate
    original_post_background = ui.post_background
    original_switch_bgm = ui.switch_bgm
    original_post_cg = ui.post_cg
    original_post_llm_reply_finished = ui.post_llm_reply_finished
    original_post_pause_asr = ui.post_pause_asr
    original_post_tts_play = getattr(ui, "post_tts_play", None)
    original_post_tts_skip = getattr(ui, "post_tts_skip", None)
    original_post_session_closed = getattr(ui, "post_session_closed", None)
    original_set_user_display_name = getattr(ui, "set_user_display_name", None)

    def update_dialog(name: str, speech: str, color: str, is_system: bool = True) -> None:
        original_update_dialog(name, speech, color, is_system)
        mirror.post_dialog_html(
            _format_dialog_html(name, speech, color, is_system),
            append_history=False,
            speaker=name or "",
            color=color or "",
            is_system=is_system,
        )

    def record_user_message(text: str) -> None:
        original_record_user_message(text)
        mirror.sync_history_entries()

    def update_sprite(character_name: str, sprite_id: int) -> None:
        original_update_sprite(character_name, sprite_id)
        mirror.update_sprite(character_name, sprite_id)

    def update_sprite_from_path(
        image_path: str,
        *,
        character_name: str = "",
        scale: float = 1.0,
    ) -> bool:
        ok = original_update_sprite_from_path(image_path, character_name=character_name, scale=scale)
        if ok:
            mirror.update_sprite_from_path(image_path, character_name=character_name, scale=scale)
        return ok

    def remove_character_sprite(character_name: str) -> None:
        original_remove_character_sprite(character_name)
        mirror.remove_character_sprite(character_name)

    def post_notification(text: str) -> None:
        original_post_notification(text)
        mirror.post_notification(text)

    def post_busy_bar(text: str, duration_seconds: float = 3.0) -> None:
        original_post_busy_bar(text, duration_seconds)
        mirror.post_busy_bar(text, duration_seconds)

    def hide_busy_bar() -> None:
        original_hide_busy_bar()
        mirror.hide_busy_bar()

    def post_options(option_list: List[str]) -> None:
        original_post_options(option_list)
        mirror.post_options(option_list)

    def post_numeric_value(text: str) -> None:
        original_post_numeric_value(text)
        mirror.post_numeric_value(text)

    def post_context_token_estimate(estimate: Dict[str, Any]) -> None:
        original_post_context_token_estimate(estimate)
        mirror.post_context_token_estimate(estimate)

    def post_background(path: str) -> None:
        original_post_background(path)
        mirror.post_background(path)

    def switch_bgm(path: str) -> None:
        original_switch_bgm(path)
        mirror.switch_bgm(path)

    def post_cg(path: str) -> None:
        original_post_cg(path)
        mirror.post_cg(path)

    def post_llm_reply_finished() -> None:
        original_post_llm_reply_finished()
        mirror.post_llm_reply_finished()

    def post_pause_asr() -> None:
        original_post_pause_asr()
        mirror.post_pause_asr()

    def post_tts_play(character_name: str, audio_path: str) -> None:
        if callable(original_post_tts_play):
            original_post_tts_play(character_name, audio_path)
        mirror.post_tts_play(character_name, audio_path)

    def post_tts_skip() -> None:
        if callable(original_post_tts_skip):
            original_post_tts_skip()
        mirror.post_tts_skip()

    def post_session_closed(reason: str = "聊天会话已结束。") -> None:
        if callable(original_post_session_closed):
            original_post_session_closed(reason)
        mirror.post_session_closed(reason)

    def set_user_display_name(name: str) -> None:
        if callable(original_set_user_display_name):
            original_set_user_display_name(name)
        mirror.set_user_display_name(name)

    ui.update_dialog = update_dialog
    ui.record_user_message = record_user_message
    ui.update_sprite = update_sprite
    ui.update_sprite_from_path = update_sprite_from_path
    ui.remove_character_sprite = remove_character_sprite
    ui.post_notification = post_notification
    ui.post_busy_bar = post_busy_bar
    ui.hide_busy_bar = hide_busy_bar
    ui.post_options = post_options
    ui.post_numeric_value = post_numeric_value
    ui.post_context_token_estimate = post_context_token_estimate
    ui.post_background = post_background
    ui.switch_bgm = switch_bgm
    ui.post_cg = post_cg
    ui.post_llm_reply_finished = post_llm_reply_finished
    ui.post_pause_asr = post_pause_asr
    ui.post_tts_play = post_tts_play
    ui.post_tts_skip = post_tts_skip
    ui.post_session_closed = post_session_closed
    ui.set_user_display_name = set_user_display_name
