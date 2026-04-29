# ///////////////////////////////////////////////////////////////
# 新世界程序 — 设置窗口（PyDracula shell + 各功能页）
# 基于 Wanderson M. PyDracula；侧栏按钮与 stackedWidget 页已接好。
# ///////////////////////////////////////////////////////////////

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

_SETTINGS_UI_DIR = Path(__file__).resolve().parent

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QCursor, QIcon, QShowEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QWidget

# Dracula 壳层：需与 modules/__init__ 的星号导出一致（含 Qt 与 UIFunctions 等）。勿用 `from
# modules import *`：那依赖把 settings_ui 加进 sys.path 的顶层名 `modules`，PyInstaller
# 分析不到，运行时报 No module named 'modules'。
from ui.settings_ui.modules import *  # noqa: F403

from ui.settings_ui.api_tab import ApiSettingsTab
from ui.settings_ui.background_tab import BackgroundSettingsTab
from ui.settings_ui.character_tab import CharacterSettingsTab
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.music_cover_tab import MusicCoverSettingsTab
from ui.settings_ui.template_tab import TemplateSettingsTab
from ui.settings_ui.tools_tab import ToolsSettingsTab
from ui.settings_ui.window import settings_window_metrics

from core.plugins.plugin_host import collect_settings_contributions, ensure_plugins_loaded
from sdk.plugin_host_context import PluginSettingsUIContext


def _clear_stacked(sw) -> None:
    while sw.count():
        w = sw.widget(0)
        sw.removeWidget(w)
        w.deleteLater()


