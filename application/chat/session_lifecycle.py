"""Own ordered session effects and publish their lifecycle observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import logging
from pathlib import Path
from typing import Any
import uuid

from application.chat.events import LifecycleDispatchError, LifecycleEvents
from application.chat.lifecycle import chat_lifecycle_lock
from sdk.chat_process import ChatProcessContext, ChatProcessEvent
from sdk.chat_session import ChatSessionContext, ChatSessionEvent

logger = logging.getLogger(__name__)


@dataclass
class SessionEffects:
    configure_mobile: Callable[..., Any]
    stop_mobile: Callable[[Any], None]
    remember_history: Callable[[Any, str | Path], bool]
    clear_story: Callable[[Any], None]


@dataclass(frozen=True)
class SessionPlan:
    session_id: str
    launch_id: str
    history_path: str | Path = ""
    mobile_enabled: bool | None = None
    mobile_on_connected: bool = False
    remember_on_connected: bool = False


class ChatSessionLifecycle:
    """One bridge state's resources, scoped by session and unique launch identity.

    The application handlers are mandatory and report failures. SDK/plugin
    observers receive only immutable metadata after those handlers are attempted.
    Child signalling, process logs and history saving remain with their owners.
    """

    def __init__(
        self, state: Any, events: LifecycleEvents, effects: SessionEffects
    ) -> None:
        self.state, self.events, self.effects = state, events, effects
        self.plan: SessionPlan | None = None
        self._stream = None
        self._connected = self._ready = self._closing = self._ended = False
        self._mobile_applied = self._history_remembered = False
        self._explicit_close = False
        self._released_sessions: set[str] = set()
        self._remove = events.subscribe(self._handle, required=True, weak=True)

    def begin(
        self,
        session_id: str,
        *,
        history_path: str | Path = "",
        mobile_enabled: bool | None = None,
        mobile_on_connected: bool = False,
        remember_on_connected: bool = False,
    ) -> str:
        with chat_lifecycle_lock(self.state):
            self.plan = SessionPlan(
                session_id=session_id,
                launch_id=uuid.uuid4().hex,
                history_path=history_path,
                mobile_enabled=mobile_enabled,
                mobile_on_connected=mobile_on_connected,
                remember_on_connected=remember_on_connected,
            )
            self._stream = getattr(self.state, "chat_stream", None)
            self.state.chat_session_launch_id = self.plan.launch_id
            self.state.chat_lifecycle_error = ""
            self._connected = self._ready = self._closing = self._ended = False
            self._mobile_applied = self._history_remembered = False
            self._explicit_close = False
            return self.plan.launch_id

    def adopt_current(self) -> SessionPlan:
        current_id = str(
            (getattr(self.state, "chat_session", {}) or {}).get("sessionId") or ""
        ).strip()
        if self.plan is None or (
            self._ended and current_id and current_id != self.plan.session_id
        ):
            self.begin(
                str(
                    (getattr(self.state, "chat_session", {}) or {}).get("sessionId")
                    or ""
                ).strip()
            )
        return self.plan

    def _owns(self, context: ChatSessionContext | ChatProcessContext) -> bool:
        return (
            self.plan is not None
            and context.launch_id == self.plan.launch_id
            and context.session_id == self.plan.session_id
            and getattr(self.state, "chat_session_launch_id", "") == self.plan.launch_id
            and str(
                (getattr(self.state, "chat_session", {}) or {}).get("sessionId") or ""
            )
            in {self.plan.session_id, ""}
        )

    def _complete(
        self,
        phase: ChatSessionEvent,
        *actions: Callable[[], Any],
        reason: str = "",
        error: BaseException | None = None,
    ) -> Any:
        failure = None
        result = None
        with chat_lifecycle_lock(self.state):
            plan = self.adopt_current()
            context = ChatSessionContext(
                phase, plan.session_id, plan.launch_id, reason, error
            )
            try:
                result = self._steps(*actions)
            except LifecycleDispatchError as cleanup_error:
                failure = cleanup_error
                context = replace(context, error=error or failure)
        self.events.emit(context)
        if failure is not None:
            raise failure
        return result

    def connected(self) -> None:
        if not self._connected:
            self._connected = True
            self._complete(
                ChatSessionEvent.CONNECTED,
                lambda: self._ready_effects(
                    mobile=self.plan.mobile_on_connected,
                    history=self.plan.remember_on_connected,
                ),
            )

    def launch(self, start: Callable[[], str]) -> str:
        try:
            return start()
        except BaseException as error:
            self.failed(str(error), error)
            raise

    def ready(self, history_path: str | Path = "") -> None:
        plan = self.adopt_current()
        if history_path:
            self.plan = replace(plan, history_path=history_path)
        if not self._ready:
            self._ready = True
            self._complete(ChatSessionEvent.READY, self._ready_effects)

    def prepare_close(self) -> None:
        self.adopt_current()
        self._explicit_close = True

    def closing(
        self,
        reason: str,
        *,
        notify_transport: bool = True,
        capture_snapshot: Callable[[], dict] | None = None,
    ) -> dict | None:
        if self._ended:
            return None
        plan = self.adopt_current()
        if not self._closing:
            snapshot = self._complete(
                ChatSessionEvent.CLOSING,
                lambda: self._close_transport(reason, notify=notify_transport),
                lambda: self.effects.stop_mobile(self.state),
                capture_snapshot or (lambda: None),
                reason=reason,
            )
            if self.plan.launch_id == plan.launch_id:
                self._closing = notify_transport
            return snapshot
        return None

    def ended(self, reason: str, *, expected_launch_id: str | None = None) -> None:
        if expected_launch_id is not None and (
            self.plan is None or self.plan.launch_id != expected_launch_id
        ):
            return
        if not self._ended:
            plan = self.adopt_current()
            self._complete(
                ChatSessionEvent.ENDED,
                self._end_transport,
                lambda: self.effects.clear_story(self.state),
                reason=reason,
            )
            if self.plan.launch_id == plan.launch_id:
                self._ended = True

    def failed(self, reason: str, error: BaseException | None = None) -> None:
        if not self._ended:
            plan = self.adopt_current()
            self._complete(
                ChatSessionEvent.FAILED,
                lambda: self._close_transport(reason),
                lambda: self.effects.stop_mobile(self.state),
                self._end_transport,
                lambda: self.effects.clear_story(self.state),
                reason=reason,
                error=error,
            )
            if self.plan.launch_id == plan.launch_id:
                self._ended = True

    def dispose(self) -> None:
        self._remove()

    def report_failure(
        self,
        error: BaseException,
        *,
        session_id: str,
        launch_id: str = "",
        reason: str = "Chat initialization did not complete.",
    ) -> None:
        """Report the original attempt after its owner has attempted shutdown."""
        if (
            not launch_id
            and self.plan is not None
            and self.plan.session_id == session_id
        ):
            launch_id = self.plan.launch_id
        context = ChatSessionContext(
            ChatSessionEvent.FAILED, session_id, launch_id, reason, error
        )
        with chat_lifecycle_lock(self.state):
            if self._owns(context) and not self._ended:
                self.failed(reason, error)
            else:
                self.events.emit(context)

    def _steps(self, *actions: Callable[[], Any]) -> Any:
        errors = []
        result = None
        for action in actions:
            try:
                result = action()
            except Exception as error:
                errors.append(error)
        if errors:
            self.state.chat_lifecycle_error = str(errors[0])
            raise LifecycleDispatchError(tuple(errors))
        return result

    def _close_transport(self, reason: str, *, notify: bool = True) -> None:
        plan = self.plan
        if notify and plan.session_id and self._stream is not None:
            get_snapshot = getattr(self._stream, "get_snapshot", None)
            snapshot = get_snapshot(plan.session_id) if callable(get_snapshot) else None
            if (
                not isinstance(snapshot, dict)
                or not str(snapshot.get("sessionClosedReason") or "").strip()
            ):
                closer = getattr(self._stream, "close_session", None)
                if callable(closer):
                    closer(plan.session_id, reason=reason)

    def _end_transport(self) -> None:
        plan = self.plan
        self.release_stream(plan.session_id)

    def release_stream(self, session_id: str) -> None:
        """Release one initialization/runtime stream without touching another session."""
        with chat_lifecycle_lock(self.state):
            stream = (
                self._stream
                if self.plan is not None and self.plan.session_id == session_id
                else getattr(self.state, "chat_stream", None)
            )
            deleter = getattr(stream, "delete_session", None)
            try:
                if (
                    session_id
                    and session_id not in self._released_sessions
                    and callable(deleter)
                ):
                    deleter(session_id)
                    self._released_sessions.add(session_id)
            finally:
                if (
                    str(
                        (getattr(self.state, "chat_session", {}) or {}).get("sessionId")
                        or ""
                    )
                    == session_id
                ):
                    self.state.chat_session = {
                        **(getattr(self.state, "chat_session", {}) or {}),
                        "sessionId": "",
                    }

    def _ready_effects(self, *, mobile: bool = True, history: bool = True) -> None:
        plan = self.plan
        if mobile and plan.mobile_enabled is not None and not self._mobile_applied:
            self.effects.configure_mobile(self.state, enabled=plan.mobile_enabled)
            self._mobile_applied = True
        if history and plan.history_path and not self._history_remembered:
            if not self.effects.remember_history(self.state, plan.history_path):
                logger.warning(
                    "Ready chat history path could not be remembered",
                    extra={"history_path": str(plan.history_path)},
                )
            self._history_remembered = True

    def _handle(self, context: Any) -> None:
        if not isinstance(context, ChatProcessContext) or not self._owns(context):
            return
        if context.event not in {
            ChatProcessEvent.STOPPED,
            ChatProcessEvent.FAILED,
        }:
            return
        with chat_lifecycle_lock(self.state):
            if not self._owns(context) or self._ended:
                return
            if self._explicit_close:
                return
            if context.reason == "shutdown" and context.exit_code is None:
                self.state.chat_lifecycle_error = str(
                    context.error or "Chat process did not exit"
                )
                return
            if context.event is ChatProcessEvent.FAILED:
                self.failed(context.reason or "Chat process failed", context.error)
            else:
                self.closing("聊天会话已结束。")
                self.ended("聊天会话已结束。", expected_launch_id=context.launch_id)
