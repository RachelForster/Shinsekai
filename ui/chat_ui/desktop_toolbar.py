"""主窗口右上角工具栏（设置 / 最小化 / 关闭）。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui.chat_ui import styles


class DesktopToolbarMixin:
    def setup_toolbar(self) -> None:
        """初始化右上角工具栏"""
        self.toolbar = QWidget(self.image_container)
        self.toolbar.setFixedSize(200, 48)
        self.toolbar.move(self.original_width - 200, 10)
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

    def minimize_window(self) -> None:
        """调用 QWidget 的 showMinimized() 来最小化窗口。"""
        self.showMinimized()
        from i18n import tr

        print(tr("toolbar.minimized"))
