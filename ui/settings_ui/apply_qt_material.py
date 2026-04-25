"""
为 PyQt5 修补 qt_material：官方 2.x 只识别 PySide6/PyQt6，PyQt5 时 GUI=False，
add_fonts / set_icons_theme 不执行，导致 QFontDatabase 未定义且 icon: 未注册
（Windows 上会出现 C:/.../icon:/primary/... 无法加载）。

在「import qt_material」之后、apply_stylesheet 之前调用一次 patch_qt_material_for_pyqt5()。
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any


def patch_qt_material_for_pyqt5() -> bool:
    """若当前为 PyQt5 环境，向 qt_material 主模块注入与 PyQt6 分支相同的名称，并置 GUI=True。"""
    if "PyQt5" not in sys.modules or "PyQt6" in sys.modules or "PySide6" in sys.modules:
        return False
    m = sys.modules.get("qt_material")
    if not isinstance(m, ModuleType):
        return False
    if getattr(m, "GUI", None) is True:
        return True

    from PyQt5.QtCore import QDir, Qt
    from PyQt5.QtGui import QBrush, QColor, QFontDatabase, QGuiApplication, QPalette
    from PyQt5.QtWidgets import QAction, QActionGroup, QColorDialog

    names: dict[str, Any] = {
        "GUI": True,
        "QFontDatabase": QFontDatabase,
        "QBrush": QBrush,
        "QColor": QColor,
        "QGuiApplication": QGuiApplication,
        "QPalette": QPalette,
        "QColorDialog": QColorDialog,
        "Qt": Qt,
        "QDir": QDir,
        "QAction": QAction,
        "QActionGroup": QActionGroup,
    }
    for k, v in names.items():
        setattr(m, k, v)
    return True
