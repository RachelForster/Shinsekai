"""Compatibility facade for the migrated event protocol and WS transport."""

from __future__ import annotations

import importlib

_events = importlib.import_module("application.runtime.event_sink")

EVENT_PROTOCOL_VERSION = _events.EVENT_PROTOCOL_VERSION
ChatEventSink = _events.ChatEventSink
NullEventSink = _events.NullEventSink
build_event = _events.build_event
fold_event_into_snapshot = _events.fold_event_into_snapshot
make_empty_chat_snapshot = _events.make_empty_chat_snapshot


def __getattr__(name: str):
    if name == "WSClientSink":
        transport = importlib.import_module(
            "frontend_bridge_core.transport.ws_client"
        )
        return transport.WSClientSink
    raise AttributeError(name)


__all__ = [
    "EVENT_PROTOCOL_VERSION",
    "ChatEventSink",
    "NullEventSink",
    "WSClientSink",
    "build_event",
    "fold_event_into_snapshot",
    "make_empty_chat_snapshot",
]
