"""Tests for the public SDK logging facade."""

from __future__ import annotations

import json
import logging

from sdk.logging import configure_logging, get_logger, log_context, shutdown_logging


def test_sdk_logger_writes_context_and_redacts_content(tmp_path):
    shutdown_logging()
    path = configure_logging(
        "test-host",
        project_root=tmp_path,
        console=False,
        replace_handlers=False,
        install_exception_hooks=False,
    )
    assert path is not None

    logger = get_logger("test.plugin", plugin_id="example.plugin")
    with log_context(task_id="task-123"):
        logger.info(
            "request token=%s",
            "secret-value",
            extra={
                "event": "plugin.request.started",
                "user_input": "private message",
            },
        )

    shutdown_logging()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    row = next(item for item in rows if item.get("event") == "plugin.request.started")
    runtime_row = next(item for item in rows if item.get("event") == "runtime.environment")

    assert row["app"] == "test-host"
    assert row["session_id"].startswith("session_")
    assert row["plugin_id"] == "example.plugin"
    assert row["task_id"] == "task-123"
    assert row["user_input"].startswith("<redacted")
    assert "secret-value" not in row["message"]
    assert runtime_row["python_version"]
    assert runtime_row["project_root"] == tmp_path.as_posix()
    assert isinstance(runtime_row["gpus"], list)
    assert runtime_row["gpu_count"] == len(runtime_row["gpus"])


def test_sdk_logger_is_plain_logging_without_host_configuration():
    shutdown_logging()
    logger = get_logger("test.unconfigured")
    assert isinstance(logger, logging.Logger)
