"""Public logging helpers for application code and plugins."""

from __future__ import annotations

import logging
from typing import Any


class _PluginLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        extra = dict(kwargs.get("extra") or {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str | None = None, *, plugin_id: str | None = None) -> logging.Logger:
    """Return a logger that inherits the host application's configuration.

    Plugin authors should pass ``__name__`` and may also pass their stable
    plugin identifier:

    ``logger = get_logger(__name__, plugin_id="example.plugin")``
    """
    logger = logging.getLogger(name or "shinsekai.plugin")
    if plugin_id:
        return _PluginLoggerAdapter(logger, {"plugin_id": plugin_id})  # type: ignore[return-value]
    return logger
