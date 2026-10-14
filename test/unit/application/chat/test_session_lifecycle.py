"""Owned session effects execute without plugins and respect launch identity."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat.events import LifecycleDispatchError, LifecycleEvents
from application.chat.session_lifecycle import ChatSessionLifecycle, SessionEffects
from sdk.chat_process import ChatProcessContext, ChatProcessEvent
from sdk.chat_session import ChatSessionContext, ChatSessionEvent


@pytest.fixture
def session():
    calls = []
    stream = SimpleNamespace(
        get_snapshot=lambda _: {},
        close_session=lambda sid, **kwargs: calls.append(("closed", sid)),
        delete_session=lambda sid: calls.append(("deleted", sid)),
    )
    state = SimpleNamespace(chat_session={"sessionId": "session-A"}, chat_stream=stream)
    events = LifecycleEvents()
    owner = ChatSessionLifecycle(
        state,
        events,
        SessionEffects(
            configure_mobile=lambda _state, **options: calls.append(
                ("mobile", options["enabled"])
            ),
            stop_mobile=lambda _: calls.append("stop-mobile"),
            remember_history=lambda _state, path: calls.append(("remember", str(path)))
            or True,
            clear_story=lambda _: calls.append("clear-story"),
        ),
    )
    owner.begin("session-A", history_path="history-A", mobile_enabled=True)
    yield SimpleNamespace(owner=owner, state=state, events=events, calls=calls)
    owner.dispose()


def test_ready_effects_wait_for_initialization_and_are_applied_once(session):
    owner = session.owner
    owner.connected()
    assert session.calls == []
    owner.ready()
    owner.ready()
    assert session.calls == [("mobile", True), ("remember", "history-A")]


def test_legacy_connected_path_applies_effects_without_claiming_initialized_ready(
    session,
):
    session.owner.plan = replace(
        session.owner.plan, mobile_on_connected=True, remember_on_connected=True
    )
    phases = []
    session.events.subscribe(lambda context: phases.append(context.event))
    session.owner.connected()
    session.owner.connected()
    assert phases == [ChatSessionEvent.CONNECTED]
    assert session.calls == [("mobile", True), ("remember", "history-A")]


@pytest.mark.parametrize(
    "phase,code", [(ChatProcessEvent.STOPPED, 0), (ChatProcessEvent.FAILED, 3)]
)
def test_detected_exit_cleans_owned_session_even_without_plugins(session, phase, code):
    plan = session.owner.plan
    context = ChatProcessContext(
        phase,
        plan.session_id,
        exit_code=code,
        launch_id=plan.launch_id,
        reason="unexpected_exit",
    )
    session.events.emit(context)
    session.events.emit(context)
    assert session.calls == [
        ("closed", "session-A"),
        "stop-mobile",
        ("deleted", "session-A"),
        "clear-story",
    ]
    assert session.state.chat_session["sessionId"] == ""


def test_explicit_stop_defers_session_cleanup_until_owner_captures_final_snapshot(
    session,
):
    owner = session.owner
    owner.prepare_close()
    plan = owner.plan
    session.events.emit(
        ChatProcessContext(
            ChatProcessEvent.STOPPED,
            plan.session_id,
            exit_code=0,
            launch_id=plan.launch_id,
            reason="shutdown",
        )
    )
    assert session.calls == []
    snapshot = owner.closing(
        "ended",
        capture_snapshot=lambda: session.calls.append("snapshot") or {"final": "A"},
    )
    assert snapshot == {"final": "A"}
    owner.ended("ended", expected_launch_id=plan.launch_id)
    assert session.calls == [
        ("closed", "session-A"),
        "stop-mobile",
        "snapshot",
        ("deleted", "session-A"),
        "clear-story",
    ]


def test_old_launch_event_does_not_clean_a_new_launch_of_the_same_session(session):
    plan = session.owner.plan
    session.owner.begin("session-A", mobile_enabled=True)
    assert session.owner.plan.launch_id != plan.launch_id
    session.events.emit(
        ChatProcessContext(
            ChatProcessEvent.FAILED,
            plan.session_id,
            exit_code=9,
            launch_id=plan.launch_id,
        )
    )
    assert session.calls == []


def test_reentrant_observer_start_cannot_make_old_close_delete_the_new_session(session):
    owner = session.owner
    original = owner.plan

    def observer(context):
        if context.event is ChatSessionEvent.CLOSING:
            session.state.chat_session = {"sessionId": "session-B"}
            owner.begin("session-B")

    session.events.subscribe(observer)
    snapshot = owner.closing("ended", capture_snapshot=lambda: {"final": "A"})
    owner.ended("ended", expected_launch_id=original.launch_id)
    assert snapshot == {"final": "A"}
    assert session.state.chat_session["sessionId"] == "session-B"
    assert ("deleted", "session-B") not in session.calls
    assert "clear-story" not in session.calls
    assert not owner._closing


def test_failure_attempts_every_cleanup_and_reports_errors(session):
    session.owner.effects.stop_mobile = Mock(side_effect=OSError("mobile failed"))
    with pytest.raises(LifecycleDispatchError) as caught:
        session.owner.failed("startup failed")
    assert "mobile failed" in str(caught.value)
    assert ("deleted", "session-A") in session.calls
    assert "clear-story" in session.calls
    assert session.state.chat_lifecycle_error == "mobile failed"


def test_plugin_failure_does_not_prevent_application_ready_or_cleanup(session):
    def broken(_context):
        raise RuntimeError("plugin failed")

    session.events.subscribe(broken)
    session.owner.ready()
    session.owner.closing("ended")
    session.owner.ended("ended")
    assert ("mobile", True) in session.calls
    assert "clear-story" in session.calls


def test_dispose_removes_core_subscription(session):
    owner = session.owner
    plan = owner.plan
    owner.dispose()
    session.events.emit(
        ChatSessionContext(ChatSessionEvent.READY, plan.session_id, plan.launch_id)
    )
    assert session.calls == []


def test_unconfirmed_shutdown_keeps_session_and_reports_failure(session):
    plan = session.owner.plan
    session.events.emit(
        ChatProcessContext(
            ChatProcessEvent.FAILED,
            plan.session_id,
            launch_id=plan.launch_id,
            reason="shutdown",
        )
    )
    assert session.calls == []
    assert session.state.chat_lifecycle_error


def test_closed_transport_is_not_notified_twice(session):
    session.state.chat_stream.get_snapshot = lambda _: {
        "sessionClosedReason": "producer closed"
    }
    session.owner.closing("ended")
    assert session.calls == ["stop-mobile"]


def test_second_bridge_finalization_does_not_repeat_effects_or_invent_a_launch(session):
    owner = session.owner
    identity = owner.plan.launch_id
    owner.closing("ended")
    owner.ended("ended")
    calls = list(session.calls)
    owner.closing("bridge shutdown")
    owner.ended("bridge shutdown")
    assert session.calls == calls
    assert owner.plan.launch_id == identity


def test_reentrant_failure_observer_does_not_mark_a_new_launch_as_ended(session):
    owner = session.owner

    def observer(context):
        if context.event is ChatSessionEvent.FAILED:
            session.state.chat_session = {"sessionId": "session-B"}
            owner.begin("session-B")

    session.events.subscribe(observer)
    owner.failed("startup failed")
    assert owner.plan.session_id == "session-B"
    assert not owner._ended


def test_core_cleanup_failure_is_visible_to_observers(session):
    observed = []
    session.events.subscribe(observed.append)
    session.owner.effects.stop_mobile = Mock(side_effect=OSError("mobile failed"))
    with pytest.raises(LifecycleDispatchError):
        session.owner.failed("failed")
    assert isinstance(observed[-1].error, LifecycleDispatchError)


def test_initialization_stream_release_is_idempotent_and_cannot_clear_another_session(
    session,
):
    session.state.chat_session = {"sessionId": "session-B"}
    session.owner.release_stream("session-A")
    session.owner.release_stream("session-A")
    assert session.calls == [("deleted", "session-A")]
    assert session.state.chat_session["sessionId"] == "session-B"
