"""Runtime controls for presenting registered plugin pages in the React Chat UI."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["FrontendUIController"]

_MAX_IDENTIFIER_LENGTH = 128
_MAX_PAYLOAD_BYTES = 16 * 1024
_dispatcher_lock = threading.RLock()
_runtime_dispatcher: Callable[[dict[str, Any]], None] | None = None
_controller_token = object()


def _clean_identifier(value: object, *, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if len(cleaned) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{label} cannot exceed {_MAX_IDENTIFIER_LENGTH} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{label} cannot contain control characters")
    return cleaned


def _normalized_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("plugin page payload must be a mapping")
    try:
        encoded = json.dumps(
            dict(payload),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("plugin page payload must contain only JSON-safe values") from exc
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"plugin page payload cannot exceed {_MAX_PAYLOAD_BYTES} UTF-8 bytes"
        )
    decoded = json.loads(encoded.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("plugin page payload must encode to an object")
    return decoded


def _dispatch_runtime_event(event: dict[str, Any]) -> None:
    with _dispatcher_lock:
        dispatcher = _runtime_dispatcher
    if dispatcher is None:
        raise RuntimeError("No active React Chat runtime can present plugin pages")
    dispatcher(event)


def _bind_frontend_ui_dispatcher(
    dispatcher: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Host-only: bind the current process's trusted React Chat event dispatcher."""
    global _runtime_dispatcher
    with _dispatcher_lock:
        _runtime_dispatcher = dispatcher


def _controller_for_plugin(plugin_id: str) -> "FrontendUIController":
    return FrontendUIController(
        _clean_identifier(plugin_id, label="plugin_id"),
        _token=_controller_token,
    )


class FrontendUIController:
    """A plugin-scoped controller for presenting its registered frontend pages.

    Instances are created by :meth:`sdk.register.PluginCapabilityRegistry.frontend_ui`
    while the plugin is being initialized. Runtime presentation is intentionally
    limited to ``overlay`` so a background plugin cannot navigate the user's Chat
    window away from the active conversation.
    """

    __slots__ = ("_plugin_id",)

    def __init__(self, plugin_id: str, *, _token: object | None = None) -> None:
        if _token is not _controller_token:
            raise TypeError(
                "FrontendUIController instances must be created by register.frontend_ui()"
            )
        self._plugin_id = plugin_id

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    def present_page(
        self,
        page_id: str,
        *,
        mode: str = "overlay",
        payload: Mapping[str, Any] | None = None,
        presentation_id: str | None = None,
    ) -> str:
        """Present one registered page and return its plugin-scoped presentation ID."""
        clean_page_id = _clean_identifier(page_id, label="page_id")
        clean_mode = str(mode or "overlay").strip().lower()
        if clean_mode != "overlay":
            raise ValueError("Runtime plugin pages currently support only overlay mode")
        clean_presentation_id = _clean_identifier(
            presentation_id or uuid.uuid4().hex,
            label="presentation_id",
        )
        _dispatch_runtime_event(
            {
                "type": "plugin.page.present",
                "mode": "overlay",
                "pageId": clean_page_id,
                "payload": _normalized_payload(payload),
                "pluginId": self._plugin_id,
                "presentationId": clean_presentation_id,
            }
        )
        return clean_presentation_id

    def dismiss_page(self, presentation_id: str) -> None:
        """Dismiss a presentation previously created by this plugin."""
        _dispatch_runtime_event(
            {
                "type": "plugin.page.dismiss",
                "pluginId": self._plugin_id,
                "presentationId": _clean_identifier(
                    presentation_id,
                    label="presentation_id",
                ),
            }
        )
