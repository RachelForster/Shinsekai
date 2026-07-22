import logging
import sys
import threading
from types import SimpleNamespace

import pytest

from sdk.exception import handler, presenter, types


def test_runtime_dependency_error_maps_opencc_package():
    error = types.runtime_dependency_error_from_text(
        "ModuleNotFoundError: No module named 'opencc'"
    )

    assert error == {
        "kind": "missing_dependency",
        "message": "Missing Python module: opencc",
        "moduleName": "opencc",
        "packageName": "opencc-python-reimplemented",
    }


def test_missing_module_from_exception_prefers_module_name():
    exc = ModuleNotFoundError("No module named 'opencc'", name="opencc")

    assert types.missing_module_from_exception(exc) == "opencc"
    assert types.package_for_module("opencc") == "opencc-python-reimplemented"


def test_runtime_dependency_error_maps_mem0_package():
    error = types.runtime_dependency_error_from_text("ModuleNotFoundError: No module named 'mem0'")

    assert error == {
        "kind": "missing_dependency",
        "message": "Missing Python module: mem0",
        "moduleName": "mem0",
        "packageName": "mem0ai[extras]",
    }


def test_runtime_dependency_error_maps_huggingface_hub_package():
    error = types.runtime_dependency_error_from_text(
        "ModuleNotFoundError: No module named 'huggingface_hub'"
    )

    assert error == {
        "kind": "missing_dependency",
        "message": "Missing Python module: huggingface_hub",
        "moduleName": "huggingface_hub",
        "packageName": "huggingface-hub",
    }


class _FakeHttpxTimeout(Exception):
    __module__ = "httpx"


class _FakeHttpxStatusError(Exception):
    __module__ = "httpx"


APITimeoutError = type("APITimeoutError", (Exception,), {"__module__": "openai"})
RateLimitError = type("RateLimitError", (Exception,), {"__module__": "openai._exceptions"})
AnthropicAPITimeoutError = type("APITimeoutError", (Exception,), {"__module__": "anthropic"})


class _FakeRequest:
    url = "https://example.test/api"


class _FakeResponse:
    request = _FakeRequest()
    status_code = 502


def _http_status_error(message: str, status_code: int):
    error_cls = type("APIStatusError", (Exception,), {"__module__": "openai"})

    class _Response:
        request = _FakeRequest()

    _Response.status_code = status_code
    exc = error_cls(message)
    exc.response = _Response()
    return exc


def test_classify_exception_maps_httpx_timeout():
    exc = _FakeHttpxTimeout("request timed out")
    exc.request = _FakeRequest()

    assert types.classify_exception(exc) == {
        "kind": "http_client",
        "message": "HTTP request failed: request timed out",
        "errorType": "_FakeHttpxTimeout",
        "timeout": True,
        "statusCode": None,
        "url": "https://example.test/api",
    }


def test_classify_exception_maps_httpx_status_error():
    exc = _FakeHttpxStatusError("Bad Gateway")
    exc.response = _FakeResponse()

    assert types.http_client_error_from_exception(exc) == {
        "kind": "http_client",
        "message": "HTTP request failed: Bad Gateway",
        "errorType": "_FakeHttpxStatusError",
        "timeout": False,
        "statusCode": 502,
        "url": "https://example.test/api",
    }


def test_classify_exception_maps_openai_timeout():
    exc = APITimeoutError("request timed out")
    exc.request = _FakeRequest()

    assert types.classify_exception(exc) == {
        "kind": "http_client",
        "message": "HTTP request failed: request timed out",
        "errorType": "APITimeoutError",
        "timeout": True,
        "statusCode": None,
        "url": "https://example.test/api",
    }


def test_classify_exception_maps_openai_status_error():
    exc = RateLimitError("rate limited")
    exc.response = _FakeResponse()

    assert types.http_client_error_from_exception(exc) == {
        "kind": "http_client",
        "message": "HTTP request failed: rate limited",
        "errorType": "RateLimitError",
        "timeout": False,
        "statusCode": 502,
        "url": "https://example.test/api",
    }


