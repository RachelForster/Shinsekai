"""在后台线程执行 LLM 相关任务时显示不确定进度对话框，避免界面卡死。"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

T = TypeVar("T")


class _AiWorkerThread(QThread):
    success = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.success.emit(self._fn())
        except Exception as e:
            self.failed.emit(str(e))


def run_ai_task_with_progress(
    parent: QWidget,
    window_title: str,
    label_text: str,
    work: Callable[[], T],
    on_success: Callable[[T], None],
    on_failure: Callable[[str], None],
) -> None:
    """
    在子线程执行 work，主线程显示忙碌进度条；结束后调用 on_success(result) 或 on_failure(错误信息字符串)。
    """
    dlg = QProgressDialog(parent)
    dlg.setWindowTitle(window_title)
    dlg.setLabelText(label_text)
    dlg.setRange(0, 0)
    dlg.setCancelButton(None)
    dlg.setModal(True)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(True)
    dlg.setAutoReset(True)
    dlg.show()
    QApplication.processEvents()

    th = _AiWorkerThread(work, parent)

    def cleanup() -> None:
        dlg.close()
        dlg.deleteLater()

    def ok(res: object) -> None:
        cleanup()
        on_success(res)  # type: ignore[arg-type]

    def fail(msg: str) -> None:
        cleanup()
        on_failure(msg)

    th.success.connect(ok)
    th.failed.connect(fail)
    th.finished.connect(th.deleteLater)
    th.start()
