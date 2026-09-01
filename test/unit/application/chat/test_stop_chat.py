from types import SimpleNamespace

from application.chat import stop_chat as stop_chat_action


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
