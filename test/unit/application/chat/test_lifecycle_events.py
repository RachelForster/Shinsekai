"""Application lifecycle delivery is available without a plugin host."""

from dataclasses import FrozenInstanceError
from threading import Lock

import pytest

from application.chat.events import LifecycleDispatchError, LifecycleEvents
from sdk.chat_process import ChatProcessContext, ChatProcessEvent


def test_application_handlers_run_before_observers_and_outside_dispatch_lock():
    events = LifecycleEvents()
    calls = []
    context = ChatProcessContext(
        ChatProcessEvent.STARTED, session_id="session", launch_id="attempt"
    )
    events.subscribe(lambda ctx: calls.append(("observer", ctx)), required=False)
    events.subscribe(lambda ctx: calls.append(("application", ctx)), required=True)
    events.emit(context)
    assert calls == [("application", context), ("observer", context)]
    with pytest.raises(FrozenInstanceError):
        context.launch_id = "changed"


def test_required_failure_is_reported_after_remaining_handlers_and_observers():
    events = LifecycleEvents()
    calls = []
    error = OSError("cleanup failed")

    def broken(_context):
        raise error

    events.subscribe(broken, required=True)
    events.subscribe(lambda _: calls.append("cleanup"), required=True)
    events.subscribe(lambda _: calls.append("observer"))
    with pytest.raises(LifecycleDispatchError) as caught:
        events.emit(ChatProcessContext(ChatProcessEvent.FAILED))
    assert caught.value.errors == (error,)
    assert calls == ["cleanup", "observer"]


def test_observer_failure_is_isolated_and_unsubscribe_is_idempotent():
    events = LifecycleEvents()
    calls = []

    def broken(_context):
        raise RuntimeError("plugin failure")

    events.subscribe(broken)
    remove = events.subscribe(lambda _: calls.append(True))
    events.emit(ChatProcessContext(ChatProcessEvent.STARTING))
    remove()
    remove()
    events.emit(ChatProcessContext(ChatProcessEvent.STARTED))
    assert calls == [True]


def test_handler_can_subscribe_and_reenter_without_holding_dispatch_lock():
    events = LifecycleEvents()
    calls = []

    def callback(context):
        if context.event is ChatProcessEvent.STARTING:
            events.subscribe(lambda _: calls.append("late"))
            events.emit(ChatProcessContext(ChatProcessEvent.STARTED))

    events.subscribe(callback, required=True)
    events.emit(ChatProcessContext(ChatProcessEvent.STARTING))
    assert calls == ["late"]
