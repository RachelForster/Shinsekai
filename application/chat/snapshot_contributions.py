"""Field-owned snapshot extensions with detached, recursively read-only inputs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from application.runtime.event_sink import make_empty_chat_snapshot


def _readonly(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _readonly(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_readonly(item) for item in value)
    return deepcopy(value)


def _copy_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_payload(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class SnapshotContext:
    session: Mapping[str, Any]
    snapshot: Mapping[str, Any]
    streaming: bool

    @classmethod
    def create(
        cls, session: dict[str, Any], snapshot: dict[str, Any], *, streaming: bool,
    ) -> SnapshotContext:
        return cls(_readonly(session), _readonly(snapshot), streaming)


# Stable base/wire fields cannot be claimed implicitly, even if absent on one path.
CORE_SNAPSHOT_FIELDS = frozenset(make_empty_chat_snapshot()) | frozenset({
    "backgroundPath", "characterName", "dialogText", "dialogHtml", "eventSeq",
    "historyEntries", "historyPath", "inputDraft", "numericInfo", "options",
    "experimentalFeatures", "runtimeMode", "sprites", "status", "statusMessage",
    "userDisplayName", "voiceLanguage", "chatProcessRunning", "chatRuntimeClosing",
    "turnOptions", "wsUrl", "sessionId", "sessionClosedReason", "conversationTree",
    "initTask", "authToken", "producerEndpoint",
    "notificationText", "backgroundColor", "backgroundLayers", "backgroundTransition",
})


SnapshotContributor = Callable[[SnapshotContext], Mapping[str, Any]]


class SnapshotContributors:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, tuple[frozenset[str], SnapshotContributor, bool]] = {}
        self._owners: dict[str, str] = {}

    def register(
        self,
        name: str,
        fields: set[str],
        contribute: SnapshotContributor,
        *,
        allow_core_override: frozenset[str] = frozenset(),
        after_extra_on_stream: bool = False,
    ) -> None:
        owned = frozenset(fields)
        if (
            not name or not owned
            or not all(isinstance(field, str) and field for field in owned)
            or not allow_core_override <= owned
        ):
            raise ValueError("Snapshot contributor requires a name and declared fields")
        if owned & (CORE_SNAPSHOT_FIELDS - allow_core_override):
            raise ValueError("Snapshot contributor cannot own protected core fields")
        with self._lock:
            if name in self._entries or owned & self._owners.keys():
                raise ValueError("Duplicate snapshot contributor or field ownership")
            self._entries[name] = (owned, contribute, after_extra_on_stream)
            self._owners.update({field: name for field in owned})

    def project(self, context: SnapshotContext, *, after_extra: bool = False) -> dict[str, Any]:
        with self._lock:
            entries = tuple(self._entries.values())
        result: dict[str, Any] = {}
        for owned, contribute, late in entries:
            if late != after_extra:
                continue
            patch = contribute(context)
            if not isinstance(patch, Mapping) or set(patch) - owned:
                raise ValueError("Snapshot contributor wrote undeclared fields")
            result.update(_copy_payload(patch))
        return result
