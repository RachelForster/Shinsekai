"""E2E tests: full chat flow from user input through worker pipeline to UI updates.

Layered from low (no Qt) to high (full Qt widget tree with qtbot).
"""

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
from core.runtime.app_runtime import AppRuntime, set_app_runtime
from sdk.messages import UserInputMessage, LLMDialogMessage, TTSOutputMessage
from test.mocks import MockLLMAdapter, MockTTSAdapter

pytestmark = pytest.mark.e2e


# =============================================================================
# Layer 1: Data pipeline (no Qt) — config, parser, multi-turn conversation
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

    from llm.llm_manager import LLMManager
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
        tts_queue=Queue(),
        audio_path_queue=Queue(),
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


# =============================================================================
# Layer 3: UIUpdateManager signals → ChatUIWindow (Qt with qtbot)
# =============================================================================

@pytest.mark.ui
class TestUISignalFlow:
    """Signal wiring between UIUpdateManager and ChatUIWindow.

    These tests create real QWidgets and need a display or Xvfb.
    Run with:  pytest test/e2e/ -m e2e --run-ui
    """

    def test_create_chat_ui_window(self, qtbot):
        """ChatUIWindow can be constructed without crashing."""
        from PySide6.QtWidgets import QApplication
        from ui.chat_ui.chat_ui import ChatUIWindow
        from test.mocks import MockLLMAdapter

        mock_llm = MockLLMAdapter(responses=[""])
        from llm.llm_manager import LLMManager
        llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)

        window = ChatUIWindow(
            image_queue=Queue(),
            emotion_queue=Queue(),
            llm_manager=llm_mgr,
            sprite_mode=False,
            background_mode=False,
            max_sprite_slots=1,
        )
        qtbot.addWidget(window)
        window.show()

        assert window.isVisible()
        assert window.sprite_mode is False
        assert window.max_sprite_slots == 1

    def test_ui_update_manager_signals_to_window(self, qtbot):
        """UIUpdateManager signals update the ChatUIWindow correctly."""
        from PySide6.QtWidgets import QApplication
        from ui.chat_ui.chat_ui import ChatUIWindow
        from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
        from test.mocks import MockLLMAdapter

        mock_llm = MockLLMAdapter(responses=[""])
        from llm.llm_manager import LLMManager
        llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)

        window = ChatUIWindow(
            image_queue=Queue(),
            emotion_queue=Queue(),
            llm_manager=llm_mgr,
            sprite_mode=False,
            background_mode=False,
            max_sprite_slots=1,
        )
        qtbot.addWidget(window)

        ui = UIUpdateManager(chat_history=[], bg_group=[])
        connect_to_desktop_window(ui, window)

        # Emit a notification signal
        ui.post_notification("Test notification")
        # Emit a busy bar signal
        ui.post_busy_bar("Thinking...", 1.0)
        # Emit options
        ui.post_options(["Option A", "Option B"])
        # Emit numeric value
        ui.post_numeric_value("HP: 100")

        # Signals are queued; flush with processEvents
        QApplication.processEvents()

        # Verify the UI received them — window state updated
        assert window.current_options == ["Option A", "Option B"]

    def test_dialog_update_signal_to_window(self, qtbot):
        """update_dialog signal renders text in the chat display."""
        from PySide6.QtWidgets import QApplication
        from ui.chat_ui.chat_ui import ChatUIWindow
        from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
        from test.mocks import MockLLMAdapter

        mock_llm = MockLLMAdapter(responses=[""])
        from llm.llm_manager import LLMManager
        llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)

        window = ChatUIWindow(
            image_queue=Queue(),
            emotion_queue=Queue(),
            llm_manager=llm_mgr,
            sprite_mode=False,
            background_mode=False,
            max_sprite_slots=1,
        )
        qtbot.addWidget(window)

        ui = UIUpdateManager(chat_history=[], bg_group=[])
        connect_to_desktop_window(ui, window)

        ui.update_dialog("Alice", "Hello world!", "#ff6b6b", is_system=False)
        QApplication.processEvents()

        # Dialog should have been added to chat_history
        assert len(ui.chat_history) > 0
        assert "Hello world!" in ui.chat_history[-1]
        assert "Alice" in ui.chat_history[-1]

    def test_hide_busy_bar(self, qtbot):
        """hide_busy_bar clears the busy bar via signal."""
        from PySide6.QtWidgets import QApplication
        from ui.chat_ui.chat_ui import ChatUIWindow
        from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
        from test.mocks import MockLLMAdapter

        mock_llm = MockLLMAdapter(responses=[""])
        from llm.llm_manager import LLMManager
        llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)

        window = ChatUIWindow(
            image_queue=Queue(),
            emotion_queue=Queue(),
            llm_manager=llm_mgr,
            sprite_mode=False,
            background_mode=False,
            max_sprite_slots=1,
        )
        qtbot.addWidget(window)

        ui = UIUpdateManager(chat_history=[], bg_group=[])
        connect_to_desktop_window(ui, window)

        ui.post_busy_bar("Working...", 0.0)
        QApplication.processEvents()
        ui.hide_busy_bar()
        QApplication.processEvents()

        # After hide, the busy bar should not be visible
        assert not window._busy_bar.isVisible()


