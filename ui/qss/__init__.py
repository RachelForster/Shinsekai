"""PyDracula 风格 QSS（基于 Wanderson M. PyDracula 主题，经裁剪与去资源化）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent


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
    return True
