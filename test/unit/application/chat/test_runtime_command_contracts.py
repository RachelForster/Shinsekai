"""Exercise validation, forwarding and rollback through the original command API."""

from __future__ import annotations

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
    "command,payload,status",
    [
        ("skip-speech", None, "idle"),
        ("dialog-advance", None, "idle"),
        ("pause-asr", None, "paused"),
        ("resume-asr", None, "listening"),
        ("begin-asr-hold", None, "listening"),
        ("finish-asr-hold", None, "listening"),
        ("cancel-asr-hold", None, "listening"),
        ("reroll", None, "generating"),
        ("chat-input-state", {"focused": True}, "listening"),
        ("flush-input-batch", None, "listening"),
        ("cancel-input-batch", None, "listening"),
        ("revert-history", 0, "idle"),
    ],
)
def test_runtime_commands_forward_once_with_stable_ids_and_status(
    state, command, payload, status
):
    state.chat_stream.snapshot.update(
        status="listening", sessionClosedReason="old", notificationText="old"
    )
    body = {"type": command, "payload": payload, "cmdId": "fixture-id"}
    result = chat._handle_chat_command(state, body)
    assert state.chat_stream.commands == [("session-1", body)]
    assert result["status"] == status
    assert state.chat_stream.snapshot["sessionClosedReason"] == ""
    assert state.chat_stream.snapshot["notificationText"] == ""


@pytest.mark.parametrize(
    "command,payload",
    [
        ("dismiss-plugin-page", None),
        ("dismiss-plugin-page", {"pluginId": "plugin"}),
        ("dismiss-plugin-page", {"pluginId": "x" * 129, "presentationId": "page"}),
        ("update-turn-options", None),
        (
            "update-turn-options",
            {"interruptEnabled": 1, "batchEnabled": True, "batchIdleSeconds": 2},
        ),
        (
            "update-turn-options",
            {"interruptEnabled": True, "batchEnabled": False, "batchIdleSeconds": True},
        ),
        (
            "update-turn-options",
            {"interruptEnabled": True, "batchEnabled": False, "batchIdleSeconds": 0.1},
        ),
        (
            "update-turn-options",
            {
                "interruptEnabled": True,
                "batchEnabled": False,
                "batchIdleSeconds": float("nan"),
            },
        ),
        ("submit-option", {"kind": "unknown"}),
        (
            "submit-option",
            {"kind": "tool-confirmation", "confirmationId": "", "action": "confirm"},
        ),
        (
            "submit-option",
            {
                "kind": "tool-confirmation",
                "confirmationId": "x" * 129,
                "action": "confirm",
            },
        ),
        (
            "submit-option",
            {"kind": "tool-confirmation", "confirmationId": "id", "action": "other"},
        ),
        ("audio-playback-signal", None),
        (
            "audio-playback-signal",
            {"playbackId": "p", "rendererId": "r", "state": "invalid"},
        ),
        ("send-message", ""),
        ("send-message", {"text": "", "attachments": []}),
        ("submit-option", ""),
        ("change-voice-language", ""),
        ("revert-history", "invalid"),
        ("fork-history", {"userIndex": "invalid"}),
        ("switch-branch", ""),
        ("rename-branch", None),
        ("rename-branch", {"label": "new"}),
        ("rename-branch", {"branchId": "main", "label": ""}),
        ("unknown-command", None),
    ],
)
def test_invalid_commands_do_not_reach_transport_or_save_config(
    state, command, payload
):
    state.config_manager.config.system_config.react_chat_fork_experimental_enabled = (
        True
    )
    state.config_manager.config.system_config.react_chat_flowchart_experimental_enabled = (
        True
    )
    with pytest.raises(ValueError):
        chat._handle_chat_command(state, {"type": command, "payload": payload})
    assert state.chat_stream.commands == []
    state.config_manager.save_api_config.assert_not_called()


@pytest.mark.parametrize(
    "command,payload",
    [
        ("fork-history", 0),
        ("switch-branch", "main"),
        ("rename-branch", {"branchId": "main", "label": "new"}),
    ],
)
def test_branch_experiments_are_enforced_before_transport(state, command, payload):
    with pytest.raises(PermissionError):
        chat._handle_chat_command(state, {"type": command, "payload": payload})
    assert state.chat_stream.commands == []


@pytest.mark.parametrize("mode", ["missing", "rejected"])
def test_forwarding_failure_does_not_patch_session_or_snapshot(state, mode):
    stream = state.chat_stream
    if mode == "missing":
        state.chat_stream = None
    else:
        stream.accept = False
    with pytest.raises(RuntimeError):
        chat._handle_chat_command(
            state, {"type": "change-voice-language", "payload": "en"}
        )
    assert "voiceLanguage" not in state.chat_session
    assert stream.updates == []


def test_turn_option_update_rolls_back_if_forwarding_fails(state):
    original = state.config_manager.config.api_config
    state.chat_stream.accept = False
    with pytest.raises(RuntimeError):
        chat._handle_chat_command(
            state,
            {
                "type": "update-turn-options",
                "payload": {
                    "interruptEnabled": False,
                    "batchEnabled": True,
                    "batchIdleSeconds": 2,
                },
            },
        )
    assert state.config_manager.config.api_config is original
    assert state.config_manager.save_api_config.call_count == 2


def test_turn_option_update_keeps_original_error_if_rollback_save_fails(state):
    original = state.config_manager.config.api_config
    state.config_manager.save_api_config.side_effect = [
        OSError("first save"),
        OSError("rollback"),
    ]
    with pytest.raises(OSError, match="first save"):
        chat._handle_chat_command(
            state,
            {
                "type": "update-turn-options",
                "payload": {
                    "interruptEnabled": False,
                    "batchEnabled": True,
                    "batchIdleSeconds": 2,
                },
            },
        )
    assert state.config_manager.config.api_config is original
    assert state.chat_stream.commands == []


