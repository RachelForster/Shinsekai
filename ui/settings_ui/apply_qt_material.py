"""
设置窗口主题已改为 `ui/qss` 中 PyDracula 风格 QSS，不再使用 qt_material。

保留本模块与空函数，以免旧脚本 `import apply_qt_material` 失败。
"""

from __future__ import annotations


def patch_qt_material_compat() -> bool:
    """兼容占位；主题见 ui.qss.load_pydracula_dark。"""
    return True


patch_qt_material_for_pyqt5 = patch_qt_material_compat  # 旧脚本兼容别名
