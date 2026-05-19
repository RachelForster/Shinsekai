"""设置窗口内的操作反馈：成功用 Toast（包名 pyqt-toast-notification，内部经 QtPy 走 PySide6），失败用 QMessageBox。

须在导入 ``pyqttoast`` 之前保持 ``QT_API=pyside6``（见上方 ``setdefault``），与全工程 PySide6 一致。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

try:
    from pyqttoast import Toast, ToastPreset
except ImportError:  # pragma: no cover
    Toast = None  # type: ignore[assignment, misc]
    ToastPreset = None  # type: ignore[assignment, misc]

_TOAST_MS = 4500
_TOAST_MAX_W = 420
_TOAST_BORDER_RADIUS_PX = 12
_MESSAGE_SUMMARY_MAX_CHARS = 420

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


def _compact_message_text(text: str) -> str:
    msg = (text or "").strip()
    if len(msg) <= _MESSAGE_SUMMARY_MAX_CHARS:
        return msg
    return msg[:_MESSAGE_SUMMARY_MAX_CHARS].rstrip() + "..."


def _show_message_box(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    *,
    details: str | None = None,
) -> None:
    full_text = (text or "").strip()
    full_details = (details or "").strip()
    box = QMessageBox(
        icon,
        title,
        _compact_message_text(full_text),
        QMessageBox.StandardButton.Ok,
        parent,
    )
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if full_details:
        box.setDetailedText(full_details)
    elif len(full_text) > _MESSAGE_SUMMARY_MAX_CHARS:
        box.setDetailedText(full_text)
    box.exec()


def _palette_is_dark(parent: QWidget | None) -> bool:
    palette = parent.palette() if parent is not None else QApplication.palette()
    color = palette.color(QPalette.ColorRole.Window)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return luminance < 128


def _themed_dialog_qss(parent: QWidget | None) -> str:
    if _palette_is_dark(parent):
        return """
QDialog#themedMessageDialog {
    background: transparent;
}
QFrame#themedMessageDialogFrame {
    background-color: rgb(40, 44, 52);
    border: 1px solid rgb(64, 71, 88);
    border-radius: 8px;
}
QLabel#themedMessageDialogTitle {
    color: rgb(221, 221, 221);
    font-weight: 600;
    font-size: 11pt;
}
QLabel#themedMessageDialogText {
    color: rgb(221, 221, 221);
    background: transparent;
}
QPlainTextEdit#themedMessageDialogDetails {
    color: rgb(221, 221, 221);
    background-color: rgb(27, 29, 35);
    border: 1px solid rgb(64, 71, 88);
    border-radius: 5px;
}
QPushButton {
    color: rgb(221, 221, 221);
    background-color: rgb(52, 59, 72);
    border: 1px solid rgb(64, 71, 88);
    border-radius: 5px;
    padding: 6px 18px;
}
QPushButton:hover {
    background-color: rgb(64, 71, 88);
}
QPushButton:pressed {
    background-color: rgb(33, 37, 43);
}
"""
    return """
QDialog#themedMessageDialog {
    background: transparent;
}
QFrame#themedMessageDialogFrame {
    background-color: #f8f8f2;
    border: 1px solid #bd93f9;
    border-radius: 8px;
}
QLabel#themedMessageDialogTitle {
    color: #333333;
    font-weight: 600;
    font-size: 11pt;
}
QLabel#themedMessageDialogText {
    color: #333333;
    background: transparent;
}
QPlainTextEdit#themedMessageDialogDetails {
    color: #333333;
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 5px;
}
QPushButton {
    color: #f8f8f2;
    background-color: #6272a4;
    border: 1px solid #6a7cb1;
    border-radius: 5px;
    padding: 6px 18px;
}
QPushButton:hover {
    background-color: #bd93f9;
}
QPushButton:pressed {
    background-color: #ff79c6;
}
"""


class _ThemedMessageDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        *,
        details: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("themedMessageDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowModality(
            Qt.WindowModality.WindowModal
            if parent is not None
            else Qt.WindowModality.ApplicationModal
        )
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_themed_dialog_qss(parent))
        self.setMinimumWidth(380)
        self.setMaximumWidth(620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame(self)
        frame.setObjectName("themedMessageDialogFrame")
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        icon_label = QLabel(frame)
        icon_pixmap = self.style().standardIcon(
            _message_box_standard_icon(icon)
        ).pixmap(28, 28)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setFixedSize(30, 30)
        header.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)

        title_label = QLabel(title, frame)
        title_label.setObjectName("themedMessageDialogTitle")
        title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_col.addWidget(title_label)

        body_label = QLabel(_compact_message_text(text), frame)
        body_label.setObjectName("themedMessageDialogText")
        body_label.setWordWrap(True)
        body_label.setTextFormat(Qt.TextFormat.PlainText)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        text_col.addWidget(body_label)
        header.addLayout(text_col, stretch=1)
        layout.addLayout(header)

        full_text = (text or "").strip()
        full_details = (details or "").strip()
        detail_text = full_details or (
            full_text if len(full_text) > _MESSAGE_SUMMARY_MAX_CHARS else ""
        )
        if detail_text:
            detail_edit = QPlainTextEdit(frame)
            detail_edit.setObjectName("themedMessageDialogDetails")
            detail_edit.setReadOnly(True)
            detail_edit.setPlainText(detail_text)
            detail_edit.setFixedHeight(160)
            layout.addWidget(detail_edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_button = QPushButton("OK", frame)
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        buttons.addWidget(ok_button)
        layout.addLayout(buttons)


def _message_box_standard_icon(icon: QMessageBox.Icon) -> QStyle.StandardPixmap:
    if icon == QMessageBox.Icon.Information:
        return QStyle.StandardPixmap.SP_MessageBoxInformation
    if icon == QMessageBox.Icon.Warning:
        return QStyle.StandardPixmap.SP_MessageBoxWarning
    if icon == QMessageBox.Icon.Critical:
        return QStyle.StandardPixmap.SP_MessageBoxCritical
    return QStyle.StandardPixmap.SP_MessageBoxInformation


def _show_themed_message_dialog(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    *,
    details: str | None = None,
) -> None:
    dialog = _ThemedMessageDialog(parent, icon, title, text, details=details)
    dialog.exec()


def toast_info(parent: QWidget | None, title: str, text: str = "") -> None:
    _show_toast(parent, title, text, use_success_style=False)


def toast_success(parent: QWidget | None, title: str, text: str = "") -> None:
    _show_toast(parent, title, text, use_success_style=True)


def message_info(
    parent: QWidget | None, title: str, text: str, *, details: str | None = None
) -> None:
    _show_themed_message_dialog(
        parent, QMessageBox.Icon.Information, title, text, details=details
    )


def message_fail(
    parent: QWidget | None, title: str, text: str, *, details: str | None = None
) -> None:
    _show_themed_message_dialog(
        parent, QMessageBox.Icon.Warning, title, text, details=details
    )


def message_error(
    parent: QWidget | None, title: str, text: str, *, details: str | None = None
) -> None:
    _show_themed_message_dialog(
        parent, QMessageBox.Icon.Critical, title, text, details=details
    )


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
