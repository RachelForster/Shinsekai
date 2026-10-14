"""Session milestone hooks are typed, immutable and observational."""

from dataclasses import FrozenInstanceError

import pytest

from sdk import ChatSessionContext, ChatSessionEvent
from sdk.hooks import PluginHookDispatcher
from sdk.register import PluginCapabilityRegistry


@pytest.mark.parametrize("phase", list(ChatSessionEvent))
def test_registry_delivers_session_milestones_with_stable_identity(phase):
    dispatcher = PluginHookDispatcher()
    registry = PluginCapabilityRegistry(hook_dispatcher=dispatcher)
    called = []
    registry.register_chat_session_hook(phase, called.append)
    context = ChatSessionContext(phase, "session", "launch")
    dispatcher.dispatch_chat_session(context)
    assert called == [context]
    with pytest.raises(FrozenInstanceError):
        context.launch_id = "changed"


def test_session_observer_errors_continue_to_later_hooks():
    dispatcher = PluginHookDispatcher()
    called = []

    def broken(_context):
        raise OSError("observer")

    dispatcher.register_chat_session(ChatSessionEvent.READY, broken)
    dispatcher.register_chat_session(ChatSessionEvent.READY, called.append)
    context = ChatSessionContext(ChatSessionEvent.READY)
    dispatcher.dispatch_chat_session(context)
    assert called == [context]


def test_session_dispatch_rejects_wrong_family_context_and_mismatched_phase():
    dispatcher = PluginHookDispatcher()
    with pytest.raises(ValueError):
        dispatcher.register_chat_session("chat_process_started", lambda _: None)
    with pytest.raises(TypeError):
        dispatcher.register_chat_session(ChatSessionEvent.READY, None)
    with pytest.raises(TypeError):
        dispatcher.dispatch_chat_session({})
    with pytest.raises(TypeError):
        dispatcher.dispatch(ChatSessionEvent.READY.value, {})
    with pytest.raises(ValueError):
        dispatcher.dispatch(
            ChatSessionEvent.READY.value, ChatSessionContext(ChatSessionEvent.ENDED)
        )