class MainWindow(QMainWindow):
    """
    左侧菜单：前 4 个为 topMenu，中 2 个为 bottomMenu（Share/Adjustments），
    与 Gradio 顺序一致：API、人物、背景、模板、音乐、工具。关闭请用窗口标题栏。
    """

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
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        global widgets
        widgets = self.ui

        Settings.ENABLE_CUSTOM_TITLE_BAR = True

        # 标题与侧栏文案由 apply_i18n 设置

        w, h, fp, _ = settings_window_metrics(self._ctx.config_manager)
        if width is not None and height is not None:
            w, h = width, height
        if font_pixel_size is not None:
            fp = font_pixel_size
        self.resize(w, h)
        g = QApplication.instance().primaryScreen().geometry()
        self.move((g.width() - w) // 2, (g.height() - h - 200))
        self.setMinimumSize(max(400, w // 2), max(300, h // 2))

        try:
            from pyqttoast import Toast

            Toast.setPositionRelativeToWidget(self)
        except ImportError:
            pass

        ensure_plugins_loaded(self._ctx.config_manager)

        # 功能页
        self._api = ApiSettingsTab(self._ctx)
        self._character = CharacterSettingsTab(self._ctx)
        self._background = BackgroundSettingsTab(self._ctx)
        self._template = TemplateSettingsTab(self._ctx)
        # self._music = MusicCoverSettingsTab(self._ctx)
        self._tools = ToolsSettingsTab(self._ctx)

        self._pages: list[QWidget] = [
            self._api,
            self._character,
            self._background,
            self._template,
            # self._music,
            self._tools,
        ]

        self._plugin_settings_contribs = collect_settings_contributions()
        for contrib in self._plugin_settings_contribs:
            plg = PluginSettingsUIContext.from_settings_ui_context(self._ctx)
            self._pages.append(contrib.build(plg))

        self._nav_buttons: list[tuple[object, int]] = [
            (self.ui.btn_home, 0),
            (self.ui.btn_widgets, 1),
            (self.ui.btn_new, 2),
            (self.ui.btn_save, 3),
            # (self.ui.btn_share, 4),
            (self.ui.btn_adjustments, 4),
        ]
        base_n = len(self._nav_buttons)
        for i, contrib in enumerate(self._plugin_settings_contribs):
            btn = QPushButton(contrib.nav_label, self.ui.topMenu)
            btn.setMinimumSize(QSize(0, 45))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.ui.verticalLayout_8.addWidget(btn)
            self._nav_buttons.append((btn, base_n + i))

        self.ui.btn_more.hide()
        self.ui.version.setText("v1.6.0")
        self.apply_i18n()

        sw = self.ui.stackedWidget
        _clear_stacked(sw)
        for p in self._pages:
            sw.addWidget(p)

        self._character.character_list_changed.connect(self._template.refresh_lists)
        self._character.character_list_changed.connect(self._tools.refresh_characters)
        self._background.background_list_changed.connect(self._template.refresh_lists)

        # Dracula 交互
        self.ui.toggleButton.clicked.connect(lambda: UIFunctions.toggleMenu(self, True))
        UIFunctions.uiDefinitions(self)

        def open_close_left():
            UIFunctions.toggleLeftBox(self, True)

        self.ui.toggleLeftBox.clicked.connect(open_close_left)
        self.ui.extraCloseColumnBtn.clicked.connect(open_close_left)

        def open_close_right():
            UIFunctions.toggleRightBox(self, True)

        self.ui.settingsTopBtn.clicked.connect(open_close_right)

        for btn, idx in self._nav_buttons:
            btn.clicked.connect(self._make_page_handler(idx))

        use_custom = True
        theme_path = _SETTINGS_UI_DIR / "themes" / "py_dracula_dark.qss"
        if use_custom and theme_path.is_file():
            UIFunctions.theme(self, str(theme_path), True)
            # 演示页里的 lineEdit/table 等已随旧 stack 页删除，不再调用 setThemeHack

        self.show()

        sw.setCurrentIndex(0)
        self.ui.btn_home.setStyleSheet(UIFunctions.selectMenu(self.ui.btn_home.styleSheet()))

    def apply_i18n(self) -> None:
        from i18n import tr

        self.setWindowTitle(tr("main.window_title"))
        self.ui.titleLeftApp.setText(tr("main.title_left"))
        self.ui.titleLeftDescription.setText(tr("main.title_description"))
        self.ui.titleRightInfo.setText(tr("main.title_right"))
        self.ui.btn_home.setText(tr("nav.api"))
        self.ui.btn_widgets.setText(tr("nav.character"))
        self.ui.btn_new.setText(tr("nav.background"))
        self.ui.btn_save.setText(tr("nav.template"))
        self.ui.btn_share.hide()
        self.ui.btn_share.setText(tr("nav.music"))
        self.ui.btn_adjustments.setText(tr("nav.tools"))
        self.ui.textEdit.setHtml(tr("main.text_edit"))
        self.ui.textEdit.setReadOnly(True)
        self.ui.toggleLeftBox.setText(tr("nav.tools"))
        for t in (self._api, self._character, self._background, self._template, self._tools):
            if hasattr(t, "apply_i18n"):
                t.apply_i18n()

    def _deselect_all_nav(self) -> None:
        for w in self.ui.topMenu.findChildren(QPushButton):
            w.setStyleSheet(UIFunctions.deselectMenu(w.styleSheet()))
        for w in self.ui.bottomMenu.findChildren(QPushButton):
            w.setStyleSheet(UIFunctions.deselectMenu(w.styleSheet()))

    def _make_page_handler(self, index: int) -> Callable[[], None]:
        def _go() -> None:
            self.ui.stackedWidget.setCurrentIndex(index)
            self._deselect_all_nav()
            b = self.sender()
            if b is not None and isinstance(b, QPushButton):
                b.setStyleSheet(UIFunctions.selectMenu(b.styleSheet()))
            if self.ui.stackedWidget.currentWidget() is self._template:
                self._template.refresh_lists()

        return _go

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not getattr(self, "_win_dwm_applied", False):
            self._win_dwm_applied = True
            from ui.win_frameless_dwm import apply_win_frameless_dwm_hacks

            apply_win_frameless_dwm_hacks(self, r=40, g=44, b=52)

    def resizeEvent(self, event):
        UIFunctions.resize_grips(self)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        self.dragPos = event.globalPosition().toPoint()
        if event.buttons() == Qt.MouseButton.LeftButton:
            pass
        super().mousePressEvent(event)


# 与 window.py / webui_qt 兼容
SettingsWindow = MainWindow


if __name__ == "__main__":
    # 独立调试：需从项目根目录保证 `ui.settings_ui` 可导入
    _root = _SETTINGS_UI_DIR.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from i18n import init_i18n
    from config.config_manager import ConfigManager
    from ui.settings_ui import create_default_context

    init_i18n(ConfigManager().config.system_config.ui_language)
    app = QApplication(sys.argv)
    icon = _SETTINGS_UI_DIR / "images" / "icons" / "icon_settings.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    ctx = create_default_context()
    win = MainWindow(ctx)
    sys.exit(app.exec())
