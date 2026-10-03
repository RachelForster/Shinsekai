from types import SimpleNamespace
import threading

import pytest

from application.chat import stop_chat as stop_chat_action
from frontend_bridge_core import chat_session


def test_stop_chat_composes_runtime_cleanup_with_fake_state(monkeypatch) -> None:
    calls = []
    state = SimpleNamespace(chat_session={"sessionId": ""}, chat_stream=None)
    monkeypatch.setattr(
        stop_chat_action.runtime_process,
        "_set_chat_runtime_closing",
        lambda _state, closing: calls.append(("closing", closing)),
    )
    monkeypatch.setattr(
        stop_chat_action.runtime_process,
        "shutdown_active_chat_process",
        lambda **options: calls.append(("shutdown", options)),
    )
    monkeypatch.setattr(
        stop_chat_action.runtime_process,
        "_chat_snapshot",
        lambda *_args: {"status": "idle"},
    )
    monkeypatch.setattr(
        stop_chat_action,
        "stop_mobile_access",
        lambda _state: calls.append(("mobile", "stopped")),
    )
    monkeypatch.setattr(
        stop_chat_action,
        "clear_story_session",
        lambda _state: calls.append(("story", "cleared")),
    )

    result = stop_chat_action.stop_chat(state, wait_timeout=2.5)

    assert result == {"status": "idle"}
    assert calls == [
        ("closing", True),
        (
            "shutdown",
            {"wait_timeout": 2.5, "wait_before_signal": 0.0},
        ),
        ("mobile", "stopped"),
        ("closing", False),
        ("story", "cleared"),
    ]


class _ObservedLifecycleLock:
    def __init__(self):
        self.lock = threading.RLock()
        self.attempted = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "other-client":
            self.attempted.set()
        self.lock.acquire()
        return self

    def __exit__(self, *_args):
        self.lock.release()


def _patch_stop_dependencies(monkeypatch):
    calls = []
    monkeypatch.setattr(stop_chat_action.runtime_process, "_set_chat_runtime_closing", lambda _state, closing: calls.append(("closing", closing)))
    monkeypatch.setattr(stop_chat_action.runtime_process, "shutdown_active_chat_process", lambda **_kwargs: calls.append("shutdown"))
    monkeypatch.setattr(stop_chat_action.runtime_process, "_chat_snapshot", lambda *_args: {"status": "idle"})
    monkeypatch.setattr(stop_chat_action, "stop_mobile_access", lambda _state: calls.append("mobile"))
    monkeypatch.setattr(stop_chat_action, "clear_story_session", lambda _state: calls.append("story"))
    return calls


def test_close_checks_identity_after_acquiring_the_lifecycle_lock(monkeypatch):
    calls = _patch_stop_dependencies(monkeypatch)
    lock = _ObservedLifecycleLock()
    state = SimpleNamespace(chat_session={"sessionId": "A"}, chat_stream=None, chat_lifecycle_lock=lock)
    errors = []

    def close_old_session():
        try:
            stop_chat_action.stop_chat(state, expected_session_id="A")
        except Exception as exc:
            errors.append(exc)

    with lock:
        thread = threading.Thread(target=close_old_session, name="other-client")
        thread.start()
        assert lock.attempted.wait(2)
        # Another client finishes A and installs B before this POST gets the lock.
        state.chat_session = {"sessionId": "B"}
    thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], stop_chat_action.ChatSessionChanged)
    assert calls == []
    assert state.chat_session == {"sessionId": "B"}


@pytest.mark.parametrize("start_name", ["launch_chat", "resume_last_chat"])
def test_close_holds_lifecycle_lock_until_cleanup_before_another_launch(monkeypatch, start_name):
    calls = _patch_stop_dependencies(monkeypatch)
    lock = _ObservedLifecycleLock()
    state = SimpleNamespace(chat_session={"sessionId": "A"}, chat_stream=None, chat_lifecycle_lock=lock)
    stopping = threading.Event()
    release = threading.Event()
    launched = threading.Event()
    errors = []

    def shutdown(**_kwargs):
        stopping.set()
        assert release.wait(2)

    def launch(_state, *_args, **_kwargs):
        # Session cleanup must have completed before launch can replace it.
        assert state.chat_session["sessionId"] == ""
        assert "mobile" in calls and "story" in calls
        state.chat_session = {"sessionId": "B"}
        launched.set()
        return {"sessionId": "B"}

    def run(action):
        try:
            action()
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(stop_chat_action.runtime_process, "shutdown_active_chat_process", shutdown)
    monkeypatch.setattr(chat_session, "_launch_chat_locked" if start_name == "launch_chat" else "_resume_last_chat_locked", launch)
    close_thread = threading.Thread(target=lambda: run(lambda: stop_chat_action.stop_chat(state, expected_session_id="A")))
    start = getattr(chat_session, start_name)
    start_thread = threading.Thread(target=lambda: run(lambda: start(state, {}) if start_name == "launch_chat" else start(state)), name="other-client")
    close_thread.start()
    try:
        assert stopping.wait(2)
        start_thread.start()
        assert lock.attempted.wait(2)
        assert not launched.is_set()
        assert state.chat_session["sessionId"] == "A"
    finally:
        release.set()
        close_thread.join(2)
        if start_thread.ident is not None:
            start_thread.join(2)
    assert errors == []
    assert not close_thread.is_alive() and not start_thread.is_alive()
    assert launched.is_set()
    assert state.chat_session == {"sessionId": "B"}


@pytest.mark.parametrize("expected", ["A", None])
def test_matching_or_legacy_close_cleans_up_the_active_session(monkeypatch, expected):
    calls = _patch_stop_dependencies(monkeypatch)
    state = SimpleNamespace(chat_session={"sessionId": "A"}, chat_stream=None)
    assert stop_chat_action.stop_chat(state, expected_session_id=expected) == {"status": "idle"}
    assert "shutdown" in calls and "mobile" in calls and "story" in calls
    assert state.chat_session["sessionId"] == ""
