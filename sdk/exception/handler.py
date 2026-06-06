from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from typing import Any, NoReturn

from sdk.exception.types import ExceptionInfo, classify_exception


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
    error_info: ExceptionInfo | None,
) -> str:
    if error_info and error_info["kind"] == "missing_dependency":
        return (
            f"{app_name} 启动失败，缺少 Python 模块：{error_info['moduleName']}\n\n"
            f"建议安装包：{error_info['packageName']}\n"
            "安装依赖后请重新启动聊天。"
        )
    if error_info and error_info["kind"] == "http_client":
        detail = f"请求地址：{error_info['url']}\n" if error_info["url"] else ""
        if error_info["timeout"]:
            reason = "网络请求超时"
        elif error_info["statusCode"] is not None:
            reason = f"网络请求返回 HTTP {error_info['statusCode']}"
        else:
            reason = "网络请求失败"
        return f"{app_name} 启动失败：{reason}\n\n{detail}{error_info['message']}"
    return f"{app_name} 启动失败：{type(exc).__name__}: {exc}"


def _write_stderr(
    app_name: str,
    exc_type: type[BaseException],
    exc: BaseException,
    detail: str,
    error_info: ExceptionInfo | None,
) -> None:
    if error_info and error_info["kind"] == "missing_dependency":
        header = (
            f"{app_name} startup failed: Missing Python module: {error_info['moduleName']}\n"
            f"Suggested package: {error_info['packageName']}\n"
        )
    elif error_info and error_info["kind"] == "http_client":
        header = (
            f"{app_name} startup failed: HTTP client error: {error_info['errorType']}\n"
            f"URL: {error_info['url']}\n"
            f"Status code: {error_info['statusCode']}\n"
            f"Timeout: {error_info['timeout']}\n"
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
    error_info = classify_exception(exc)
    error_kind = error_info["kind"] if error_info else ""
    event = f"main.{error_kind}" if error_kind else "main.uncaught_exception"
    target_logger = logger or logging.getLogger("shinsekai.main")

    try:
        target_logger.critical(
            "main.py failed during startup/runtime",
            exc_info=(exc_type, exc, tb),
            extra={
                "event": event,
                "error_kind": error_kind,
                "module_name": error_info.get("moduleName", "") if error_info else "",
                "package_name": error_info.get("packageName", "") if error_info else "",
                "http_status_code": error_info.get("statusCode") if error_info else None,
                "http_url": error_info.get("url", "") if error_info else "",
                "http_timeout": error_info.get("timeout") if error_info else None,
            },
        )
    except Exception:
        pass

    _write_stderr(app_name, exc_type, exc, detail, error_info)
    if _should_show_dialog(show_dialog):
        show_error_dialog(
            f"{app_name} 启动失败",
            _format_dialog_message(app_name, exc, error_info),
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
