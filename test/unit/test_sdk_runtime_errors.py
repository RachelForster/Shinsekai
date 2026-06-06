import logging

import pytest

from sdk.exception import handler, types


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
        "packageName": "mem0ai",
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
    monkeypatch.setattr(handler, "show_error_dialog", lambda *args, **kwargs: calls.append(args) or True)

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
