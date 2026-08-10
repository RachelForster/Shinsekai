from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from application.chat.runtime_process import _handle_chat_command
from application.story import SceneDialogueItem, SceneTurnResult, StorySession
from application.story.coordinator import (
    bound_story_session,
    clear_story_session,
    discard_story_session_storage,
    publish_story_transition,
    story_snapshot_patch,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from config.schema import ApiConfig
from core.story import StoryCompiler, StoryRuntime, parse_story_project
from test.unit.core.story.story_fixtures import campus_mystery_source


class _ChatStream:
    def __init__(self) -> None:
        self.published: list[dict] = []
        self.command = None
        self.snapshot = {
            "dialogText": "Choose",
            "eventSeq": 0,
            "historyEntries": [],
            "inputDraft": "",
            "options": [],
            "sessionId": "session-1",
            "sprites": [],
            "status": "idle",
        }

    def get_snapshot(self, _session_id: str) -> dict:
        return dict(self.snapshot)

    def update_session_snapshot(self, _session_id: str, patch: dict) -> None:
        self.snapshot.update(patch)

    def publish_event(self, _session_id: str, event: dict) -> bool:
        payload = dict(event)
        seq = int(self.snapshot.get("eventSeq") or 0) + 1
        payload["seq"] = seq
        self.snapshot["eventSeq"] = seq
        event_type = str(payload.get("type") or "")
        if event_type == "history.replace":
            self.snapshot["historyEntries"] = list(payload.get("entries") or [])
        elif event_type == "story.state.replace":
            story = dict(payload.get("story") or {})
            self.snapshot["story"] = story
            self.snapshot["options"] = list(story.get("options") or [])
        elif event_type == "options.show":
            self.snapshot["options"] = list(payload.get("options") or [])
        self.published.append(payload)
        return True

    def send_command(self, session_id: str, command: dict) -> bool:
        self.command = (session_id, dict(command))
        return True


class _SceneService:
    def handle_free_text(self, text: str, *, command_id: str, message_id: str):
        return SceneTurnResult(
            command_id=command_id,
            revision=2,
            dialogue=(SceneDialogueItem("ling", f"收到：{text}"),),
            tool_results=(),
        )


def _state(*, enabled: bool, fork: bool = False, flowchart: bool = False) -> SimpleNamespace:
    flags = FeatureFlagConfigManager(
        environ={},
        overrides={FeatureFlag.STORY_SYSTEM: enabled},
    )
    manager = SimpleNamespace(
        config=SimpleNamespace(
            api_config=ApiConfig(),
            system_config=SimpleNamespace(
                react_chat_flowchart_experimental_enabled=flowchart,
                react_chat_fork_experimental_enabled=fork,
                voice_language="ja",
            ),
        ),
        feature_flags=flags,
    )
    return SimpleNamespace(
        chat_session={"sessionId": "session-1"},
        chat_stream=_ChatStream(),
        config_manager=manager,
        story_session=None,
    )


def _story_session(flags: FeatureFlagConfigManager) -> StorySession:
    program = StoryCompiler().compile(parse_story_project(campus_mystery_source()))
    return StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start-1",
    )


def test_structured_story_choice_uses_deterministic_session() -> None:
    state = _state(enabled=True)
    state.story_session = _story_session(state.config_manager.feature_flags)

    snapshot = _handle_chat_command(
        state,
        {
            "cmdId": "choice-1",
            "payload": {
                "choiceId": "prepare-investigation",
                "expectedNodeId": "transfer-day",
                "expectedRevision": 1,
                "kind": "story-choice",
            },
            "type": "submit-option",
        },
    )

    assert snapshot["story"]["currentNodeId"] == "old-school-gate"
    assert snapshot["storyAck"]["commandId"] == "choice-1"
    assert state.chat_stream.snapshot["story"]["revision"] == 2
    assert snapshot["historyEntries"][-1]["role"] == "user"
    assert "和绫约定调查旧校舍" in snapshot["historyEntries"][-1]["text"]
    published_types = [event["type"] for event in state.chat_stream.published]
    assert "history.replace" in published_types
    assert "story.state.replace" in published_types
    assert "options.show" in published_types
    assert snapshot["eventSeq"] >= 1
    assert state.story_session.active_branch.history_entries[-1]["role"] == "user"


def test_structured_story_choice_keeps_legacy_error_when_flag_is_off() -> None:
    state = _state(enabled=False)

    with pytest.raises(ValueError, match="must be a string"):
        _handle_chat_command(
            state,
            {
                "payload": {"kind": "story-choice"},
                "type": "submit-option",
            },
        )


