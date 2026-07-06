from __future__ import annotations

import json
import importlib
import logging
import os
import sys
import threading
from types import SimpleNamespace

import pytest

from sdk.logging import configure as logging_config
from sdk.logging import formatters, timing
from sdk.logging.stopwatch import stopwatch

stopwatch_module = importlib.import_module("sdk.logging.stopwatch")


def test_json_and_console_formatters_include_context_exception_and_stack():
    record = logging.LogRecord(
        "test.logger",
        logging.ERROR,
        __file__,
        12,
        "token=%s",
        ("sk-secretvalue",),
        None,
    )
    record.event = "demo.event"
    record.task_id = "task-123"
    record.api_key = "secret"
    record.user_input = "private prompt"
    record.stack_info = "stack line"
    try:
        raise ValueError("api key = hidden")
    except ValueError:
        record.exc_info = sys.exc_info()

    payload = json.loads(formatters.JsonLineFormatter().format(record))

    assert payload["event"] == "demo.event"
    assert payload["task_id"] == "task-123"
    assert payload["api_key"] == "<redacted>"
    assert payload["user_input"].startswith("<redacted")
    assert "sk-secretvalue" not in payload["message"]
    assert "api key = <redacted>" in payload["exception"]
    assert payload["stack"] == "stack line"

    text = formatters.ConsoleFormatter().format(record)
    assert "test.logger demo.event" in text
    assert "task_id=task-123" in text
    assert "api key = <redacted>" in text


def test_stopwatch_logs_only_when_threshold_is_met(monkeypatch):
    calls = []

    class FakeLogger:
        def info(self, *args):
            calls.append(args)

    times = iter([10.0, 10.1, 20.0, 20.7])
    monkeypatch.setattr(stopwatch_module.time, "perf_counter", lambda: next(times))

    with stopwatch("fast", threshold=0.5, logger=FakeLogger()):
        pass
    with stopwatch("slow", threshold=0.5, logger=FakeLogger()) as measured:
        assert repr(measured) == "stopwatch('slow')"

    assert len(calls) == 1
    assert calls[0][0] == "[stopwatch] %s  %.3fs"
    assert calls[0][1] == "slow"
    assert calls[0][2] == pytest.approx(0.7)


def test_timing_tracker_tracks_local_cross_thread_and_reports(monkeypatch, capsys):
    tracker = timing.TimingTracker()
    tracker.reset()
    calls = []
    times = iter([1.0, 1.25, 2.0, 2.5, 3.0, 3.4])
    monkeypatch.setattr(timing.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(timing._log, "info", lambda *args: calls.append(args))

    tracker.stop("missing")
    tracker.stop_cross("missing")
    tracker.start("local")
    tracker.stop("local")
    tracker.start_cross("cross")
    tracker.stop_cross("cross")
    with tracker.track("context"):
        pass

    stats = tracker.get_stats()
    assert stats["local"]["count"] == 1
    assert stats["local"]["total_sec"] == pytest.approx(0.25)
    assert stats["cross"]["avg_sec"] == pytest.approx(0.5)
    assert stats["context"]["total_sec"] == pytest.approx(0.4)
    assert len(calls) == 3

    tracker.print_report()
    report = capsys.readouterr().out
    assert "=== Timing Report ===" in report
    assert "cross: total=0.500s" in report

    tracker.reset()
    tracker.print_report()
    assert "No timing data collected." in capsys.readouterr().out
    tracker.reset()


def test_logging_configuration_helpers_cover_common_paths(monkeypatch, tmp_path):
    assert logging_config._safe_name(" Shinsekai/App ") == "Shinsekai-App"
    assert logging_config._safe_name("!!!") == "app"

    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    assert logging_config._read_version(tmp_path) == "1.2.3"

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.paths":
            raise ImportError("resource path unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert logging_config._read_version(tmp_path / "missing") == "unknown"

    monkeypatch.setenv("SHINSEKAI_LOG_LEVEL", "DEBUG")
    assert logging_config._parse_level(None) == logging.DEBUG
    assert logging_config._parse_level(logging.WARNING) == logging.WARNING
    assert logging_config._parse_level("not-a-level") == logging.INFO

    old = tmp_path / "old.jsonl"
    current = tmp_path / "current.jsonl"
    old.write_text("old", encoding="utf-8")
    current.write_text("current", encoding="utf-8")
    os.utime(old, (1, 1))
    monkeypatch.setattr(logging_config.time, "time", lambda: 200000.0)

    logging_config._cleanup_old_logs(tmp_path, retention_days=1)
    assert not old.exists()
    assert current.exists()

    logging_config._cleanup_old_logs(tmp_path, retention_days=0)
    assert current.exists()


def test_configure_logging_handles_null_handler_existing_listener_and_file_errors(tmp_path):
    logging_config.shutdown_logging()
    blocked_log_dir = tmp_path / "not-a-dir"
    blocked_log_dir.write_text("x", encoding="utf-8")

    try:
        first_path = logging_config.configure_logging(
            "test app",
            project_root=tmp_path,
            log_dir=blocked_log_dir,
            console=False,
            file=True,
            install_exception_hooks=False,
        )
        second_path = logging_config.configure_logging(
            "other app",
            project_root=tmp_path,
            console=False,
            file=False,
            install_exception_hooks=False,
        )

        assert first_path is None
        assert second_path is None
    finally:
        logging_config.shutdown_logging()


def test_configure_logging_exception_hooks_capture_process_and_thread(monkeypatch):
    original_sys_hook = sys.excepthook
    original_thread_hook = getattr(threading, "excepthook", None)
    logger = logging.getLogger("shinsekai.uncaught")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    try:
        logger.handlers = [CaptureHandler()]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logging_config._install_exception_hooks()
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        sys.excepthook(RuntimeError, RuntimeError("boom"), None)
        threading.excepthook(
            SimpleNamespace(
                exc_type=SystemExit,
                exc_value=SystemExit(0),
                exc_traceback=None,
                thread=SimpleNamespace(name="exit-thread"),
            )
        )
        threading.excepthook(
            SimpleNamespace(
                exc_type=ValueError,
                exc_value=ValueError("thread"),
                exc_traceback=None,
                thread=SimpleNamespace(name="worker-1"),
            )
        )
    finally:
        sys.excepthook = original_sys_hook
        if original_thread_hook is not None:
            threading.excepthook = original_thread_hook
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    assert [record.getMessage() for record in records] == [
        "Uncaught exception",
        "Uncaught thread exception",
    ]
    assert records[0].event == "process.uncaught_exception"
    assert records[1].failed_thread == "worker-1"
