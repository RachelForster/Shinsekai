"""
集中定义从 LLM / UI 等 worker 线程发往主界面的信号，避免在 QThread 子类上分散声明。

Worker 只调用本类提供的 post_* 方法，由方法内部 emit，不直接触达信号对象。

在应用主线程中创建 `UIUpdateManager` 实例，注入各 worker，并在 `connect_to_desktop_window` 中
一次性接到 `DesktopAssistantWindow` 的槽。
"""

from __future__ import annotations

from typing import Any, List, Optional

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal


class UIUpdateManager(QObject):
    update_sprite_signal = pyqtSignal(np.ndarray, str, float)  # 图像, 角色名, 缩放
    update_dialog_signal = pyqtSignal(str)
    update_notification_signal = pyqtSignal(str)
    update_option_signal = pyqtSignal(list)
    update_value_signal = pyqtSignal(str)
    update_bg = pyqtSignal(str)
    update_cg = pyqtSignal(str)
    llm_reply_finished_signal = pyqtSignal()
    pause_asr_signal = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def post_sprite_update(self, image: np.ndarray, character_name: str, scale: float) -> None:
        self.update_sprite_signal.emit(image, character_name, scale)

    def post_dialog(self, formatted_html: str) -> None:
        self.update_dialog_signal.emit(formatted_html)

    def post_notification(self, text: str) -> None:
        self.update_notification_signal.emit(text)

    def post_options(self, option_list: List[str]) -> None:
        self.update_option_signal.emit(option_list)

    def post_numeric_value(self, text: str) -> None:
        self.update_value_signal.emit(text)

    def post_background(self, path: str) -> None:
        self.update_bg.emit(path)

    def post_cg(self, path: str) -> None:
        self.update_cg.emit(path)

    def post_llm_reply_finished(self) -> None:
        self.llm_reply_finished_signal.emit()

    def post_pause_asr(self) -> None:
        self.pause_asr_signal.emit()


def connect_to_desktop_window(ui: UIUpdateManager, window: Any) -> None:
    """将 worker 侧 UI 更新信号全部接到主窗口上的对应槽（原 main_sprite 中分散的连接）。"""
    ui.update_sprite_signal.connect(window.update_image)
    ui.update_dialog_signal.connect(window.setDisplayWords)
    ui.update_notification_signal.connect(window.setNotification)
    ui.update_option_signal.connect(window.setOptions)
    ui.update_value_signal.connect(window.update_numeric_info)
    ui.update_bg.connect(window.setBackgroundImage)
    ui.update_cg.connect(window.show_cg_image)
    ui.llm_reply_finished_signal.connect(window.llm_reply_finished)
    ui.pause_asr_signal.connect(window.pause_asr_signal)
