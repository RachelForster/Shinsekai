"""Plugin-scoped user-input transport for actions running in the frontend bridge."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from sdk.frontend_ui import _clean_identifier

__all__ = ["FrontendUserInputController"]

_MAX_TEXT_BYTES = 64 * 1024
_dispatcher_lock = threading.RLock()
_runtime_dispatcher: Callable[[dict[str, Any]], None] | None = None
_controller_token = object()


def _normalized_text(text: object) -> str:
    value = str(text or "").strip()
    if not value:
        raise ValueError("frontend user input cannot be empty")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(
            f"frontend user input cannot exceed {_MAX_TEXT_BYTES} UTF-8 bytes"
        )
    return value


def _dispatch_runtime_input(event: dict[str, Any]) -> None:
    with _dispatcher_lock:
        dispatcher = _runtime_dispatcher
    if dispatcher is None:
        raise RuntimeError("No active React Chat runtime can accept plugin input")
    dispatcher(event)


def _bind_frontend_user_input_dispatcher(
    dispatcher: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Host-only: bind the current bridge process to its active Chat stream."""
    global _runtime_dispatcher
    with _dispatcher_lock:
        _runtime_dispatcher = dispatcher


def _controller_for_plugin(plugin_id: str) -> "FrontendUserInputController":
    return FrontendUserInputController(
        _clean_identifier(plugin_id, label="plugin_id"),
        _token=_controller_token,
    )


class FrontendUserInputController:
    """Submit a user turn from a plugin action hosted by the frontend bridge."""

    __slots__ = ("_plugin_id",)

    def __init__(self, plugin_id: str, *, _token: object | None = None) -> None:
        if _token is not _controller_token:
            raise TypeError(
                "FrontendUserInputController instances must be created by "
                "register.frontend_user_input()"
            )
        self._plugin_id = plugin_id

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    def submit_text(self, text: str) -> None:
        """Forward one text turn to the active Chat runtime."""
        _dispatch_runtime_input(
            {
                "type": "plugin.user-input.submit",
                "pluginId": self._plugin_id,
                "text": _normalized_text(text),
            }
        )
