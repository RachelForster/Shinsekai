"""Plugin-scoped game state, event, and frame ingestion SDK for real-time perception."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import json
import threading
from typing import Any

from sdk.frontend_ui import _clean_identifier

__all__ = ["PerceptionController"]

_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
_dispatcher_lock = threading.RLock()
_runtime_dispatcher: Callable[[dict[str, Any]], bool] | None = None
_controller_token = object()


def _bind_perception_dispatcher(
    dispatcher: Callable[[dict[str, Any]], bool] | None,
) -> None:
    """Host-only: bind the current process (bridge or chat runtime) to perception ingestion."""
    global _runtime_dispatcher
    with _dispatcher_lock:
        _runtime_dispatcher = dispatcher


def _dispatch_perception_payload(payload: dict[str, Any]) -> bool:
    with _dispatcher_lock:
        dispatcher = _runtime_dispatcher
    if dispatcher is None:
        return False
    return bool(dispatcher(payload))


def _controller_for_plugin(plugin_id: str) -> "PerceptionController":
    return PerceptionController(
        _clean_identifier(plugin_id, label="plugin_id"),
        _token=_controller_token,
    )


class PerceptionController:
    """Push structured game JSON states, discrete events, or frames into Perception."""

    __slots__ = ("_plugin_id",)

    def __init__(self, plugin_id: str, *, _token: object | None = None) -> None:
        if _token is not _controller_token:
            raise TypeError(
                "PerceptionController instances must be created by register.perception()"
            )
        self._plugin_id = plugin_id

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    def push_state(
        self,
        state: Mapping[str, Any],
        *,
        game: str = "",
        replace: bool = False,
    ) -> bool:
        """Merge or replace structured game JSON state in Tier-0 raw buffer."""
        if not isinstance(state, Mapping) or not state:
            raise ValueError("perception state must be a non-empty mapping")
        encoded = json.dumps(dict(state), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("perception state payload exceeds maximum allowed size")
        return _dispatch_perception_payload(
            {
                "source": f"plugin:{self._plugin_id}",
                "game": str(game or "").strip()[:64],
                "state": dict(state),
                "replaceState": bool(replace),
            }
        )

    def push_event(
        self,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        game: str = "",
    ) -> bool:
        """Append a discrete game event (e.g., 'kill', 'boss_phase_2', 'death')."""
        clean_type = str(event_type or "").strip()[:120]
        if not clean_type:
            raise ValueError("perception event_type cannot be empty")
        event_body = dict(data) if isinstance(data, Mapping) else {}
        return _dispatch_perception_payload(
            {
                "source": f"plugin:{self._plugin_id}",
                "game": str(game or "").strip()[:64],
                "events": [{"type": clean_type, "data": event_body}],
            }
        )

    def push_frame(
        self,
        image: bytes | str,
        *,
        mime_type: str = "image/jpeg",
        width: int = 0,
        height: int = 0,
        game: str = "",
    ) -> bool:
        """Submit a compressed visual frame (raw bytes or base64 string)."""
        if isinstance(image, (bytes, bytearray, memoryview)):
            raw_bytes = bytes(image)
            if not raw_bytes:
                raise ValueError("perception frame bytes cannot be empty")
            if len(raw_bytes) > _MAX_PAYLOAD_BYTES:
                raise ValueError("perception frame exceeds maximum allowed size")
            b64 = base64.b64encode(raw_bytes).decode("ascii")
        else:
            b64 = str(image or "").strip()
            if not b64:
                raise ValueError("perception frame base64 cannot be empty")
            if len(b64) > _MAX_PAYLOAD_BYTES:
                raise ValueError("perception frame exceeds maximum allowed size")
        return _dispatch_perception_payload(
            {
                "source": f"plugin:{self._plugin_id}",
                "game": str(game or "").strip()[:64],
                "imageBase64": b64,
                "mimeType": str(mime_type or "image/jpeg").strip()[:64],
                "width": max(0, int(width or 0)),
                "height": max(0, int(height or 0)),
            }
        )
