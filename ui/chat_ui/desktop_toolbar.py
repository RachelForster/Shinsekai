"""主窗口右上角工具栏（设置 / 最小化 / 关闭）。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui.chat_ui import styles


class DesktopToolbarMixin:
    def setup_toolbar(self) -> None:
        """初始化右上角工具栏"""
        self.toolbar = QWidget(self.image_container)
        self.toolbar.setStyleSheet(styles.toolbar_host())

        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(16, 0, 16, 0)
        toolbar_layout.setSpacing(8)

        button_size = 48
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(button_size, button_size)
        btn_style = styles.toolbar_action_button()
        self.settings_btn.setStyleSheet(btn_style)
        self.settings_btn.clicked.connect(self.show_settings_menu)

        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setFixedSize(button_size, button_size)
        self.minimize_btn.setStyleSheet(btn_style)
        self.minimize_btn.clicked.connect(self.minimize_window)

        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(button_size, button_size)
        self.close_btn.setStyleSheet(btn_style)
        self.close_btn.clicked.connect(self.close)

        toolbar_layout.addWidget(self.settings_btn)
        toolbar_layout.addWidget(self.minimize_btn)
        toolbar_layout.addWidget(self.close_btn)
        self._layout_toolbar_geometry()

    def _layout_toolbar_geometry(self) -> None:
        """按窗口缩放更新工具栏尺寸、字号与位置（依赖 _window_font_scale）。"""
        if getattr(self, "toolbar", None) is None:
            return
        scale = self._window_font_scale()
        btn_sz = max(32, int(48 * scale))
        tb_h = max(36, int(48 * scale), btn_sz)
        margins = 16 + 16
        spacing = 8 + 8
        min_tb_w = margins + spacing + 3 * btn_sz
        tb_w = max(min_tb_w, int(200 * scale), 140)
        self.toolbar.setFixedSize(tb_w, tb_h)

        btn_r = max(8, btn_sz // 2)
        t_font = f"{max(14, int(28 * scale))}px"
        qss = styles.toolbar_action_button(t_font, btn_r)
        host_r = max(10, min(tb_h // 2, int(20 * scale)))
        self.toolbar.setStyleSheet(styles.toolbar_host(host_r))
        for b in (self.settings_btn, self.minimize_btn, self.close_btn):
            b.setFixedSize(btn_sz, btn_sz)
            b.setStyleSheet(qss)
        w_ic = self.image_container.width() if getattr(self, "image_container", None) else 0
        if not w_ic:
            w_ic = self.width()
        self.toolbar.move(max(0, w_ic - tb_w), 10)

    def minimize_window(self) -> None:
        """调用 QWidget 的 showMinimized() 来最小化窗口。"""
        self.showMinimized()
        from i18n import tr

        print(tr("toolbar.minimized"))
