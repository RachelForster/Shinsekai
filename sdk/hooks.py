"""Plugin lifecycle hook dispatcher and context objects."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Any

logger = logging.getLogger(__name__)


class PluginHookEvent(str, Enum):
    BEFORE_COMPACT = "before_compact"
    MESSAGE_ADDED = "message_added"
    BEFORE_CHAT = "before_chat"


@dataclass(frozen=True)
class HookRegistration:
    event: PluginHookEvent
    hook: Callable[[Any], None]
    label: str
    order: int
    legacy_hook: Callable[[list[dict[str, Any]]], None] | None = None


@dataclass
class BeforeCompactContext:
    messages: list[dict[str, Any]]
    older_messages: list[dict[str, Any]]
    recent_messages: list[dict[str, Any]]


@dataclass
class MessageAddedContext:
    role: str
    message: dict[str, Any]
    messages: list[dict[str, Any]]


@dataclass
class BeforeChatContext:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    generation_kwargs: dict[str, Any]
    stream: bool


@dataclass
class ShutdownHookRegistration:
    order: int
    label: str
    action: Callable[[], None]


@dataclass
class ShutdownHookRegistry:
    _hooks: list[ShutdownHookRegistration] = field(default_factory=list)
    _next_order: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def register(
        self,
        action: Callable[[], None],
        *,
        label: str = "shutdown_hook",
    ) -> Callable[[], None]:
        if not callable(action):
            raise TypeError("shutdown hook action must be callable")
        clean_label = str(label or "shutdown_hook").strip() or "shutdown_hook"
        with self._lock:
            registration = ShutdownHookRegistration(
                order=self._next_order,
                label=clean_label,
                action=action,
            )
            self._next_order += 1
            self._hooks.append(registration)

        def unregister() -> None:
            self.unregister(registration)

        return unregister

    def unregister(self, registration: ShutdownHookRegistration) -> None:
        with self._lock:
            try:
                self._hooks.remove(registration)
            except ValueError:
                pass

    def clear(self) -> None:
        with self._lock:
            self._hooks.clear()
            self._next_order = 0

    def steps(self) -> list[tuple[str, Callable[[], None]]]:
        with self._lock:
            hooks = sorted(self._hooks, key=lambda item: item.order)
        return [(hook.label, hook.action) for hook in hooks]


_shutdown_hook_registry = ShutdownHookRegistry()


def register_shutdown_hook(
    action: Callable[[], None],
    *,
    label: str = "shutdown_hook",
) -> Callable[[], None]:
    """Register a process-local shutdown hook and return an unregister function."""

    return _shutdown_hook_registry.register(action, label=label)


def clear_shutdown_hooks() -> None:
    """Clear registered shutdown hooks. Intended for tests and fresh runtimes."""

    _shutdown_hook_registry.clear()


def iter_shutdown_hooks() -> list[tuple[str, Callable[[], None]]]:
    """Return registered shutdown hooks in registration order."""

    return _shutdown_hook_registry.steps()


class PluginHookDispatcher:
    """Owns registered plugin lifecycle hooks and dispatches them safely."""

    def __init__(self) -> None:
        self._hooks: dict[PluginHookEvent, list[HookRegistration]] = {
            event: [] for event in PluginHookEvent
        }
        self._next_order = 0

    def clear(self) -> None:
        for hooks in self._hooks.values():
            hooks.clear()
        self._next_order = 0

    def register(
        self,
        event: PluginHookEvent | str,
        hook: Callable[[Any], None],
        *,
        label: str = "",
        legacy_hook: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        event_key = self._normalize_event(event)
        registration = HookRegistration(
            event=event_key,
            hook=hook,
            label=label or getattr(hook, "__name__", "") or event_key.value,
            order=self._next_order,
            legacy_hook=legacy_hook,
        )
        self._next_order += 1
        self._hooks[event_key].append(registration)

    def register_before_compact(
        self,
        hook: Callable[[BeforeCompactContext], None],
        *,
        label: str = "",
        legacy_hook: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        self.register(
            PluginHookEvent.BEFORE_COMPACT,
            hook,
            label=label,
            legacy_hook=legacy_hook,
        )

    def register_message_added(
        self,
        hook: Callable[[MessageAddedContext], None],
        *,
        label: str = "",
    ) -> None:
        self.register(PluginHookEvent.MESSAGE_ADDED, hook, label=label)

    def register_before_chat(
        self,
        hook: Callable[[BeforeChatContext], None],
        *,
        label: str = "",
    ) -> None:
        self.register(PluginHookEvent.BEFORE_CHAT, hook, label=label)

    def has_hooks(self, event: PluginHookEvent | str) -> bool:
        return bool(self._hooks[self._normalize_event(event)])

    @property
    def legacy_compact_hooks(self) -> list[Callable[[list[dict[str, Any]]], None]]:
        return [
            registration.legacy_hook
            for registration in self._hooks[PluginHookEvent.BEFORE_COMPACT]
            if registration.legacy_hook is not None
        ]

    def dispatch(
        self,
        event: PluginHookEvent | str,
        context: Any,
    ) -> None:
        event_key = self._normalize_event(event)
        for registration in list(self._hooks[event_key]):
            try:
                registration.hook(context)
            except Exception as exc:
                logger.warning(
                    "Plugin hook %s failed in %s: %s",
                    event_key.value,
                    registration.label,
                    exc,
                    exc_info=True,
                )

    def dispatch_before_compact(self, context: BeforeCompactContext) -> None:
        self.dispatch(PluginHookEvent.BEFORE_COMPACT, context)

    def dispatch_message_added(self, context: MessageAddedContext) -> None:
        self.dispatch(PluginHookEvent.MESSAGE_ADDED, context)

    def dispatch_before_chat(self, context: BeforeChatContext) -> None:
        self.dispatch(PluginHookEvent.BEFORE_CHAT, context)

    def _normalize_event(self, event: PluginHookEvent | str) -> PluginHookEvent:
        if isinstance(event, PluginHookEvent):
            return event
        value = str(event).strip()
        if value.startswith("on_"):
            value = value[3:]
        return PluginHookEvent(value)
