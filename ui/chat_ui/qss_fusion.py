"""
自定义 QSS 与系统默认 QStyle（尤其 Windows）组合时，QPushButton 等控件的
border-radius 常被原生绘制忽略。对聊天主窗进程启用 Fusion 可稳定呈现圆角与主题。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyleFactory


def ensure_fusion_style(app: QApplication | None = None) -> bool:
    """
    将当前（或传入的）QApplication 设为 Fusion 样式；不可用则返回 False。
    安全多次调用：重复 setStyle(Fusion) 无害。
    """
    a = app if app is not None else QApplication.instance()
    if a is None:
        return False
    fusion = QStyleFactory.create("Fusion")
    if fusion is None:
        return False
    a.setStyle(fusion)
    return True