def test_classify_exception_marks_unpaired_tool_messages_reason():
    exc = _http_status_error(
        "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'",
        400,
    )

    assert types.http_client_error_from_exception(exc) == {
        "kind": "http_client",
        "message": (
            "HTTP request failed: "
            "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
        ),
        "errorType": "APIStatusError",
        "timeout": False,
        "statusCode": 400,
        "url": "https://example.test/api",
        "reason": types.HTTP_REASON_UNPAIRED_TOOL_MESSAGES,
    }
    assert types.is_unpaired_tool_messages_error(exc)


def test_unpaired_tool_messages_reason_avoids_broad_keyword_false_positive():
    exc = _http_status_error(
        "Invalid role value for tool when tool_calls are disabled by this model",
        400,
    )

    error = types.http_client_error_from_exception(exc)

    assert error is not None
    assert "reason" not in error
    assert not types.is_unpaired_tool_messages_error(exc)


def test_classify_exception_marks_missing_tool_call_id_responses_reason():
    exc = _http_status_error(
        "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'. "
        "The following tool_call_ids did not have response messages: call_1",
        400,
    )

    error = types.http_client_error_from_exception(exc)

    assert error is not None
    assert error["reason"] == types.HTTP_REASON_UNPAIRED_TOOL_MESSAGES


def test_classify_exception_maps_anthropic_timeout():
    exc = AnthropicAPITimeoutError("anthropic timeout")
    exc.request = _FakeRequest()

    assert types.http_client_error_from_exception(exc) == {
        "kind": "http_client",
        "message": "HTTP request failed: anthropic timeout",
        "errorType": "APITimeoutError",
        "timeout": True,
        "statusCode": None,
        "url": "https://example.test/api",
    }


def test_download_error_formats_http_status_for_user():
    exc = _http_status_error("permission denied", 403)

    error = types.download_error_from_exception(
        exc,
        source="huggingface",
        url="sentence-transformers/example",
    )

    assert error["kind"] == "download"
    assert error["source"] == "huggingface"
    assert error["errorType"] == "APIStatusError"
    assert error["message"] == "Download failed: HTTP request failed: permission denied"
    assert error["statusCode"] == 403
    assert error["url"] == "sentence-transformers/example"
    assert "没有权限" in error["userMessage"]


def test_download_error_formats_timeout_for_user():
    exc = _FakeHttpxTimeout("request timed out")
    exc.request = _FakeRequest()

    error = types.download_error_from_exception(exc, source="huggingface")

    assert error["errorType"] == "_FakeHttpxTimeout"
    assert error["message"] == "Download failed: HTTP request failed: request timed out"
    assert error["timeout"] is True
    assert "下载超时" in error["userMessage"]


def test_report_main_exception_writes_bridge_detectable_dependency_error(capsys):
    logger = logging.getLogger("test.runtime_errors")

    try:
        raise ModuleNotFoundError("No module named 'opencc'", name="opencc")
    except ModuleNotFoundError as exc:
        handler.report_main_exception(
            type(exc),
            exc,
            exc.__traceback__,
            app_name="Shinsekai Chat",
            logger=logger,
            show_dialog=False,
        )

    captured = capsys.readouterr()
    assert "Missing Python module: opencc" in captured.err
    assert "Suggested package: opencc-python-reimplemented" in captured.err


def test_report_main_exception_writes_http_client_error(capsys):
    logger = logging.getLogger("test.runtime_errors")
    exc = _FakeHttpxStatusError("Bad Gateway")
    exc.response = _FakeResponse()

    handler.report_main_exception(
        type(exc),
        exc,
        exc.__traceback__,
        app_name="Shinsekai Chat",
        logger=logger,
        show_dialog=False,
    )

    captured = capsys.readouterr()
    assert "HTTP client error: _FakeHttpxStatusError" in captured.err
    assert "Status code: 502" in captured.err


def test_llm_presenter_gives_balance_action_for_402():
    text = presenter.format_llm_exception_message(
        _http_status_error("payment required", 402),
        fallback_message="fallback",
    )

    assert "额度或余额不足" in text
    assert "充值" in text
    assert "payment required" in text


def test_llm_presenter_gives_auth_action_for_unauthorized_keyword():
    exc = APITimeoutError("unauthorized: invalid api key")
    exc.request = _FakeRequest()
    text = presenter.format_llm_exception_message(exc, fallback_message="fallback")

    assert "未授权" in text
    assert "API Key" in text


