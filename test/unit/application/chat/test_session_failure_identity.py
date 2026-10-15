"""Late initialization failures preserve their identity after owned shutdown."""

from types import SimpleNamespace

from application.chat.host.events import LifecycleEvents
from application.chat.host.session_lifecycle import ChatSessionLifecycle, SessionEffects
from sdk.chat_session import ChatSessionEvent


def make_owner():
    calls = []
    state = SimpleNamespace(chat_session={"sessionId": "session-A"}, chat_stream=None)
    events = LifecycleEvents()
    owner = ChatSessionLifecycle(
        state,
        events,
        SessionEffects(
            configure_mobile=lambda *_args, **_kwargs: None,
            stop_mobile=lambda _: calls.append("mobile"),
            remember_history=lambda *_args: True,
            clear_story=lambda _: calls.append("story"),
        ),
    )
    owner.begin("session-A")
    return owner, state, events, calls


def test_failed_initialization_of_an_old_attempt_cannot_roll_back_a_new_session():
    owner, state, events, calls = make_owner()
    old = owner.plan
    observed = []
    events.subscribe(observed.append)
    state.chat_session = {"sessionId": "session-B"}
    owner.begin("session-B")
    error = TimeoutError("old initialization timed out")
    owner.report_failure(error, session_id=old.session_id, launch_id=old.launch_id)
    assert calls == []
    assert observed[-1].session_id == "session-A"
    assert observed[-1].launch_id == old.launch_id
    assert observed[-1].error is error


def test_failure_after_owned_shutdown_preserves_error_without_repeating_cleanup():
    owner, state, events, calls = make_owner()
    owner.closing("failed")
    owner.ended("failed")
    prior = list(calls)
    observed = []
    events.subscribe(observed.append)
    error = ValueError("provider initialization failed")
    owner.report_failure(error, session_id="session-A")
    assert calls == prior
    assert observed[-1].event is ChatSessionEvent.FAILED
    assert observed[-1].error is error
