"""设置窗口内的操作反馈：成功用 Toast（包名 pyqt-toast-notification，内部经 QtPy 走 PySide6），失败用 QMessageBox。

须在导入 ``pyqttoast`` 之前保持 ``QT_API=pyside6``（见上方 ``setdefault``），与全工程 PySide6 一致。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QMessageBox, QWidget

try:
    from pyqttoast import Toast, ToastPreset
except ImportError:  # pragma: no cover
    Toast = None  # type: ignore[assignment, misc]
    ToastPreset = None  # type: ignore[assignment, misc]

_TOAST_MS = 4500
_TOAST_MAX_W = 420
_TOAST_BORDER_RADIUS_PX = 12

_FAIL_SUBSTR = (
    "失败",
    "错误",
    "不能为空",
    "找不到",
    "请选择",
    "请先",
    "不存在",
    "无有效",
    "未选择",
    "导入失败",
    "生成失败",
    "加载失败",
    "请填",
    "无语音文件",
    "无有效语音",
    "文件不存在",
)


def is_failure_message(msg: str) -> bool:
    s = (msg or "").strip()
    return any(m in s for m in _FAIL_SUBSTR)


def _show_toast(
    parent: QWidget | None, title: str, text: str, *, use_success_style: bool
) -> None:
    if not Toast or not ToastPreset:
        body = f"{title}\n{text}" if (text and text.strip()) else title
        QMessageBox.information(parent, title, body)
        return
    t = Toast(parent)
    t.setDuration(_TOAST_MS)
    t.setTitle(title)
    if text and text.strip():
        t.setText(text)
    t.setMaximumWidth(_TOAST_MAX_W)
    t.applyPreset(ToastPreset.SUCCESS if use_success_style else ToastPreset.INFORMATION)
    t.setBorderRadius(_TOAST_BORDER_RADIUS_PX)
    t.show()


def toast_info(parent: QWidget | None, title: str, text: str = "") -> None:
    _show_toast(parent, title, text, use_success_style=False)


def toast_success(parent: QWidget | None, title: str, text: str = "") -> None:
    _show_toast(parent, title, text, use_success_style=True)


def message_fail(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def message_error(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)


def feedback_result(
    parent: QWidget | None, title: str, msg: str, *, success_style: bool | None = None
) -> None:
    """
    根据返回文案选择 toast 或 警告框：含失败/校验类关键词时走 QMessageBox。
    success_style: True/False 强制 toast 样式；None 时按 is_failure_message 与文案猜测。
    """
    if is_failure_message(msg):
        message_fail(parent, title, msg)
        return
    if success_style is None:
        success_style = any(
            x in (msg or "")
            for x in ("成功", "已", "完成", "保存", "添加", "更新", "删除", "上传", "导出", "下载")
        )
    if success_style:
        toast_success(parent, title, msg)
    else:
        toast_info(parent, title, msg)