def test_llm_presenter_gives_rate_limit_action_for_429():
    text = presenter.format_llm_exception_message(
        _http_status_error("too many requests", 429),
        fallback_message="fallback",
    )

    assert "请求过于频繁" in text
    assert "限流" in text


def test_handle_main_exception_exits_after_reporting(capsys):
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        with pytest.raises(SystemExit) as raised:
            handler.handle_main_exception(
                exc,
                app_name="Shinsekai Chat",
                logger=logging.getLogger("test.runtime_errors"),
                show_dialog=False,
                exit_code=7,
            )

    assert raised.value.code == 7
    assert "Shinsekai Chat startup failed: RuntimeError: boom" in capsys.readouterr().err


def test_report_main_exception_can_suppress_dialog_from_bridge(monkeypatch):
    calls = []
    monkeypatch.setenv("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", "1")
    monkeypatch.setattr(
        handler,
        "show_error_dialog",
        lambda *args, **kwargs: calls.append(args) or True,
    )

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        handler.report_main_exception(
            type(exc),
            exc,
            exc.__traceback__,
            app_name="Shinsekai Chat",
            logger=logging.getLogger("test.runtime_errors"),
            show_dialog=True,
        )

    assert calls == []


def test_dialog_message_formats_dependency_http_and_generic_errors():
    dependency = types.runtime_dependency_error_from_module("opencc")
    assert "缺少 Python 模块：opencc" in handler._format_dialog_message(
        "App", ModuleNotFoundError("No module named 'opencc'"), dependency
    )

    timeout = _FakeHttpxTimeout("timed out")
    timeout.request = _FakeRequest()
    assert "网络请求超时" in handler._format_dialog_message(
        "App", timeout, types.http_client_error_from_exception(timeout)
    )

    status = _http_status_error("bad gateway", 502)
    assert "HTTP 502" in handler._format_dialog_message(
        "App", status, types.http_client_error_from_exception(status)
    )

    connection = _FakeHttpxStatusError("connection reset")
    assert "网络请求失败" in handler._format_dialog_message(
        "App", connection, types.http_client_error_from_exception(connection)
    )

    assert handler._format_dialog_message("App", RuntimeError("boom"), None) == (
        "App 启动失败：RuntimeError: boom"
    )


