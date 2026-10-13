"""History, snapshots and story projection contracts of the original facade."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.chat import runtime_process as chat
from test.unit.application.chat.runtime_process_fakes import make_state, write_messages


@pytest.fixture
def state(tmp_path, monkeypatch):
    return make_state(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"createdAt": 1.25}, 1250),
        ({"created_at": 10_000_000_000}, 10_000_000_000),
        ({"timestamp": "2"}, 2000),
        ({"ts": "10000000000"}, 10_000_000_000),
        ({"createdAt": "1970-01-01T00:00:01Z"}, 1000),
        ({"createdAt": "", "ts": 3}, 3000),
        ({"createdAt": None, "ts": 4}, 4000),
        ({"createdAt": "invalid"}, None),
        ({"createdAt": {}}, None),
        ({}, None),
    ],
)
def test_history_timestamp_formats(value, expected):
    assert chat._message_created_at_ms(value) == expected


@pytest.mark.parametrize(
    "text,role",
    [
        ("你：hello", "user"),
        ("选项：continue", "options"),
        ("narr：stage", "system"),
        ("Alice：hello", "assistant"),
    ],
)
def test_history_role_aliases(text, role):
    assert chat._history_entry_role_from_text(text) == role


def test_history_projection_skips_transport_messages_and_keeps_user_indexes():
    messages = [
        None,
        {"role": "user", "content": ""},
        {"role": "system", "content": "prompt"},
        {
            "role": "user",
            "content": "raw",
            "display_content": "visible",
            "createdAt": 2,
        },
        {"role": "tool", "content": "result"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "dialog": [
                        {"character_name": "Alice", "speech": "reply"},
                        {"character_name": "Alice", "speech": ""},
                    ]
                }
            ),
        },
        {"role": "user", "content": "second"},
    ]
    entries = chat._serialize_history_entries_from_messages(messages, "<b>Player</b>")
    assert entries == [
        {
            "id": "history-0",
            "revertUserIndex": 0,
            "role": "user",
            "text": "Player: visible",
            "createdAt": 2000,
        },
        {"id": "history-1", "role": "assistant", "text": "Alice: reply"},
        {
            "id": "history-2",
            "revertUserIndex": 1,
            "role": "user",
            "text": "Player: second",
        },
    ]
    assert chat._serialize_history_entries_from_messages({}) == []
    assert chat._history_entries_from_snapshot(None) == []
    assert chat._history_entries_from_snapshot(
        {"historyEntries": [None, {"text": "valid"}]}
    ) == [{"text": "valid"}]


def test_history_falls_back_to_disk_only_when_stream_has_no_history(state):
    write_messages(state, [{"role": "user", "content": "disk"}])
    assert chat._chat_history(state) == []
    state.chat_stream.snapshot.pop("historyEntries")
    assert chat._chat_history(state)[0]["text"] == "你: disk"
    state.chat_stream = None
    state.chat_session["historyPath"] = ""
    assert chat._chat_history_entries(state) == []


def test_unc_history_is_not_accessed(state, monkeypatch):
    state.chat_stream = None
    state.chat_session["historyPath"] = r"\\server\share\history.json"
    reader = MagicMock(side_effect=AssertionError("must not access network history"))
    monkeypatch.setattr(chat, "_resolve_history_file", reader)
    assert chat._chat_history_entries(state) == []
    chat._persist_story_choice_messages(state, "choice", "Player")
    chat._persist_scene_turn_messages(state, "message", "Player", [])
    reader.assert_not_called()


def test_stream_snapshot_precedence_renderer_and_mobile_transport(state, monkeypatch):
    stream = state.chat_stream
    stream.snapshot.update(
        voiceLanguage="",
        conversationTree={"private": True},
        dialogHtml="old",
        userDisplayName="<b>Hero</b>",
    )
    monkeypatch.setattr(
        chat, "story_snapshot_patch", lambda _: {"status": "story", "storyRevision": 8}
    )
    monkeypatch.setattr(
        chat,
        "get_mobile_access_info",
        lambda _: SimpleNamespace(
            to_payload=lambda: {"enabled": True},
            websocket_url="ws://mobile/chat",
        ),
    )
    result = chat._chat_snapshot(
        state, "generating", "new", extra={"status": "extra"}, renderer_id="renderer"
    )
    assert result["status"] == "story"
    assert result["dialogText"] == "new"
    assert "dialogHtml" not in result
    assert "conversationTree" not in result
    assert result["voiceLanguage"] == "ja"
    assert result["userDisplayName"] == "Hero"
    assert state.chat_session["userDisplayName"] == "Hero"
    assert result["wsUrl"] == "ws://mobile/chat"
    assert result["mobileAccess"] == {"enabled": True}
    assert ("session-1", "renderer") in stream.reads
    assert stream.snapshot["dialogHtml"] == "old"


def test_fallback_snapshot_keeps_extra_override_and_initial_snapshot_clears_sprites(
    state, monkeypatch
):
    state.chat_stream = None
    state.chat_session.update(voiceLanguage=" EN ", userDisplayName="Player")
    monkeypatch.setattr(chat, "story_snapshot_patch", lambda _: {"status": "story"})
    result = chat._chat_snapshot(
        state, extra={"status": "extra", "sprites": [{"id": "previous"}]}
    )
    assert result["status"] == "extra"
    assert result["voiceLanguage"] == "en"
    assert result["numericInfo"] is None
    initial = chat._chat_stream_initial_snapshot(result)
    assert initial["sprites"] == []
    assert result["sprites"] == [{"id": "previous"}]


def test_runtime_option_defaults_and_empty_voice_language(state):
    state.config_manager.config.system_config.voice_language = ""
    assert chat._chat_voice_language(state) == "ja"
    assert chat._chat_runtime_mode(state) == "react"
    assert chat._chat_turn_options(SimpleNamespace()) == {
        "interruptEnabled": True,
        "batchEnabled": False,
        "batchIdleSeconds": 5.0,
    }
    assert chat._chat_experimental_features(SimpleNamespace()) == {
        "conversationTree": False,
        "forkHistory": False,
    }
    state.chat_stream.snapshot = None
    assert chat._chat_user_display_name_from_snapshot(state) == "你"


def test_history_download_capability_replaces_previous_and_expires_monotonically(
    state, monkeypatch
):
    path = write_messages(state, [])
    now = [5.0]
    monkeypatch.setattr(chat, "time", SimpleNamespace(monotonic=lambda: now[0]))
    first = chat._issue_chat_history_download_capability(state, path)
    second = chat._issue_chat_history_download_capability(state, path)
    with pytest.raises(PermissionError, match="invalid"):
        chat._chat_history_download_file(state, first)
    now[0] = 65.0
    assert chat._chat_history_download_file(state, second) == path
    now[0] += 0.001
    with pytest.raises(PermissionError, match="expired"):
        chat._chat_history_download_file(state, second)
    assert state.history_download_capabilities == {}


@pytest.mark.parametrize("token", ["", "\n", "bad\x00token"])
def test_history_download_rejects_absent_or_control_character_capabilities(
    state, token
):
    with pytest.raises((PermissionError, ValueError)):
        chat._chat_history_download_file(state, token)


def test_history_download_checks_file_after_capability_was_issued(state):
    path = write_messages(state, [])
    assert chat._current_chat_history_download_file(state) == path
    token = chat._issue_chat_history_download_capability(state, path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        chat._chat_history_download_file(state, token)
    with pytest.raises(FileNotFoundError):
        chat._current_chat_history_download_file(state)
    state.chat_session["historyPath"] = ""
    with pytest.raises(FileNotFoundError):
        chat._current_chat_history_download_file(state)


def _with_branch(state):
    write_messages(state, [])
    chat.save_branch_state(
        Path(state.chat_session["historyPath"]),
        {
            "active": "main",
            "counter": 9,
            "branches": {
                "main": {
                    "id": "main",
                    "label": "Main",
                    "messages": [],
                    "history": [],
                }
            },
        },
    )


def test_story_choice_updates_messages_and_active_branch(state):
    _with_branch(state)
    entries = chat._record_story_choice_history(state, "continue")
    assert entries[-1]["text"] == "Player: continue"
    active = chat.chat_history_active_path(Path(state.chat_session["historyPath"]))
    assert chat._read_history_file(active) == [{"role": "user", "content": "continue"}]
    branch = chat.load_branch_state(Path(state.chat_session["historyPath"]))[
        "branches"
    ]["main"]
    assert branch["history"] == ["<b>Player</b>：continue"]
    assert branch["messages"] == [{"role": "user", "content": "continue"}]


def test_scene_turn_records_once_and_escapes_persisted_html(state):
    _with_branch(state)
    dialogue = [
        SimpleNamespace(character_id="narr", text="<scene>"),
        SimpleNamespace(character_id="Alice", text="reply"),
    ]
    entries = chat._record_scene_turn_history(state, "<request>", dialogue)
    assert [entry["role"] for entry in entries] == ["user", "system", "assistant"]
    state.chat_stream.snapshot["historyEntries"] = entries
    assert chat._record_scene_turn_history(state, "<request>", dialogue) == entries
    branch = chat.load_branch_state(Path(state.chat_session["historyPath"]))[
        "branches"
    ]["main"]
    assert len(branch["messages"]) == 3
    assert "&lt;request&gt;" in branch["history"][0]
    assert "&lt;scene&gt;" in branch["history"][1]
    events = chat._scene_dialog_events(dialogue)
    assert events[0]["isSystem"] is True
    assert events[1]["isSystem"] is False
    assert events[0]["fullHtml"] == "<p>&lt;scene&gt;</p>"


@pytest.mark.parametrize(
    "entries,text,dialogue,expected",
    [
        ([], "request", [], False),
        ([{"role": "assistant"}], "request", [], False),
        ([{"role": "user", "text": "other"}], "request", [], False),
        ([{"role": "user", "text": "request"}], "request", [], True),
        (
            [{"role": "user", "text": "request"}, {"text": "reply"}],
            "request",
            [SimpleNamespace(text="reply")],
            True,
        ),
        (
            [{"role": "user", "text": "request"}, {"text": "other"}],
            "request",
            [SimpleNamespace(text="reply")],
            False,
        ),
    ],
)
def test_scene_history_deduplication(entries, text, dialogue, expected):
    assert chat._scene_turn_already_recorded(entries, text, dialogue) is expected


def test_story_branch_alignment_and_command_translation(state, monkeypatch):
    _with_branch(state)
    story = SimpleNamespace(
        branches={"main": {}, "branch-12": {}, "branch-invalid": {}},
        checkpoint_generation_before_user_index=MagicMock(return_value=7),
        fork=MagicMock(),
        switch_branch=MagicMock(),
        restore_generation=MagicMock(),
    )
    monkeypatch.setattr(chat, "bound_story_session", lambda _: story)
    body = {"payload": 2}
    chat._sync_story_session_branch_command(state, "fork-history", body)
    assert body["payload"] == {"userIndex": 2, "branchId": "branch-13"}
    story.fork.assert_called_once_with("branch-13", generation=7)
    chat._sync_story_session_branch_command(state, "switch-branch", {"payload": "main"})
    chat._sync_story_session_branch_command(
        state, "switch-branch", {"payload": "absent"}
    )
    story.switch_branch.assert_called_once_with("main")
    chat._sync_story_session_branch_command(state, "revert-history", {"payload": 1})
    story.restore_generation.assert_called_once_with(7)


def test_story_choice_labels_skip_bad_options_and_fall_back_to_id():
    story = SimpleNamespace(
        chat_snapshot=lambda: {
            "options": [None, {"id": "other"}, {"id": "choice", "label": " Continue "}]
        }
    )
    assert chat._story_choice_label(story, "choice") == "Continue"
    assert chat._story_choice_label(story, "missing") == "missing"


def test_theme_payload_reads_dict_and_ignores_other_json_values(
    state, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "theme.json"
    state.config_manager.config.system_config.chat_ui_theme_path = "theme.json"
    state.config_manager.config.system_config.theme_color = "#112233"
    assert chat._chat_theme_payload(state)["path"] == ""
    path.write_text('{"frame":"custom"}', encoding="utf-8")
    assert chat._chat_theme_payload(state) == {
        "path": path.as_posix(),
        "raw": {"frame": "custom"},
        "themeColor": "#112233",
    }
    path.write_text("[]", encoding="utf-8")
    assert chat._chat_theme_payload(state)["raw"] == {}


def test_plain_history_and_missing_files(state, tmp_path):
    raw = [{"role": "user", "content": "hello"}]
    assert "hello" in chat._plain_history_text(raw)
    assert "hello" in chat._plain_history_text_from_entries(
        [{"role": "user", "text": "Player: hello"}]
    )
    assert chat._read_history_file(tmp_path / "absent.json") == []
