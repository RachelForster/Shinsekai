from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from typing import Any, NoReturn

from sdk.exception.types import RuntimeDependencyError, runtime_dependency_error_from_exception


_dialog_shown = False
_hook_installed = False


def _traceback_text(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: Any,
) -> str:
    return "".join(traceback.format_exception(exc_type, exc, tb))


def _format_dialog_message(
    app_name: str,
    exc: BaseException,
    dependency_error: RuntimeDependencyError | None,
) -> str:
    if dependency_error:
        return (
            f"{app_name} 启动失败，缺少 Python 模块：{dependency_error['moduleName']}\n\n"
            f"建议安装包：{dependency_error['packageName']}\n"
            "安装依赖后请重新启动聊天。"
        )
    return f"{app_name} 启动失败：{type(exc).__name__}: {exc}"


def _write_stderr(
    app_name: str,
    exc_type: type[BaseException],
    exc: BaseException,
    detail: str,
    dependency_error: RuntimeDependencyError | None,
) -> None:
    if dependency_error:
        header = (
            f"{app_name} startup failed: Missing Python module: {dependency_error['moduleName']}\n"
            f"Suggested package: {dependency_error['packageName']}\n"
        )
    else:
        header = f"{app_name} startup failed: {exc_type.__name__}: {exc}\n"
    try:
        sys.stderr.write(header)
        sys.stderr.write(detail)
        if not detail.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
    except Exception:
        pass


def _show_qt_dialog(title: str, message: str, detail: str) -> bool:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except Exception:
        return False

    app = QApplication.instance()
    owns_app = False
    if app is None:
        try:
            app = QApplication([])
            owns_app = True
        except Exception:
            return False

    try:
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        if detail:
            box.setDetailedText(detail[-20000:])
        box.exec()
        return True
    except Exception:
        return False
    finally:
        if owns_app:
            try:
                app.quit()
            except Exception:
                pass


def _show_windows_dialog(title: str, message: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message[:4000], title, 0x10)
        return True
    except Exception:
        return False


def show_error_dialog(title: str, message: str, detail: str = "") -> bool:
    global _dialog_shown
    if _dialog_shown:
        return False
    _dialog_shown = True
    return _show_qt_dialog(title, message, detail) or _show_windows_dialog(title, message)


def _should_show_dialog(show_dialog: bool) -> bool:
    if not show_dialog:
        return False
    raw = (
        os.environ.get("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG")
        or os.environ.get("SHINSEKAI_DISABLE_MAIN_ERROR_DIALOG")
        or ""
    )
    return raw.strip().lower() not in {"1", "true", "yes", "on"}


def report_main_exception(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: Any,
    *,
    app_name: str = "Shinsekai Chat",
    logger: logging.Logger | None = None,
    show_dialog: bool = True,
) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return

    detail = _traceback_text(exc_type, exc, tb)
    dependency_error = runtime_dependency_error_from_exception(exc)
    event = "main.missing_dependency" if dependency_error else "main.uncaught_exception"
    target_logger = logger or logging.getLogger("shinsekai.main")

    try:
        target_logger.critical(
            "main.py failed during startup/runtime",
            exc_info=(exc_type, exc, tb),
            extra={
                "event": event,
                "module_name": dependency_error.get("moduleName", "") if dependency_error else "",
                "package_name": dependency_error.get("packageName", "") if dependency_error else "",
            },
        )
    except Exception:
        pass

    _write_stderr(app_name, exc_type, exc, detail, dependency_error)
    if _should_show_dialog(show_dialog):
        show_error_dialog(
            f"{app_name} 启动失败",
            _format_dialog_message(app_name, exc, dependency_error),
            detail,
        )


def handle_main_exception(
    exc: BaseException,
    *,
    app_name: str = "Shinsekai Chat",
    logger: logging.Logger | None = None,
    show_dialog: bool = True,
    exit_code: int = 1,
) -> NoReturn:
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise exc
    report_main_exception(
        type(exc),
        exc,
        exc.__traceback__,
        app_name=app_name,
        logger=logger,
        show_dialog=show_dialog,
    )
    raise SystemExit(exit_code)


def install_main_exception_hook(
    *,
    app_name: str = "Shinsekai Chat",
    logger: logging.Logger | None = None,
    show_dialog: bool = True,
) -> None:
    global _hook_installed
    if _hook_installed:
        return
    _hook_installed = True

    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        report_main_exception(
            exc_type,
            exc,
            tb,
            app_name=app_name,
            logger=logger,
            show_dialog=show_dialog,
        )

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        report_main_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            app_name=app_name,
            logger=logger,
            show_dialog=show_dialog,
        )

    sys.excepthook = _sys_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook
