"""PyDracula 风格 QSS（基于 Wanderson M. PyDracula 主题，经裁剪与去资源化）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
_COMBO_POPUP_STYLE_MARKER = "/* pydracula-combobox-popup-hover */"
_COMBO_POPUP_HOVER_DELEGATE_ATTR = "_pydracula_combo_popup_hover_delegate"
_COMBO_POPUP_VIEW_QSS = f"""
{_COMBO_POPUP_STYLE_MARKER}
QAbstractItemView {{
	color: rgb(221, 221, 221);
	background-color: rgb(33, 37, 43);
	border: 1px solid rgb(44, 49, 58);
	outline: 0px;
	padding: 10px;
	selection-background-color: rgb(64, 71, 88);
	selection-color: rgb(221, 221, 221);
}}
QAbstractItemView::item {{
	background-color: rgb(33, 37, 43);
}}
QAbstractItemView::item:hover {{
	color: rgb(221, 221, 221);
	background-color: rgb(64, 71, 88);
}}
QAbstractItemView::item:selected {{
	color: rgb(221, 221, 221);
	background-color: rgb(64, 71, 88);
}}
"""


def load_pydracula_dark() -> str:
    """返回 py_dracula_dark.qss 全文。"""
    p = _DIR / "py_dracula_dark.qss"
    return p.read_text(encoding="utf-8")


def _pydracula_dark_palette() -> Any:
    """Create the dark palette used as a fallback for native/top-level widgets."""
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    window = QColor(40, 44, 52)
    panel = QColor(33, 37, 43)
    base = QColor(27, 29, 35)
    button = QColor(52, 59, 72)
    text = QColor(221, 221, 221)
    muted = QColor(113, 126, 149)
    highlight = QColor(64, 71, 88)
    white = QColor(255, 255, 255)
    accent = QColor(189, 147, 249)

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, window)
        palette.setColor(group, QPalette.ColorRole.WindowText, text)
        palette.setColor(group, QPalette.ColorRole.Base, base)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, panel)
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, panel)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, white)
        palette.setColor(group, QPalette.ColorRole.Text, text)
        palette.setColor(group, QPalette.ColorRole.Button, button)
        palette.setColor(group, QPalette.ColorRole.ButtonText, text)
        palette.setColor(group, QPalette.ColorRole.BrightText, white)
        palette.setColor(group, QPalette.ColorRole.Highlight, highlight)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, white)
        palette.setColor(group, QPalette.ColorRole.Link, accent)

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Window, window)
    palette.setColor(disabled, QPalette.ColorRole.WindowText, muted)
    palette.setColor(disabled, QPalette.ColorRole.Base, base)
    palette.setColor(disabled, QPalette.ColorRole.AlternateBase, panel)
    palette.setColor(disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(disabled, QPalette.ColorRole.Button, button)
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, muted)
    palette.setColor(disabled, QPalette.ColorRole.Highlight, highlight)
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, muted)
    try:
        palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    except AttributeError:
        pass
    return palette


def _style_combobox_popup(combo: Any) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate

    view = combo.view()
    if view is None:
        return
    view.setMouseTracking(True)
    view.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    viewport = view.viewport()
    if viewport is not None:
        viewport.setMouseTracking(True)
        viewport.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    style_sheet = view.styleSheet()
    if _COMBO_POPUP_STYLE_MARKER not in style_sheet:
        prefix = f"{style_sheet}\n" if style_sheet.strip() else ""
        view.setStyleSheet(prefix + _COMBO_POPUP_VIEW_QSS)

    if getattr(view, _COMBO_POPUP_HOVER_DELEGATE_ATTR, None) is None:
        class _ComboPopupHoverDelegate(QStyledItemDelegate):
            def paint(self, painter: Any, option: Any, index: Any) -> None:
                item_option = QStyleOptionViewItem(option)
                self.initStyleOption(item_option, index)
                if item_option.state & (
                    QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected
                ):
                    item_option.state |= QStyle.StateFlag.State_Selected
                    item_option.palette.setColor(
                        QPalette.ColorRole.Highlight, QColor(64, 71, 88)
                    )
                    item_option.palette.setColor(
                        QPalette.ColorRole.HighlightedText, QColor(221, 221, 221)
                    )
                super().paint(painter, item_option, index)

        delegate = _ComboPopupHoverDelegate(view)
        view.setItemDelegate(delegate)
        setattr(view, _COMBO_POPUP_HOVER_DELEGATE_ATTR, delegate)


def _install_combobox_popup_hover(app: Any) -> None:
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QComboBox

    class _ComboPopupHoverFilter(QObject):
        def eventFilter(self, obj: Any, event: Any) -> bool:
            if isinstance(obj, QComboBox) and event.type() in {
                QEvent.Type.Polish,
                QEvent.Type.Show,
                QEvent.Type.MouseButtonPress,
            }:
                _style_combobox_popup(obj)
            return False

    if getattr(app, "_pydracula_combo_popup_hover_filter", None) is None:
        event_filter = _ComboPopupHoverFilter(app)
        app.installEventFilter(event_filter)
        app._pydracula_combo_popup_hover_filter = event_filter

    for widget in app.allWidgets():
        if isinstance(widget, QComboBox):
            _style_combobox_popup(widget)


def apply_pydracula_dark(app: Any | None = None) -> bool:
    """Apply the dark palette and QSS to a QApplication."""
    from PySide6.QtWidgets import QApplication, QStyleFactory

    target = app if app is not None else QApplication.instance()
    if target is None:
        return False
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        target.setStyle(fusion)
    target.setPalette(_pydracula_dark_palette())
    target.setStyleSheet(load_pydracula_dark())
    _install_combobox_popup_hover(target)
    return True
