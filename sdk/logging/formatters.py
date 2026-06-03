"""Human-readable and JSONL logging formatters."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sdk.logging.context import LOG_CONTEXT_FIELDS
from sdk.logging.redaction import redact_value


_RESERVED_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_RECORD_FIELDS or key.startswith("_"):
            continue
        extras[key] = redact_value(value, key=key)
    return extras


class JsonLineFormatter(logging.Formatter):
    """Format one log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_value(record.getMessage(), key="formatted_message"),
            "pid": record.process,
            "thread": record.threadName,
        }
        payload.update(_record_extras(record))
        if record.exc_info:
            payload["exception"] = redact_value(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = redact_value(self.formatStack(record.stack_info))
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    """Compact text formatter for terminals and captured stdio."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone().strftime("%H:%M:%S")
        event = getattr(record, "event", "")
        context = " ".join(
            f"{field}={getattr(record, field)}"
            for field in LOG_CONTEXT_FIELDS
            if getattr(record, field, None) not in (None, "")
        )
        prefix = f"{timestamp} [{record.levelname}] {record.name}"
        if event:
            prefix += f" {event}"
        if context:
            prefix += f" [{context}]"
        text = f"{prefix}: {redact_value(record.getMessage(), key='formatted_message')}"
        if record.exc_info:
            text += "\n" + str(redact_value(self.formatException(record.exc_info)))
        return text
