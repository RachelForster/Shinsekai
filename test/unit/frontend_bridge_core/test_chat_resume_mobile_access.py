from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend_bridge_core import chat_session


@pytest.mark.parametrize("source", ["saved-conversation", "last-launch-cache"])
@pytest.mark.parametrize("stored", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
def test_resume_mobile_preference_overrides_both_persisted_sources(
    monkeypatch, source, stored, override
):
    session = {
        "enableMobileAccess": stored,
        "historyPath": "previous-chat.json",
        "selectedCharacters": [],
        "scenario": "scene",
        "system": "system",
    }
    saved_launch = {"enableMobileAccess": stored, "historyPath": "previous-chat.json"}
    state = SimpleNamespace(
        chat_session={},
        chat_stream=None,
        history_dir="unused",
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                system_config=SimpleNamespace(live_room_id="", voice_language="ja")
            )
        ),
    )
    mobile_access = Mock()
    launch = Mock(return_value={"status": "idle"})
    monkeypatch.setattr(chat_session, "_chat_runtime_closing", lambda _state: False)
    monkeypatch.setattr(
        chat_session, "_load_template_session_payload", lambda _state: session
    )
    monkeypatch.setattr(
        chat_session, "resolve_chat_history_path", lambda *_args: Path("previous-chat.json")
    )
    monkeypatch.setattr(
        chat_session,
        "saved_conversation_launch",
        lambda *_args: saved_launch if source == "saved-conversation" else None,
    )
    monkeypatch.setattr(chat_session, "launch_chat", launch)
    monkeypatch.setattr(chat_session, "configure_mobile_access", mobile_access)
    monkeypatch.setattr(
        chat_session, "_resume_template_parts", lambda _state: ("scene", "system", "resume")
    )
    monkeypatch.setattr(
        chat_session, "_resolve_template_character_names", lambda *_args: []
    )
    monkeypatch.setattr(
        chat_session, "initial_sprite_path_for_characters", lambda *_args: ""
    )
    monkeypatch.setattr(chat_session, "release_unbound_story_session", Mock())
    monkeypatch.setattr(chat_session, "_chat_process_running", lambda: False)
    monkeypatch.setattr(chat_session, "_chat_runtime_mode", lambda _state: "native")
    monkeypatch.setattr(
        chat_session, "_launch_runtime_chat", Mock(return_value="Chat ready")
    )
    monkeypatch.setattr(
        chat_session, "_chat_snapshot", lambda *_args, **_kwargs: {"status": "idle"}
    )
    monkeypatch.setattr(
        chat_session, "_chat_stream_initial_snapshot", lambda snapshot: snapshot
    )
    stream_info = {"sessionId": "init-session"}

    result = chat_session.resume_last_chat(
        state, init_stream_info=stream_info, enable_mobile_access=override
    )

    expected = stored if override is None else override
    assert result["status"] == "idle"
    if source == "saved-conversation":
        launch.assert_called_once_with(
            state,
            {**saved_launch, "enableMobileAccess": expected},
            init_stream_info=stream_info,
        )
    else:
        launch.assert_not_called()
        assert mobile_access.call_args.kwargs["enabled"] is expected
    # Applying a device preference must not mutate the loaded configuration object.
    assert session["enableMobileAccess"] is stored
    assert saved_launch["enableMobileAccess"] is stored
