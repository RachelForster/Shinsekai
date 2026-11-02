"""Narrow boundaries consumed by chat process, projection and command services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Protocol, TextIO

from sdk.chat_lifecycle import ChatProcessContext


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def send_signal(self, signum: int) -> None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


class ProcessResources(Protocol):
    process: ChildProcess | None
    log: TextIO | None
    lock: Any


@dataclass
class MemoryProcessResources:
    process: ChildProcess | None = None
    log: TextIO | None = None
    lock: Any = None

    def __post_init__(self) -> None:
        if self.lock is None:
            self.lock = threading.RLock()


class TerminationSystem(Protocol):
    def platform(self) -> str: ...
    def monotonic(self) -> float: ...
    def group_signal(self, pid: int, signum: int) -> None: ...


class LaunchSystem(Protocol):
    def popen(self, command: list[str], **kwargs: Any) -> ChildProcess: ...


@dataclass(frozen=True)
class ProcessSystem:
    platform: Callable[[], str]
    monotonic: Callable[[], float]
    group_signal: Callable[[int, int], None]
    popen: Callable[..., ChildProcess]


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    cwd: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class LaunchRejected:
    message: str


class LifecyclePublisher(Protocol):
    def __call__(self, context: ChatProcessContext) -> None: ...


class SnapshotSource(Protocol):
    def get_snapshot(self, session_id: str, **kwargs: Any) -> dict[str, Any] | None: ...


class SessionState(Protocol):
    chat_session: dict[str, Any]
    chat_stream: SnapshotSource | None


class HistoryPort(Protocol):
    def entries(self, state: SessionState) -> list[dict[str, Any]]: ...
    def resolve(self, state: SessionState, path: str | Path) -> Path: ...
    def read(self, path: Path) -> Any: ...


class StorySelectionPort(Protocol):
    def session(self, state: Any) -> Any: ...
    def publish(self, state: Any, patch: dict[str, Any], **kwargs: Any) -> None: ...


class StoryCoordinatorPort(StorySelectionPort, Protocol):
    def patch(self, state: Any) -> dict[str, Any]: ...
    def clear(self, state: Any) -> None: ...
    def discard(self, path: Path) -> None: ...


@dataclass
class StoryCoordinatorAccess:
    session: Callable[[Any], Any]
    patch: Callable[[Any], dict[str, Any]]
    publish: Callable[..., None]
    clear: Callable[[Any], None]
    discard: Callable[[Path], None]
