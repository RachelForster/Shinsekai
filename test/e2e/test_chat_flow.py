"""E2E tests for the framework-neutral chat data pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest

from config.config_manager import ConfigManager
from config.schema import (
    Sprite, Character, Background, ApiConfig, SystemConfig, AppConfig,
)
from core.messaging.stream_parser import LlmResponseStreamParser
from application.runtime.context import AppRuntime, set_app_runtime
from sdk.messages import UserInputMessage, LLMDialogMessage, PresentationMessage
from test.mocks import MockLLMAdapter, MockTTSAdapter

pytestmark = pytest.mark.e2e


# =============================================================================
# Data pipeline — config, parser, multi-turn conversation
# =============================================================================

def _make_base_config():
    """Return a valid AppConfig suitable for tests."""
    from test.conftest import make_app_config
    ac = make_app_config()
    ac.api_config.is_streaming = False
    return ac


def _make_runtime(mock_llm, char=None):
    """Build a minimal AppRuntime for pipeline tests."""
    from test.conftest import make_app_config
    ac = make_app_config()
    ac.api_config.is_streaming = False
    if char:
        ac.characters = [char]

    config_mgr = MagicMock(spec=ConfigManager)
    config_mgr.config = ac
    config_mgr.get_character_by_name.return_value = char or ac.characters[0]

    from ai.llm.llm_manager import LLMManager
    llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)
    ui_mgr = MagicMock()
    ui_mgr.chat_history = []

    rt = AppRuntime(
        config=config_mgr,
        ui_update_manager=ui_mgr,
        llm_manager=llm_mgr,
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=Queue(),
        dialog_queue=Queue(),
        presentation_queue=Queue(),
        text_processor=MagicMock(),
        opencc=MagicMock(),
    )
    rt.opencc.convert.side_effect = lambda s: s
    return rt


class TestDataPipeline:
    """Conversation flow through LLM → parser, no Qt needed."""

    def test_three_turn_conversation(self):
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "TestChar", "speech": "Hello!", "sprite": "0"}),
            json.dumps({"character_name": "TestChar", "speech": "Interesting.", "sprite": "1"}),
            json.dumps({"character_name": "TestChar", "speech": "Goodbye!", "sprite": "0"}),
        ])
        rt = _make_runtime(mock_llm)
        set_app_runtime(rt)
        parser = LlmResponseStreamParser()

        for user_text in ["Hi", "Tell me more", "Bye"]:
            response = rt.llm_manager.chat(user_text, stream=False, include_local_time=False)
            assert response
            dialogs = list(parser.feed(response))
            assert len(dialogs) > 0
            assert dialogs[0].name == "TestChar"

        set_app_runtime(None)

    def test_conversation_with_system_messages(self):
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "NARR", "speech": "The adventure begins.", "sprite": "-1"})
            + "\n"
            + json.dumps({"character_name": "TestChar", "speech": "Where am I?", "sprite": "0"}),
        ])
        rt = _make_runtime(mock_llm)
        set_app_runtime(rt)
        parser = LlmResponseStreamParser()
        response = rt.llm_manager.chat("Start", stream=False, include_local_time=False)
        dialogs = list(parser.feed(response))
        names = [d.name for d in dialogs]
        assert "NARR" in names and "TestChar" in names
        set_app_runtime(None)

    def test_malformed_json_resilience(self):
        mock_llm = MockLLMAdapter(responses=[
            "garbage text {broken"
            + json.dumps({"character_name": "TestChar", "speech": "Recovered!", "sprite": "0"})
        ])
        rt = _make_runtime(mock_llm)
        set_app_runtime(rt)
        response = rt.llm_manager.chat("test", stream=False, include_local_time=False)
        dialogs = list(LlmResponseStreamParser().feed(response or ""))
        assert len(dialogs) >= 1
        assert dialogs[-1].name == "TestChar"
        set_app_runtime(None)


# =============================================================================
# Layer 2: Config round-trip (no Qt)
# =============================================================================

class TestConfigRoundTrip:
    def test_load_real_config_files(self):
        ConfigManager._instance = None
        ConfigManager._config = None
        try:
            mgr = ConfigManager()
            assert mgr.config.api_config is not None
            assert mgr.config.system_config is not None
            assert isinstance(mgr.config.characters, list)
        finally:
            ConfigManager._instance = None
            ConfigManager._config = None

    def test_pydantic_validation(self):
        ac = ApiConfig(llm_provider="TestProvider", llm_api_key={"TestProvider": "sk-xxx"}, llm_model={"TestProvider": "m"}, is_streaming=False)
        assert ac.llm_provider == "TestProvider"

    def test_character_crud(self):
        from test.conftest import make_character, make_app_config
        config = make_app_config()
        config.characters.append(make_character(name="NewChar", color="#0f0", sprite_prefix="new"))
        found = any(c.name == "NewChar" for c in config.characters)
        assert found
