from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat.runtime_process import _handle_chat_command
from application.story import StorySession
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from config.schema import ApiConfig
from core.story import StoryCompiler, StoryRuntime, parse_story_project
from test.unit.core.story.story_fixtures import campus_mystery_source


class _ChatStream:
    def __init__(self) -> None:
        self.snapshot = {
            "dialogText": "Choose",
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


def _state(*, enabled: bool) -> SimpleNamespace:
    flags = FeatureFlagConfigManager(
        environ={},
        overrides={FeatureFlag.STORY_SYSTEM: enabled},
    )
    manager = SimpleNamespace(
        config=SimpleNamespace(
            api_config=ApiConfig(),
            system_config=SimpleNamespace(
                react_chat_flowchart_experimental_enabled=False,
                react_chat_fork_experimental_enabled=False,
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
