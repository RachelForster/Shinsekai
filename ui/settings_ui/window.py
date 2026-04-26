"""设置窗体尺寸与上下文；实际界面为 PyDracula `main.MainWindow`。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from config.background_manager import BackgroundManager
from config.character_manager import CharacterManager
from config.config_manager import ConfigManager
from llm.template_generator import TemplateGenerator
from tools.generate_sprites import ImageGenerator

# 与 ui/desktop_ui.DesktopAssistantWindow 主界面一致（非背景模式、无边距）
FONT_FAMILY_MS_YAHEI = "Microsoft YaHei"


def settings_window_metrics(config_manager: ConfigManager) -> tuple[int, int, int, int]:
    """
    与 DesktopAssistantWindow 一致：非 background_mode 时宽高均为屏幕高度*3/4；
    字号与主窗口相同（base_font_size_px + DPI 换算）。
    返回 (width, height, font_px, line_height_px)。
    """
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("settings_window_metrics 需要已有 QApplication")
    screen = app.primaryScreen()
    screen_geometry = screen.geometry()
    original_height = screen_geometry.height() // 4 * 3
    original_width = original_height
    base_font = config_manager.config.system_config.base_font_size_px
    base_dpi = 150.0
    current_dpi = screen.logicalDotsPerInch()
    font_px = int(base_font * current_dpi // base_dpi)
    line_h = max(int(font_px * 1.25), font_px + 4)
    return (original_width, original_height, font_px, line_h)


from ui.settings_ui.context import SettingsUIContext


def create_default_context() -> SettingsUIContext:
    # 打包运行：webui_qt 已设 EASYAI_PROJECT_ROOT 与 cwd=发行根；勿用 __file__ 推仓库根（冻结时在 _internal 下）
    er = os.environ.get("EASYAI_PROJECT_ROOT")
    project_root = Path(er).resolve() if er else Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return SettingsUIContext(
        config_manager=ConfigManager(),
        character_manager=CharacterManager(),
        background_manager=BackgroundManager(),
        image_generator=ImageGenerator(),
        template_generator=TemplateGenerator(),
        template_dir_path="./data/character_templates",
        history_dir="./data/chat_history",
    )


from ui.settings_ui.main import MainWindow as SettingsWindow

__all__ = [
    "FONT_FAMILY_MS_YAHEI",
    "SettingsWindow",
    "create_default_context",
    "settings_window_metrics",
]
