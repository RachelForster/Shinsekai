"""
集中定义从 worker 发往主界面的 Qt 信号，以及在此之上封装的对话/立绘/BGM/特效等操作。

这类方法从 UI 工作线程调用，内部通过信号跨线程更新主界面；BGM/音效使用 pygame，与 UIWorker 中的对话通道分离。
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Dict, List, MutableSequence, Optional

import cv2
import numpy as np
import pygame
from PySide6.QtCore import QObject, Signal

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


class UIUpdateManager(QObject):
    update_sprite_signal = Signal(np.ndarray, str, float)  # 图像, 角色名, 缩放
    update_dialog_signal = Signal(str)
    update_notification_signal = Signal(str)
    update_busy_bar_signal = Signal(str, float)  # 文案, 显示秒数（<=0 则不定时隐藏）；空文案表示关闭
    update_option_signal = Signal(list)
    update_value_signal = Signal(str)
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
            image_path = Path(character_config.sprites[sprite_id]["path"]).as_posix()
            cv_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
            if cv_image is not None:
                if cv_image.shape[2] == 3:
                    cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                    alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
                    cv_image = cv2.merge([cv_image, alpha_channel])
                elif cv_image.shape[2] == 4:
                    cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
                self.post_sprite_update(cv_image, character_name, character_config.sprite_scale)
            else:
                print(f"UIUpdateManager: 无法加载图片: {image_path}")
        except Exception as e:
            traceback.print_exc()
            print(f"UIUpdateManager: 加载图片时出错: {e}")

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

    def resolve_effect(self, effect: str, args: Dict[str, Any], after_dialog: bool = False) -> None:
        try:
            match effect:
                case "LEAVE":
                    if after_dialog:
                        self.remove_character_sprite(args.get("character_name"))
                case _:
                    if not after_dialog:
                        path = SOUND_EFFECTS_PATH.get(effect.upper(), None)
                        if path:
                            self.play_sound_effect(path)
        except Exception as e:
            print("播放特效失败", e)


def connect_to_desktop_window(ui: UIUpdateManager, window: Any) -> None:
    """将 worker 侧 UI 更新信号全部接到主窗口上的对应槽（原 main_sprite 中分散的连接）。"""
    ui.update_sprite_signal.connect(window.update_image)
    ui.update_dialog_signal.connect(window.setDisplayWords)
    ui.update_notification_signal.connect(window.setNotification)
    ui.update_busy_bar_signal.connect(window.setBusyBar)
    ui.update_option_signal.connect(window.setOptions)
    ui.update_value_signal.connect(window.update_numeric_info)
    ui.update_bg.connect(window.setBackgroundImage)
    ui.update_cg.connect(window.show_cg_image)
    # 与主窗口均为 PySide6 Signal 时可直连中继。
    ui.llm_reply_finished_signal.connect(window.llm_reply_finished)
    ui.pause_asr_signal.connect(window.pause_asr_signal)
