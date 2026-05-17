from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QMenu, QMessageBox, QVBoxLayout

from ui.qss import apply_pydracula_dark


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
