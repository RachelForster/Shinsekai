from __future__ import annotations

import logging

import pytest

from frontend_bridge_core.routes.api import FrontendBridgeHandler


def _handler(path: str, method: str = "GET") -> FrontendBridgeHandler:
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.path = path
    handler.command = method
    return handler


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/tasks/task-1", "GET"),
        ("/api/tasks/task-1", "OPTIONS"),
        ("/api/chat/runtime-status", "GET"),
        ("/api/chat/snapshot", "GET"),
        ("/api/health", "GET"),
        ("/api/characters/memories/status", "POST"),
        ("/api/model-assets/status", "POST"),
        ("/api/plugins/status", "GET"),
    ],
)
def test_successful_polling_requests_are_not_logged(path, method, caplog):
    caplog.set_level(logging.INFO, logger="frontend_bridge_core.routes.api")

    _handler(path, method).log_message('"%s" %s %s', f"{method} {path} HTTP/1.1", "200", "-")

    completed = [record for record in caplog.records if getattr(record, "event", "") == "http.request.completed"]
    assert completed == []


def test_failed_polling_request_is_logged(caplog):
    caplog.set_level(logging.WARNING, logger="frontend_bridge_core.routes.api")

    _handler("/api/tasks/task-1").log_message(
        '"%s" %s %s',
        "GET /api/tasks/task-1 HTTP/1.1",
        "500",
        "-",
    )

    completed = [record for record in caplog.records if getattr(record, "event", "") == "http.request.completed"]
    assert len(completed) == 1
    assert completed[0].levelno == logging.ERROR
    assert completed[0].status == 500


def test_non_polling_request_is_still_logged(caplog):
    caplog.set_level(logging.INFO, logger="frontend_bridge_core.routes.api")

    _handler("/api/config").log_message('"%s" %s %s', "GET /api/config HTTP/1.1", "200", "-")

    completed = [record for record in caplog.records if getattr(record, "event", "") == "http.request.completed"]
    assert len(completed) == 1
    assert completed[0].levelno == logging.INFO
