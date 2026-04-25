"""
qt_material 2.x 原生支持 PyQt6，无需在应用内打补丁（此前 PyQt5 需 patch_qt_material_for_pyqt5）。

保留本模块名以免外部脚本 import 失败；`patch_qt_material_for_pyqt5` 为兼容旧代码的空操作。
"""

from __future__ import annotations


def patch_qt_material_for_pyqt5() -> bool:
    """已迁移至 PyQt6 时无操作。保留函数供旧 import 使用。"""
    return True
