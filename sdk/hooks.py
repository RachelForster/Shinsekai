"""Plugin lifecycle hook dispatcher and context objects."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
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