@pytest.mark.parametrize("batch", [False, True])
def test_message_normalization_respects_batch_status_and_user_display_name(
    state, batch
):
    state.config_manager.config.api_config.is_batch_input_enabled = batch
    state.chat_stream.snapshot["status"] = "listening"
    body = {
        "type": "send-message",
        "payload": {"text": " hello ", "attachments": [], "ignored": True},
    }
    result = chat._handle_chat_command(state, body)
    forwarded = state.chat_stream.commands[0][1]
    assert forwarded["payload"] == {"text": "hello", "attachments": []}
    assert len(forwarded["cmdId"]) == 32
    assert result["status"] == ("listening" if batch else "generating")
    assert result["userDisplayName"] == "Player"
    assert result["inputDraft"] == ""


def test_tool_confirmation_and_audio_signal_are_normalized(state):
    chat._handle_chat_command(
        state,
        {
            "type": "submit-option",
            "payload": {
                "kind": "tool-confirmation",
                "action": " CONFIRM ",
                "confirmationId": " id ",
                "extra": "discard",
            },
        },
    )
    assert state.chat_stream.commands[-1][1]["payload"] == {
        "kind": "tool-confirmation",
        "action": "confirm",
        "confirmationId": "id",
    }
    chat._handle_chat_command(
        state,
        {
            "type": "audio-playback-signal",
            "payload": {
                "playbackId": " p ",
                "rendererId": "r" * 200,
                "state": "finished",
                "error": "e" * 700,
            },
        },
    )
    payload = state.chat_stream.commands[-1][1]["payload"]
    assert payload["playbackId"] == "p"
    assert len(payload["rendererId"]) == 128
    assert len(payload["error"]) == 500


def test_plugin_page_dismissal_requires_live_event_delivery(state):
    body = {
        "type": "dismiss-plugin-page",
        "payload": {"pluginId": "plugin", "presentationId": "page", "extra": 1},
    }
    chat._handle_chat_command(state, body)
    assert state.chat_stream.events == [
        (
            "session-1",
            {
                "type": "plugin.page.dismiss",
                "pluginId": "plugin",
                "presentationId": "page",
            },
        )
    ]
    state.chat_stream.accept = False
    with pytest.raises(RuntimeError):
        chat._handle_chat_command(state, body)
    state.chat_stream = None
    with pytest.raises(RuntimeError):
        chat._handle_chat_command(state, body)


def test_copy_history_prefers_visible_entries_then_uses_persisted_messages(state):
    state.chat_stream.snapshot["historyEntries"] = [
        {"role": "user", "text": "Player: visible"}
    ]
    result = chat._handle_chat_command(state, {"type": "copy-history"})
    assert "visible" in result["clipboardText"]
    state.chat_stream.snapshot["historyEntries"] = []
    write_messages(state, [{"role": "user", "content": "persisted"}])
    assert (
        "persisted"
        in chat._handle_chat_command(state, {"type": "copy-history"})["clipboardText"]
    )


def test_clear_history_removes_owned_files_but_preserves_neighbour_files(state):
    state.chat_stream = None
    state.chat_session["historyPath"] = str(
        Path(state.project_root_dir) / "legacy.json"
    )
    Path(state.chat_session["historyPath"]).write_text("[]", encoding="utf-8")
    active = write_messages(state, [{"role": "user", "content": "old"}])
    neighbour = active.parent / "keep.txt"
    neighbour.write_text("other owner", encoding="utf-8")
    result = chat._handle_chat_command(state, {"type": "clear-history"})
    assert not active.exists()
    assert neighbour.read_text(encoding="utf-8") == "other owner"
    assert result["historyEntries"] == []


def test_story_choice_is_executed_with_revision_and_published_ack(state, monkeypatch):
    ack = SimpleNamespace(
        to_payload=lambda: {"accepted": True}, presentation_events=[{"type": "story"}]
    )
    story = SimpleNamespace(
        chat_snapshot=lambda: {"options": [{"id": "choice", "label": "Continue"}]},
        execute=MagicMock(return_value=ack),
    )
    monkeypatch.setattr(chat, "bound_story_session", lambda _: story)
    publish = MagicMock()
    monkeypatch.setattr(chat, "publish_story_transition", publish)
    result = chat._handle_chat_command(
        state,
        {
            "type": "submit-option",
            "cmdId": "stable",
            "payload": {
                "kind": "story-choice",
                "choiceId": "choice",
                "expectedNodeId": "node",
                "expectedRevision": 3,
            },
        },
    )
    command = story.execute.call_args.args[0]
    assert (
        command.command_id,
        command.choice_id,
        command.expected_node_id,
        command.expected_revision,
    ) == ("stable", "choice", "node", 3)
    assert result["storyAck"] == {"accepted": True}
    assert publish.call_args.kwargs["presentation_events"] == [{"type": "story"}]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "story-choice",
            "choiceId": "c",
            "expectedNodeId": "n",
            "expectedRevision": "bad",
        },
        {
            "kind": "story-choice",
            "choiceId": "",
            "expectedNodeId": "n",
            "expectedRevision": 1,
        },
    ],
)
def test_story_choice_validation_precedes_mutation(state, monkeypatch, payload):
    story = SimpleNamespace(execute=MagicMock())
    monkeypatch.setattr(chat, "bound_story_session", lambda _: story)
    with pytest.raises(ValueError):
        chat._handle_chat_command(state, {"type": "submit-option", "payload": payload})
    story.execute.assert_not_called()
