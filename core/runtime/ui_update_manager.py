"""
集中定义从 worker 发往主界面的 Qt 信号，以及在此之上封装的对话/立绘/BGM/特效等操作。

这类方法从 UI 工作线程调用，内部通过信号跨线程更新主界面；BGM/音效使用 pygame，与 UIWorker 中的对话通道分离。
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Dict, List, MutableSequence, Optional

import numpy as np
import pygame

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

from config.config_manager import ConfigManager

SOUND_EFFECT_CHANNEL_ID = 6
SOUND_EFFECTS_PATH = {
    "DISAPPOINTED": "./assets/system/sound/disappointed.wav",
    "SHOCKED": "./assets/system/sound/shocked.wav",
    "ATTENTION": "./assets/system/sound/attention.wav",
}

_config_manager = ConfigManager()


def get_character_by_name(name: str):
    return _config_manager.get_character_by_name(name)


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


def _load_image_rgba_array(image_path: str) -> Optional[np.ndarray]:
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
    if is_system:
        return (
            f"<p style='line-height: 135%; letter-spacing: 2px; color:{color};'>"
            f"<b>{name}</b>{separator}{speech}</p>"
        )
    return (
        f"<p style='line-height: 135%; letter-spacing: 2px;'>"
        f"<b style='color:{color};'>{name}</b>{separator}{speech}</p>"
    )


class HeadlessUIUpdateManager:
    """Console/no-op UI facade for workflows that run without a desktop window."""

    def __init__(self, chat_history: Optional[MutableSequence[str]] = None) -> None:
        self.chat_history: MutableSequence[str] = (
            chat_history if chat_history is not None else []
        )
        self.current_bgm_path: Optional[str] = None
        self.bg_group: List = []

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
        if path:
            print(f"background: {path}")

    def post_cg(self, path: str) -> None:
        if path:
            print(f"cg: {path}")

    def post_llm_reply_finished(self) -> None:
        pass

    def post_pause_asr(self) -> None:
        pass

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        formatted = _format_dialog_html(name, speech, color, is_system)
        if str(speech or "").strip() or str(name or "").strip():
            self.chat_history.append(formatted)
            print(f"{name}: {speech}" if name else str(speech or ""))

    def update_sprite(self, character_name: str, sprite_id: int) -> None:
        pass

    def switch_bgm(self, new_bgm_path: str) -> None:
        self.current_bgm_path = new_bgm_path or None
        if new_bgm_path:
            print(f"bgm: {new_bgm_path}")

    def resolve_effect(self, *args: Any, **kwargs: Any) -> None:
        pass


class UIUpdateManager(QObject):
    update_sprite_signal = Signal(np.ndarray, str, float)  # 图像, 角色名, 缩放
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
        self._looping_effects: dict[str, Any] = {}  # keyword → Sound对象

    # --- 低层：仅发信号 ---

    def post_sprite_update(self, image: np.ndarray, character_name: str, scale: float) -> None:
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
        self.update_value_signal.emit(text)

    def post_context_token_estimate(self, estimate: Dict[str, Any]) -> None:
        self.update_context_token_estimate_signal.emit(format_context_token_estimate(estimate))

    def post_background(self, path: str) -> None:
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

    # --- 高层：业务组装（原 UIWorker 上的逻辑） ---

    def update_dialog(self, name: str, speech: str, color: str, is_system: bool = True) -> None:
        if is_system:
            formatted = (
                f"<p style='line-height: 135%; letter-spacing: 2px; color:{color};'>"
                f"<b>{name}</b>：{speech}</p>"
            )
        else:
            formatted = (
                f"<p style='line-height: 135%; letter-spacing: 2px;'>"
                f"<b style='color:{color};'>{name}</b>：{speech}</p>"
            )
        self.chat_history.append(formatted)
        self.post_dialog(formatted)

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
        self.post_sprite_update(np.empty((0,), dtype=np.uint8), character_name, 1.0)

    def switch_bgm(self, new_bgm_path: str) -> None:
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
            volume = _config_manager.config.system_config.music_volumn / 100
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