# =============================================================================
# Layer 4: Workers + UI pipeline (Qt with qtbot)
# =============================================================================

@pytest.mark.ui
class TestWorkerUIPipeline:
    def test_llm_worker_to_ui_signal_flow(self, qtbot):
        """LLMWorker → TTSWorker → UIWorker → UIUpdateManager signal flow.

        Uses NARR (system message) to avoid DefaultCharacterTtsHandler
        dependency on the module-level ConfigManager singleton.
        """
        from PySide6.QtWidgets import QApplication
        from ui.chat_ui.chat_ui import ChatUIWindow
        from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
        from core.runtime.workers import LLMWorker, TTSWorker, UIWorker

        # LLM responds with a NARR message — avoids DefaultCharacterTtsHandler
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "NARR", "speech": "Pipeline UI works!", "sprite": "-1"})
        ])
        from llm.llm_manager import LLMManager

        llm_mgr = LLMManager(adapter=mock_llm, max_tokens=128000)

        window = ChatUIWindow(
            image_queue=Queue(),
            emotion_queue=Queue(),
            llm_manager=llm_mgr,
            sprite_mode=False,
            background_mode=False,
            max_sprite_slots=1,
        )
        qtbot.addWidget(window)

        ui = UIUpdateManager(chat_history=[], bg_group=[])
        connect_to_desktop_window(ui, window)

        # Build AppRuntime with real queues
        ac = _make_base_config()
        config_mgr = MagicMock(spec=ConfigManager)
        config_mgr.config = ac
        config_mgr.get_character_by_name.return_value = ac.characters[0]
        text_processor = MagicMock()
        text_processor.remove_parentheses.side_effect = lambda s: s
        text_processor.html_to_plain_qt.side_effect = lambda s: s
        text_processor.decide_language.return_value = "zh"
        text_processor.replace_names.side_effect = lambda s: s

        from core.runtime.app_runtime import AppRuntime
        rt = AppRuntime(
            config=config_mgr,
            ui_update_manager=ui,
            llm_manager=llm_mgr,
            tts_manager=None,
            t2i_manager=None,
            bgm_list=[],
            user_input_queue=Queue(),
            tts_queue=Queue(),
            audio_path_queue=Queue(),
            text_processor=text_processor,
            opencc=MagicMock(),
        )
        rt.opencc.convert.side_effect = lambda s: s
        set_app_runtime(rt)

        # Start all three workers
        ui_worker = UIWorker(rt.audio_path_queue)
        tts_worker = TTSWorker(rt.tts_queue, rt.audio_path_queue)
        llm_worker = LLMWorker(rt.user_input_queue, rt.tts_queue)

        ui_worker.start()
        tts_worker.start()
        llm_worker.start()

        # Send user input
        rt.user_input_queue.put(UserInputMessage(text="Hello!"))

        # Let the full pipeline process: LLM → TTS → UI
        # The UIWorker consumes from audio_path_queue internally.
        def _dialog_appeared():
            return any("Pipeline UI works!" in entry for entry in ui.chat_history)

        try:
            qtbot.waitUntil(_dialog_appeared, timeout=15000)
        except Exception:
            llm_worker.stop()
            tts_worker.stop()
            ui_worker.stop()
            llm_worker.wait(3000)
            tts_worker.wait(3000)
            ui_worker.wait(3000)
            pytest.fail(f"Pipeline: dialog never reached UI. chat_history={ui.chat_history}")

        QApplication.processEvents()

        llm_worker.stop()
        tts_worker.stop()
        ui_worker.stop()
        llm_worker.wait(3000)
        tts_worker.wait(3000)
        ui_worker.wait(3000)
