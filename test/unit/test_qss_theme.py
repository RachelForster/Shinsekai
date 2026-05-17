from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from ui.qss import apply_pydracula_dark, load_pydracula_dark


_ROOT = Path(__file__).resolve().parents[2]


def _luminance(color) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def _assert_dark_readable(widget):
    widget.ensurePolished()
    palette = widget.palette()
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    window_text = palette.color(QPalette.ColorRole.WindowText)
    text = palette.color(QPalette.ColorRole.Text)

    assert _luminance(window) < 80
    assert _luminance(base) < 80
    assert _luminance(window_text) > 150
    assert _luminance(text) > 150


def test_pydracula_popups_use_dark_readable_palette():
    app = QApplication.instance() or QApplication([])
    old_stylesheet = app.styleSheet()
    old_palette = app.palette()
    try:
        apply_pydracula_dark(app)

        menu = QMenu()
        menu.addAction("History")
        _assert_dark_readable(menu)

        _assert_dark_readable(QDialog())
        _assert_dark_readable(QMessageBox())

        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        combo = QComboBox()
        combo.addItems(["one", "two"])
        layout.addWidget(combo)
        dialog.ensurePolished()
        combo.showPopup()
        app.processEvents()
        _assert_dark_readable(combo)
        _assert_dark_readable(combo.view())
        combo.hidePopup()
    finally:
        app.setStyleSheet(old_stylesheet)
        app.setPalette(old_palette)


def test_pydracula_combobox_popup_view_has_hover_tracking():
    app = QApplication.instance() or QApplication([])
    old_stylesheet = app.styleSheet()
    old_palette = app.palette()
    try:
        apply_pydracula_dark(app)

        combo = QComboBox()
        combo.addItems(["one", "two"])
        combo.ensurePolished()
        combo.showPopup()
        app.processEvents()

        view = combo.view()
        assert view.hasMouseTracking()
        assert view.viewport().hasMouseTracking()
        assert "pydracula-combobox-popup-hover" in view.styleSheet()
        assert "QAbstractItemView::item:hover" in view.styleSheet()
        assert "selection-color: rgb(221, 221, 221);" in view.styleSheet()
        assert hasattr(view, "_pydracula_combo_popup_hover_delegate")
        assert view.itemDelegate() is view._pydracula_combo_popup_hover_delegate

        pixmap = QPixmap(120, 28)
        pixmap.fill(QColor(33, 37, 43))
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 120, 28)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver
        view.itemDelegate().paint(painter, option, combo.model().index(0, 0))
        painter.end()

        hover_color = pixmap.toImage().pixelColor(4, 14)
        assert (hover_color.red(), hover_color.green(), hover_color.blue()) == (64, 71, 88)
        combo.hidePopup()
    finally:
        app.setStyleSheet(old_stylesheet)
        app.setPalette(old_palette)


def _assert_combobox_popup_hover_highlight(qss: str):
    qss_lines = {line.strip() for line in qss.splitlines()}

    assert "QAbstractItemView::item:hover," not in qss_lines
    assert "QAbstractItemView::item:hover {" not in qss_lines
    assert "QComboBox QListView::item:hover" in qss
    assert "QComboBox QAbstractItemView::item:hover" in qss
    assert "selection-background-color: rgb(64, 71, 88);" in qss
    assert "selection-color: rgb(221, 221, 221);" in qss


def test_pydracula_combobox_popup_items_have_hover_highlight():
    _assert_combobox_popup_hover_highlight(load_pydracula_dark())


def test_settings_theme_combobox_popup_items_have_hover_highlight():
    qss = (_ROOT / "ui" / "settings_ui" / "themes" / "py_dracula_dark.qss").read_text(
        encoding="utf-8"
    )

    _assert_combobox_popup_hover_highlight(qss)