def test_dialog_helpers_handle_import_failure_and_single_display(monkeypatch):
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PySide6.QtWidgets":
            raise ImportError("qt missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert handler._show_qt_dialog("Title", "Message", "detail") is False
    monkeypatch.setenv("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", "1")
    assert handler._show_windows_dialog("Title", "Message") is False

    calls = []
    monkeypatch.delenv("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.delenv("SHINSEKAI_DISABLE_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.setattr(handler, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(handler, "_dialog_shown", False)
    monkeypatch.setattr(
        handler,
        "_show_qt_dialog",
        lambda title, message, detail: calls.append(("qt", detail)) or False,
    )
    monkeypatch.setattr(
        handler,
        "_show_windows_dialog",
        lambda title, message: calls.append(("win", message)) or True,
    )

    assert handler.show_error_dialog("Title", "Message", "detail") is True
    assert handler.show_error_dialog("Other", "Again", "ignored") is False
    assert calls == [("qt", "detail"), ("win", "Message")]


def test_qt_dialog_uses_owned_app_and_truncates_detail(monkeypatch):
    calls = []

    class FakeApp:
        @staticmethod
        def instance():
            return None

        def __init__(self, args):
            calls.append(("app", args))

        def quit(self):
            calls.append(("quit", None))

    class FakeBox:
        class Icon:
            Critical = "critical"

        def setIcon(self, icon):
            calls.append(("icon", icon))

        def setWindowTitle(self, title):
            calls.append(("title", title))

        def setText(self, text):
            calls.append(("text", text))

        def setDetailedText(self, detail):
            calls.append(("detail_len", len(detail)))

        def exec(self):
            calls.append(("exec", None))

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PySide6.QtWidgets":
            return SimpleNamespace(QApplication=FakeApp, QMessageBox=FakeBox)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert handler._show_qt_dialog("Title", "Message", "x" * 25000) is True
    assert ("app", []) in calls
    assert ("detail_len", 20000) in calls
    assert ("quit", None) in calls


def test_report_main_exception_still_reports_when_logger_or_stderr_fail(monkeypatch, capsys):
    class FailingLogger:
        def critical(self, *args, **kwargs):
            raise RuntimeError("logger failed")

    dialog_calls = []
    monkeypatch.delenv("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.delenv("SHINSEKAI_DISABLE_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.setattr(handler, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(
        handler,
        "show_error_dialog",
        lambda *args: dialog_calls.append(args) or True,
    )

    exc = RuntimeError("boom")
    handler.report_main_exception(
        type(exc),
        exc,
        exc.__traceback__,
        app_name="App",
        logger=FailingLogger(),
        show_dialog=True,
    )

    assert "App startup failed: RuntimeError: boom" in capsys.readouterr().err
    assert dialog_calls and dialog_calls[0][0] == "App 启动失败"

    class BrokenStderr:
        def write(self, text):
            raise OSError("closed")

        def flush(self):
            raise OSError("closed")

    monkeypatch.setattr(handler.sys, "stderr", BrokenStderr())
    handler._write_stderr("App", RuntimeError, RuntimeError("boom"), "detail", None)


def test_report_main_exception_suppresses_dialog_under_pytest(monkeypatch, capsys):
    dialog_calls = []
    monkeypatch.delenv("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.delenv("SHINSEKAI_DISABLE_MAIN_ERROR_DIALOG", raising=False)
    monkeypatch.setattr(handler, "_running_under_pytest", lambda: True)
    monkeypatch.setattr(
        handler,
        "show_error_dialog",
        lambda *args: dialog_calls.append(args) or True,
    )

    exc = RuntimeError("boom")
    handler.report_main_exception(
        type(exc),
        exc,
        exc.__traceback__,
        app_name="App",
        logger=None,
        show_dialog=True,
    )

    assert "App startup failed: RuntimeError: boom" in capsys.readouterr().err
    assert dialog_calls == []


def test_main_exception_hooks_report_sys_and_thread_exceptions(monkeypatch):
    original_sys_hook = sys.excepthook
    original_thread_hook = getattr(threading, "excepthook", None)
    calls = []
    monkeypatch.setattr(handler, "_hook_installed", False)
    monkeypatch.setattr(
        handler,
        "report_main_exception",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    try:
        handler.install_main_exception_hook(app_name="HookApp", show_dialog=False)
        sys.excepthook(RuntimeError, RuntimeError("sys"), None)
        threading.excepthook(
            SimpleNamespace(
                exc_type=ValueError,
                exc_value=ValueError("thread"),
                exc_traceback=None,
            )
        )
        handler.install_main_exception_hook(app_name="Ignored")
    finally:
        sys.excepthook = original_sys_hook
        if original_thread_hook is not None:
            threading.excepthook = original_thread_hook
        handler._hook_installed = False

    assert [call[0][0] for call in calls] == [RuntimeError, ValueError]
    assert all(call[1]["app_name"] == "HookApp" for call in calls)


def test_handle_main_exception_reraises_exit_exceptions():
    with pytest.raises(KeyboardInterrupt):
        handler.handle_main_exception(KeyboardInterrupt())

    sentinel = SystemExit(3)
    with pytest.raises(SystemExit) as raised:
        handler.handle_main_exception(sentinel)
    assert raised.value is sentinel


@pytest.mark.parametrize(
    ("status_code", "message", "timeout", "expected"),
    [
        (403, "permission denied", False, "权限不足"),
        (None, "plain timeout", True, "请求超时"),
        (503, "service unavailable", False, "服务商暂时异常"),
        (400, "bad request", False, "请求参数有误"),
        (418, "teapot", False, "HTTP 418"),
        (None, "connection reset", False, "网络请求失败"),
        (None, "quota exceeded", False, "额度或余额不足"),
    ],
)
def test_llm_http_action_message_covers_status_families(status_code, message, timeout, expected):
    assert expected in presenter.llm_http_action_message(status_code, message, timeout=timeout)


def test_llm_presenter_formats_fallback_and_missing_dependency():
    assert presenter.format_llm_exception_message(
        RuntimeError("plain failure"),
        fallback_message="fallback",
    ) == "fallback\nplain failure"

    text = presenter.format_llm_exception_message(
        ModuleNotFoundError("No module named 'opencc'", name="opencc"),
        fallback_message="fallback",
    )

    assert "缺少 Python 模块：opencc" in text
    assert "opencc-python-reimplemented" in text
