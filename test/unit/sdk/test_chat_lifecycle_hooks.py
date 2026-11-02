"""Process and session observers share one dispatch contract."""

from dataclasses import FrozenInstanceError

import pytest

from sdk import (
    ChatProcessContext,
    ChatProcessEvent,
    ChatSessionContext,
    ChatSessionEvent,
)
from sdk.hooks import PluginHookDispatcher
from sdk.register import PluginCapabilityRegistry


@pytest.fixture(
    params=[
        (ChatProcessEvent, ChatProcessContext, "register_chat_process_hook"),
        (ChatSessionEvent, ChatSessionContext, "register_chat_session_hook"),
    ],
    ids=["process", "session"],
)
def family(request):
    return request.param


@pytest.mark.parametrize("form", ["enum", "value", "prefixed"])
def test_generic_registration_query_and_dispatch_accept_same_event_forms(family, form):
    events, context_type, _ = family
    dispatcher = PluginHookDispatcher()
    called = []
    for event in events:
        key = {"enum": event, "value": event.value, "prefixed": "on_" + event.value}[form]
        context = context_type(event, session_id="session", launch_id="launch")
        dispatcher.register(key, called.append)
        assert dispatcher.has_hooks(key)
        dispatcher.dispatch(key, context)
        assert called[-1] is context
    dispatcher.clear()
    for event in events:
        assert not dispatcher.has_hooks(event)
        dispatcher.dispatch(event, context_type(event))
    assert len(called) == len(events)


def test_registry_delivers_each_event_in_order_with_stable_identity(family):
    events, context_type, register_name = family
    registry = PluginCapabilityRegistry()
    calls = []
    register = getattr(registry, register_name)
    for event in events:
        register(event, lambda context: calls.append(("first", context)))
        register("on_" + event.value, lambda context: calls.append(("second", context)))
        context = context_type(event.value, session_id="session", launch_id="launch")
        assert context.event is event
        assert registry.hook_dispatcher.has_hooks(event)
        registry.hook_dispatcher.dispatch(event, context)
        assert calls[-2:] == [("first", context), ("second", context)]
        assert context.session_id == "session"
        assert context.launch_id == "launch"
        with pytest.raises(FrozenInstanceError):
            context.launch_id = "changed"
        assert not hasattr(context, "environment")
        assert not hasattr(context, "state")


def test_observer_failure_does_not_skip_later_observers(family):
    events, context_type, register_name = family
    registry = PluginCapabilityRegistry()
    calls = []

    def broken(_context):
        raise RuntimeError("observer failed")

    register = getattr(registry, register_name)
    event = next(iter(events))
    register(event, broken, label="broken")
    register(event, calls.append)
    context = context_type(event)
    registry.hook_dispatcher.dispatch(event.value, context)
    assert calls == [context]


def test_registration_rejects_unknown_events_wrong_family_and_noncallable(family):
    events, _, register_name = family
    registry = PluginCapabilityRegistry()
    register = getattr(registry, register_name)
    other_events = ChatSessionEvent if events is ChatProcessEvent else ChatProcessEvent
    for event in ("unknown", "before_chat", next(iter(other_events))):
        with pytest.raises(ValueError):
            register(event, lambda _: None)
    with pytest.raises(TypeError):
        register(next(iter(events)), None)
    with pytest.raises(TypeError):
        registry.hook_dispatcher.register(next(iter(events)), None)


def test_dispatch_rejects_wrong_context_type_and_mismatched_event(family):
    events, context_type, _ = family
    event, different_event, *_ = events
    other_context = (
        ChatSessionContext(ChatSessionEvent.READY)
        if context_type is ChatProcessContext
        else ChatProcessContext(ChatProcessEvent.STARTED)
    )
    dispatcher = PluginHookDispatcher()
    for context in (object(), {}, other_context):
        with pytest.raises(TypeError):
            dispatcher.dispatch(event.value, context)
    with pytest.raises(ValueError):
        dispatcher.dispatch(event.value, context_type(different_event))


def test_process_metadata_is_immutable_and_distinct_from_session_readiness():
    context = ChatProcessContext(ChatProcessEvent.STARTED, pid=123, exit_code=0)
    assert context.pid == 123
    assert context.exit_code == 0
    with pytest.raises(FrozenInstanceError):
        context.pid = 456
    with pytest.raises(ValueError):
        ChatProcessContext(ChatSessionEvent.READY)
    with pytest.raises(ValueError):
        ChatSessionContext(ChatProcessEvent.STARTED)
