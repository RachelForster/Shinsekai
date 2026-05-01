"""分段标签导航（替代 QTabWidget）：避免 Windows 下 QTabBar 忽略文字样式的问题。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# 未选中白字 + 选中高亮；与 PyDracula 深色主题搭配。
SEGMENTED_TAB_NAV_QSS = (
    "QPushButton {\n"
    "    color: #ffffff;\n"
    "    background: transparent;\n"
    "    border: none;\n"
    "    border-bottom: 2px solid transparent;\n"
    "    padding: 8px 14px;\n"
    "    font-weight: normal;\n"
    "}\n"
    "QPushButton:checked {\n"
    "    color: palette(highlight);\n"
    "    border-bottom: 2px solid palette(highlight);\n"
    "    font-weight: bold;\n"
    "}\n"
    "QPushButton:hover:!checked {\n"
    "    color: #ffffff;\n"
    "    background-color: rgba(255, 255, 255, 30);\n"
    "}\n"
)


class SegmentedTabNav(QWidget):
    """横向可选按钮 + QStackedWidget；多于一页时显示导航条，仅一页时隐藏导航条。"""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._nav_wrap = QWidget(self)
        nav_outer = QHBoxLayout(self._nav_wrap)
        nav_outer.setContentsMargins(4, 4, 4, 0)
        nav_outer.setSpacing(0)

        self._btn_strip = QWidget()
        self._btn_strip_layout = QHBoxLayout(self._btn_strip)
        self._btn_strip_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_strip_layout.setSpacing(4)

        nav_outer.addWidget(self._btn_strip, stretch=0)
        nav_outer.addStretch(1)

        self._nav_wrap.setStyleSheet(SEGMENTED_TAB_NAV_QSS)

        self._stack = QStackedWidget()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._stack.setCurrentIndex)
        self._group.idClicked.connect(self.currentChanged.emit)

        root.addWidget(self._nav_wrap)
        root.addWidget(self._stack, stretch=1)

    def add_tab(self, widget: QWidget, title: str) -> int:
        idx = self._stack.count()
        btn = QPushButton(title)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._group.addButton(btn, idx)
        self._btn_strip_layout.addWidget(btn)
        self._stack.addWidget(widget)
        if idx == 0:
            btn.setChecked(True)
        self._sync_nav_visibility()
        return idx

    def set_tab_text(self, index: int, title: str) -> None:
        b = self._group.button(index)
        if b is not None:
            b.setText(title)

    def count(self) -> int:
        return self._stack.count()

    def current_index(self) -> int:
        return self._stack.currentIndex()

    def set_current_index(self, index: int) -> None:
        b = self._group.button(index)
        if b is not None:
            b.setChecked(True)
        self._stack.setCurrentIndex(index)

    def _sync_nav_visibility(self) -> None:
        self._nav_wrap.setVisible(self._stack.count() > 1)
