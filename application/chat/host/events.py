"""Application-owned lifecycle delivery; plugins are optional observers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass, replace
import logging
import threading
import weakref
from typing import Any

logger = logging.getLogger(__name__)


class LifecycleDispatchError(RuntimeError):
    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(
            "Application lifecycle handlers failed: "
            + "; ".join(str(error) for error in errors)
        )


class LifecycleEvents:
    """Attempt every required handler, then notify isolated observers.

    Delivery uses a snapshot outside the registry mutex. Required failures are
    returned to the resource owner as an exception rather than swallowed by the
    plugin observer policy. Weak subscriptions avoid retaining old bridge states.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_id = 0
        self._handlers: dict[int, tuple[Callable, bool, bool]] = {}

    def subscribe(
        self,
        handler: Callable[[Any], None],
        *,
        required: bool = False,
        weak: bool = False,
    ) -> Callable[[], None]:
        callback = weakref.WeakMethod(handler) if weak else handler
        with self._lock:
            self._next_id += 1
            identity = self._next_id
            self._handlers[identity] = (callback, required, weak)

        def unsubscribe() -> None:
            with self._lock:
                self._handlers.pop(identity, None)

        return unsubscribe

    def emit(self, context: Any) -> None:
        with self._lock:
            handlers = sorted(self._handlers.items(), key=lambda item: not item[1][1])
        errors = []
        observer_context = context
        for identity, (callback, required, weak) in handlers:
            if (
                not required
                and errors
                and observer_context is context
                and is_dataclass(context)
                and getattr(context, "error", None) is None
            ):
                observer_context = replace(
                    context, error=LifecycleDispatchError(tuple(errors))
                )
            handler = callback() if weak else callback
            if handler is None:
                with self._lock:
                    self._handlers.pop(identity, None)
                continue
            try:
                handler(context if required else observer_context)
            except Exception as error:
                if required:
                    errors.extend(
                        error.errors
                        if isinstance(error, LifecycleDispatchError)
                        else (error,)
                    )
                else:
                    logger.warning("Lifecycle observer failed", exc_info=True)
        if errors:
            raise LifecycleDispatchError(tuple(errors))