def test_story_snapshot_is_not_projected_onto_another_history(tmp_path) -> None:
    state = _state(enabled=True)
    session = _story_session(state.config_manager.feature_flags)
    session.owner_history_path = str((tmp_path / "one").resolve())
    state.story_session = session
    state.chat_session["historyPath"] = str((tmp_path / "two").resolve())

    assert bound_story_session(state) is None
    assert story_snapshot_patch(state) == {}


def test_clearing_story_session_drops_memory_and_document(tmp_path) -> None:
    history_path = tmp_path / "session"
    history_path.mkdir()
    story_path = history_path / "story-v2.json"
    story_path.write_text("{}", encoding="utf-8")
    state = _state(enabled=True)
    state.chat_session["historyPath"] = str(history_path)
    state.story_session = _story_session(state.config_manager.feature_flags)

    discard_story_session_storage(history_path)
    clear_story_session(state)

    assert state.story_session is None
    assert not story_path.exists()


def test_fork_history_creates_a_matching_story_branch() -> None:
    state = _state(enabled=True, fork=True)
    session = _story_session(state.config_manager.feature_flags)
    state.story_session = session
    _handle_chat_command(
        state,
        {
            "cmdId": "choice-1",
            "payload": {
                "choiceId": "prepare-investigation",
                "expectedNodeId": "transfer-day",
                "expectedRevision": 1,
                "kind": "story-choice",
            },
            "type": "submit-option",
        },
    )

    snapshot = _handle_chat_command(
        state,
        {"payload": {"userIndex": 0}, "type": "fork-history"},
    )

    assert snapshot["status"] == "generating"
    assert "branch-2" in session.branches
    assert session.active_branch_id == "branch-2"
    assert session.active_branch.state.current_node_id == "transfer-day"
    assert state.chat_stream.command[1]["payload"]["branchId"] == "branch-2"


def test_live_story_transition_publishes_approved_actor_resources() -> None:
    state = _state(enabled=True)
    state.story_session = _story_session(state.config_manager.feature_flags)
    state.story_cast_service = SimpleNamespace(
        chat_patch=lambda: {
            "actorContext": {
                "activeCharacterIds": ["ling"],
                "speakerAllowlist": ["ling", "NARR", "SYSTEM"],
            },
            "sprites": [
                {
                    "id": "story:ling",
                    "characterName": "ling",
                    "label": "绫",
                    "path": r"C:\stories\case\characters\ling.png",
                    "scale": 1.0,
                }
            ],
            "storyResources": {"activeCharacterIds": ["ling"]},
        }
    )
    state.chat_stream.media_url = (
        lambda path: f"/api/media?path={path.replace(chr(92), '/')}"
    )

    publish_story_transition(state, state.story_session.chat_snapshot())

    published_types = [event["type"] for event in state.chat_stream.published]
    assert "story.state.replace" in published_types
    assert "sprite.show" in published_types
    sprite_event = next(
        event for event in state.chat_stream.published if event["type"] == "sprite.show"
    )
    assert sprite_event["url"].startswith("/api/media?path=")
    assert state.chat_stream.snapshot["sprites"][0]["path"].startswith("/api/media?path=")
    assert state.chat_stream.snapshot["actorContext"]["activeCharacterIds"] == ["ling"]
    assert story_snapshot_patch(state)["sprites"][0]["path"].startswith("/api/media?path=")


def test_fork_history_skips_story_transition_when_flag_is_off() -> None:
    state = _state(enabled=False, fork=True)
    event_seq = state.chat_stream.snapshot["eventSeq"]

    snapshot = _handle_chat_command(
        state,
        {"payload": {"userIndex": 0}, "type": "fork-history"},
    )

    assert snapshot["status"] == "generating"
    assert state.chat_stream.published == []
    assert state.chat_stream.snapshot["eventSeq"] == event_seq


def test_publish_story_transition_is_noop_when_flag_is_off() -> None:
    state = _state(enabled=False)
    state.story_cast_service = SimpleNamespace(
        chat_patch=lambda: (_ for _ in ()).throw(AssertionError("unguarded chat_patch"))
    )

    publish_story_transition(
        state,
        {"options": [], "story": {"revision": 1}},
    )

    assert state.chat_stream.published == []
    assert state.chat_stream.snapshot["eventSeq"] == 0
    assert "story" not in state.chat_stream.snapshot


def test_free_text_uses_scene_service_only_when_story_flag_is_enabled() -> None:
    state = _state(enabled=True)
    state.story_scene_service = _SceneService()

    snapshot = _handle_chat_command(
        state,
        {
            "cmdId": "turn-1",
            "payload": "你好",
            "type": "send-message",
        },
    )

    assert snapshot["dialogText"] == "收到：你好"
    assert snapshot["characterName"] == "ling"
    assert snapshot["sceneTurn"]["revision"] == 2
