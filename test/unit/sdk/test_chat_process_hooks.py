"""Public lifecycle contracts stay immutable, typed and failure-isolated."""

from dataclasses import FrozenInstanceError

import pytest

from sdk import ChatProcessContext, ChatProcessEvent
from sdk.hooks import PluginHookDispatcher, PluginHookEvent
from sdk.register import PluginCapabilityRegistry


@pytest.mark.parametrize("event", list(ChatProcessEvent))
def test_registry_publishes_typed_process_events_in_order(event):
    registry = PluginCapabilityRegistry()
    calls = []
    registry.register_chat_process_hook(
        event, lambda context: calls.append(("first", context))
    )
    registry.register_chat_process_hook(
        event.value, lambda context: calls.append(("second", context))
    )
    context = ChatProcessContext(event, session_id="session", pid=123)
    registry.hook_dispatcher.dispatch_chat_process(context)
    assert calls == [("first", context), ("second", context)]
    assert registry.hook_dispatcher.has_hooks(event.value)


def test_context_normalizes_string_events_and_cannot_be_mutated():
    context = ChatProcessContext("chat_process_started", pid=123)
    assert context.event is ChatProcessEvent.STARTED
    with pytest.raises(FrozenInstanceError):
        context.pid = 456
    assert not hasattr(context, "environment")
    assert not hasattr(context, "state")


def test_observer_failure_does_not_hide_later_cleanup_observers():
    dispatcher = PluginHookDispatcher()
    calls = []

    def broken(_context):
        raise RuntimeError("observer failed")

    dispatcher.register_chat_process(ChatProcessEvent.STOPPED, broken, label="broken")
    dispatcher.register_chat_process(
        ChatProcessEvent.STOPPED, calls.append, label="cleanup"
    )
    context = ChatProcessContext(ChatProcessEvent.STOPPED, pid=123)
    dispatcher.dispatch_chat_process(context)
    assert calls == [context]


@pytest.mark.parametrize("event", ["unknown", "before_chat"])
def test_process_registration_rejects_other_hook_families(event):
    with pytest.raises(ValueError):
        PluginHookDispatcher().register_chat_process(event, lambda _: None)


def test_process_registration_requires_a_callable():
    with pytest.raises(TypeError):
        PluginHookDispatcher().register_chat_process(ChatProcessEvent.STARTED, None)


def test_dispatch_requires_matching_typed_context():
    dispatcher = PluginHookDispatcher()
    with pytest.raises(TypeError):
        dispatcher.dispatch_chat_process(object())
    with pytest.raises(TypeError):
        dispatcher.dispatch(PluginHookEvent.CHAT_PROCESS_STARTED, object())
    with pytest.raises(ValueError):
        dispatcher.dispatch(
            PluginHookEvent.CHAT_PROCESS_STARTED,
            ChatProcessContext(ChatProcessEvent.STOPPED),
        )


def test_process_registration_supports_existing_on_prefix_and_clear():
    dispatcher = PluginHookDispatcher()
    calls = []
    dispatcher.register_chat_process("on_chat_process_started", calls.append)
    dispatcher.clear()
    dispatcher.dispatch_chat_process(ChatProcessContext(ChatProcessEvent.STARTED))
    assert calls == []
