from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QFrame,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ui.qss import apply_pydracula_dark, load_pydracula_dark
from ui.settings_ui.feedback import _ThemedMessageDialog


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


def _assert_messagebox_detail_text_uses_dark_palette(qss: str):
    assert "QMessageBox QTextEdit" in qss
    assert "QMessageBox QPlainTextEdit" in qss
    assert "background-color: rgb(27, 29, 35);" in qss


def test_pydracula_messagebox_detail_text_uses_dark_palette():
    _assert_messagebox_detail_text_uses_dark_palette(load_pydracula_dark())


def test_settings_theme_messagebox_detail_text_uses_dark_palette():
    qss = (_ROOT / "ui" / "settings_ui" / "themes" / "py_dracula_dark.qss").read_text(
        encoding="utf-8"
    )

    _assert_messagebox_detail_text_uses_dark_palette(qss)


def _parent_with_window_color(color: QColor) -> QWidget:
    parent = QWidget()
    palette = parent.palette()
    palette.setColor(QPalette.ColorRole.Window, color)
    parent.setPalette(palette)
    return parent


def test_themed_info_dialog_uses_frameless_modal_dark_frame():
    QApplication.instance() or QApplication([])
    parent = _parent_with_window_color(QColor(40, 44, 52))
    dialog = _ThemedMessageDialog(
        parent, QMessageBox.Icon.Information, "API", "已获取 3 个模型。"
    )

    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert "QFrame#themedMessageDialogFrame" in dialog.styleSheet()
    assert "background-color: rgb(40, 44, 52);" in dialog.styleSheet()
    assert dialog.findChild(QFrame, "themedMessageDialogFrame") is not None
    assert dialog.findChild(QPushButton).text() == "OK"


def test_themed_info_dialog_uses_light_frame_from_palette():
    QApplication.instance() or QApplication([])
    parent = _parent_with_window_color(QColor(248, 248, 242))
    dialog = _ThemedMessageDialog(
        parent, QMessageBox.Icon.Information, "API", "Fetched 3 models."
    )

    assert "background-color: #f8f8f2;" in dialog.styleSheet()
    assert "background-color: #6272a4;" in dialog.styleSheet()


def test_themed_warning_dialog_keeps_details_inside_frameless_frame():
    QApplication.instance() or QApplication([])
    parent = _parent_with_window_color(QColor(40, 44, 52))
    dialog = _ThemedMessageDialog(
        parent,
        QMessageBox.Icon.Warning,
        "API",
        "获取模型列表失败：HTTP 403: Error 1010",
        details='{"error_code":1010,"error_name":"browser_signature_banned"}',
    )

    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    detail_edit = dialog.findChild(QPlainTextEdit, "themedMessageDialogDetails")
    assert detail_edit is not None
    assert "browser_signature_banned" in detail_edit.toPlainText()
