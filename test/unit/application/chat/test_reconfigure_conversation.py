import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat.conversation_library import (
    list_conversations,
    remember_conversation,
)
from application.chat.reconfigure_conversation import (
    prepare_conversation_edit,
    restart_edited_conversation,
)


@pytest.fixture
def edit(tmp_path, monkeypatch):
    path = tmp_path / "history" / "one"
    path.mkdir(parents=True)
    (path / "active.json").write_text(
        json.dumps(
            [
                {"role": "system", "content": "Old rules"},
                {"role": "user", "content": "Hello"},
            ]
        )
    )
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(path.parent),
        template_dir_path=str(tmp_path / "templates"),
        chat_session={"historyPath": str(path)},
        config_manager=SimpleNamespace(
            get_character_by_name=lambda name: name if name == "Alice" else None
        ),
    )
    payload = {"characters": ["Alice"], "system": "New rules", "scenario": "New scene"}
    remember_conversation(state, path, payload)
    record = list_conversations(state)[0]
    stop = Mock()
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation._chat_process_running", lambda: True
    )
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation._chat_snapshot",
        lambda _: {"status": "idle"},
    )
    monkeypatch.setattr("application.chat.reconfigure_conversation.stop_chat", stop)
    return state, record, payload, stop, path


def test_edit_cannot_reset_or_redirect_history(edit):
    state, record, payload, stop, path = edit
    result = prepare_conversation_edit(
        state, record["id"], {**payload, "historyPath": "other", "resetHistory": True}
    )
    assert result["historyPath"] == path.as_posix()
    assert result["resetHistory"] is False
    assert result["useCurrentTemplateForHistory"] is True
    stop.assert_not_called()
    original = (path / "active.json").read_bytes()
    restart_edited_conversation(state, record["id"], result)
    stop.assert_called_once_with(state)
    assert (path / "active.json").read_bytes() == original


def test_edit_retains_launch_options_not_exposed_by_editor(edit):
    state, record, payload, _, path = edit
    remember_conversation(
        state,
        path,
        {**payload, "workflowPath": "custom.yaml", "userDisplayName": "Reader"},
    )
    result = prepare_conversation_edit(state, record["id"], payload)
    assert result["workflowPath"] == "custom.yaml"
    assert result["userDisplayName"] == "Reader"


@pytest.mark.parametrize(
    "snapshot",
    [
        {"status": "generating"},
        {"status": "speaking"},
        {"status": "listening"},
        {"status": "idle", "turnState": {"pendingCount": 1}},
        {"status": "idle", "turnState": {"scheduled": True}},
    ],
)
def test_busy_reply_is_not_interrupted(edit, monkeypatch, snapshot):
    state, record, payload, stop, _ = edit
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation._chat_snapshot", lambda _: snapshot
    )
    with pytest.raises(RuntimeError, match="Wait"):
        restart_edited_conversation(state, record["id"], payload)
    stop.assert_not_called()


def test_other_chat_is_not_stopped(edit):
    state, record, payload, stop, path = edit
    state.chat_session["historyPath"] = str(path.parent / "other")
    with pytest.raises(RuntimeError, match="Another chat"):
        restart_edited_conversation(state, record["id"], payload)
    stop.assert_not_called()


def test_invalid_character_does_not_stop_runtime(edit):
    state, record, payload, stop, _ = edit
    with pytest.raises(ValueError, match="character"):
        restart_edited_conversation(
            state, record["id"], {**payload, "characters": ["Missing"]}
        )
    stop.assert_not_called()


def test_story_edit_validates_then_recovers_original_progress(edit, monkeypatch):
    state, record, payload, stop, path = edit
    (path / "story-v2.json").write_text('{"scene": "chapter-two"}')
    (path / "story-prompt-binding.json").write_text(
        '{"storyPath": "original.story.json"}'
    )
    validate = Mock()
    recover = Mock()
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation.prepare_story_launch", validate
    )
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation.start_or_recover_story_session",
        recover,
    )
    restart_edited_conversation(state, record["id"], payload)
    validate.assert_called_once_with(state, "original.story.json", path.as_posix())
    recover.assert_called_once()
    assert recover.call_args.args == (state, "original.story.json")
    assert (path / "story-v2.json").read_text() == '{"scene": "chapter-two"}'
    stop.assert_called_once()


def test_invalid_story_is_rejected_before_stop(edit, monkeypatch):
    state, record, payload, stop, path = edit
    (path / "story-v2.json").write_text("{}")
    (path / "story-prompt-binding.json").write_text(
        '{"storyPath": "changed.story.json"}'
    )
    monkeypatch.setattr(
        "application.chat.reconfigure_conversation.prepare_story_launch",
        Mock(side_effect=ValueError("changed story")),
    )
    with pytest.raises(ValueError, match="changed story"):
        restart_edited_conversation(state, record["id"], payload)
    stop.assert_not_called()
