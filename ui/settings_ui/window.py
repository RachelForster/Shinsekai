"""设置主窗口：左侧导航 + 右侧内容区；外观由 webui_qt 中 qt-material 主题提供。"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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


from ui.settings_ui.api_tab import ApiSettingsTab
from ui.settings_ui.background_tab import BackgroundSettingsTab
from ui.settings_ui.character_tab import CharacterSettingsTab
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.music_cover_tab import MusicCoverSettingsTab
from ui.settings_ui.template_tab import TemplateSettingsTab
from ui.settings_ui.tools_tab import ToolsSettingsTab


def create_default_context() -> SettingsUIContext:
    project_root = Path(__file__).resolve().parent.parent.parent
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


class SettingsWindow(QMainWindow):
    """与 webui.Gradio 同序：API → 人物 → 背景 → 聊天模板 → 音乐翻唱 → 小工具（侧栏导航）。"""

    def __init__(
        self,
        ctx: SettingsUIContext,
        parent: QWidget | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
        font_pixel_size: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setWindowTitle("新世界程序 - 设置")
        w, h, fp, _ = settings_window_metrics(self._ctx.config_manager)
        if width is not None and height is not None:
            w, h = width, height
        if font_pixel_size is not None:
            fp = font_pixel_size
        self.resize(w, h)
        g = QApplication.instance().primaryScreen().geometry()
        self.move(
            (g.width() - w) // 2,
            (g.height() - h - 200),
        )
        self.setMinimumSize(max(400, w // 2), max(300, h // 2))
        self._header_font_px = fp
        self._build()

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        header = QLabel()
        # header.setWordWrap(True)
        # header.setText(
        #     "<h1>新世界程序</h1>"
        #     "<p>（B站、小红书）作者：不二咲爱笑 · "
        #     "<a href=\"https://github.com/RachelForster/Shinsekai\">GitHub</a> · "
        #     "QQ 交流群：1033281516。本软件开源，禁止商用。</p>"
        # )
        # header.setOpenExternalLinks(True)
        f = QFont(FONT_FAMILY_MS_YAHEI)
        f.setPixelSize(self._header_font_px)
        header.setFont(f)
        layout.addWidget(header)

        self._api = ApiSettingsTab(self._ctx)
        self._character = CharacterSettingsTab(self._ctx)
        self._background = BackgroundSettingsTab(self._ctx)
        self._template = TemplateSettingsTab(self._ctx)
        self._music = MusicCoverSettingsTab(self._ctx)
        self._tools = ToolsSettingsTab(self._ctx)

        self._stack = QStackedWidget()
        for page in (
            self._api,
            self._character,
            self._background,
            self._template,
            self._music,
            self._tools,
        ):
            self._stack.addWidget(page)

        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        for label in (
            "API 设定",
            "人物设定",
            "背景管理",
            "聊天模板",
            "音乐翻唱流水线",
            "小工具",
        ):
            self._nav.addItem(QListWidgetItem(label))
        self._nav.setCurrentRow(0)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._nav.setMinimumWidth(200)
        self._nav.setMaximumWidth(400)
        self._nav.setSpacing(4)
        self._nav.setUniformItemSizes(True)
        self._nav.currentRowChanged.connect(self._on_nav_row_changed)

        self._character.character_list_changed.connect(self._template.refresh_lists)
        self._character.character_list_changed.connect(self._tools.refresh_characters)
        self._background.background_list_changed.connect(self._template.refresh_lists)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._nav)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        total_w = max(self.width(), 1)
        left_w = min(240, total_w // 4)
        splitter.setSizes([left_w, total_w - left_w])
        layout.addWidget(splitter, stretch=1)

    def _on_nav_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        if self._stack.currentWidget() is self._template:
            self._template.refresh_lists()
