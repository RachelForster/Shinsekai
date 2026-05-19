"""Integration tests: LLMWorker / TTSWorker / UIWorker QThread lifecycle.

Requires pytest-qt for QApplication event loop.  All adapters are mocked;
workers use real QThread, real queues, and the real handler dispatch chain.
"""

from __future__ import annotations

import json
import time
from queue import Queue
from unittest.mock import MagicMock

import pytest

from sdk.messages import UserInputMessage, LLMDialogMessage, LLMTurnEndMessage, TTSOutputMessage
from test.mocks import MockLLMAdapter

# QThread workers
from core.runtime.workers import LLMWorker, TTSWorker, UIWorker
from core.runtime.app_runtime import AppRuntime, set_app_runtime

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime_for_workers(mock_llm_adapter=None, **overrides):
    """Build a minimal AppRuntime suitable for worker testing."""
    from config.schema import AppConfig, ApiConfig, SystemConfig, Character, Background
    from config.config_manager import ConfigManager
    from llm.llm_manager import LLMManager
    from test.conftest import make_app_config

    app_config = make_app_config()
    # Set streaming to False by default for simpler tests
    app_config.api_config.is_streaming = overrides.get("is_streaming", False)

    config_mgr = MagicMock(spec=ConfigManager)
    config_mgr.config = app_config
    config_mgr.get_character_by_name.return_value = app_config.characters[0]

    adapter = mock_llm_adapter or MockLLMAdapter(responses=["Mock response."])
    llm_mgr = LLMManager(adapter=adapter, max_tokens=128000)

    ui_mgr = MagicMock()
    ui_mgr.chat_history = []

    rt = AppRuntime(
        config=config_mgr,
        ui_update_manager=ui_mgr,
        llm_manager=llm_mgr,
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=overrides.get("user_input_queue", Queue()),
        tts_queue=overrides.get("tts_queue", Queue()),
        audio_path_queue=overrides.get("audio_path_queue", Queue()),
        text_processor=MagicMock(),
        opencc=MagicMock(),
    )
    rt.opencc.convert.side_effect = lambda s: s
    return rt


def _next_llm_dialog(queue: Queue, timeout: float = 5) -> LLMDialogMessage:
    deadline = time.monotonic() + timeout
    while True:
        item = queue.get(timeout=max(0.01, deadline - time.monotonic()))
        if isinstance(item, LLMDialogMessage):
            return item
        assert isinstance(item, LLMTurnEndMessage)


# ---------------------------------------------------------------------------
# LLMWorker
# ---------------------------------------------------------------------------

class TestLLMWorker:
    def test_worker_creates_and_runs(self, qtbot):
        """LLMWorker starts, processes a message, puts dialogs into tts_queue, then stops."""
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "TestChar", "speech": "Hello from LLM!", "sprite": "0"})
        ])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=False)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()
        assert worker.isRunning()

        # Feed a message
        rt.user_input_queue.put(UserInputMessage(text="Hi!"))

        # Wait for output in tts_queue (poll with timeout)
        try:
            result = _next_llm_dialog(rt.tts_queue)
        except Exception:
            worker.stop()
            worker.wait(3000)
            pytest.fail("Timed out waiting for tts_queue output")

        assert isinstance(result, LLMDialogMessage)
        assert result.name == "TestChar"
        assert result.text == "Hello from LLM!"

        worker.stop()
        worker.wait(3000)
        assert not worker.isRunning()

    def test_worker_stops_cleanly_without_processing(self, qtbot):
        """Worker can be stopped even if no messages were processed."""
        mock_llm = MockLLMAdapter(responses=["Unused"])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=False)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()
        assert worker.isRunning()

        worker.stop()
        worker.wait(3000)
        assert not worker.isRunning()

    def test_worker_handles_none_termination_signal(self, qtbot):
        """None in the input queue triggers worker exit."""
        mock_llm = MockLLMAdapter(responses=["Unused"])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=False)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()
        # Send None as termination
        rt.user_input_queue.put(None)

        worker.wait(3000)
        assert not worker.isRunning()

    def test_worker_streaming_mode(self, qtbot):
        """LLMWorker in streaming mode parses stream chunks correctly."""
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "Alice", "speech": "Streamed!", "sprite": "1"})
        ])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=True)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()
        rt.user_input_queue.put(UserInputMessage(text="Stream test"))

        try:
            result = _next_llm_dialog(rt.tts_queue)
        except Exception:
            worker.stop()
            worker.wait(3000)
            pytest.fail("Timed out waiting for streaming output")

        assert isinstance(result, LLMDialogMessage)
        assert result.name == "Alice"

        worker.stop()
        worker.wait(3000)

    def test_multiple_messages_sequential(self, qtbot):
        """Worker processes multiple messages sequentially."""
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "A", "speech": "First", "sprite": "0"}),
            json.dumps({"character_name": "B", "speech": "Second", "sprite": "1"}),
        ])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=False)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()

        rt.user_input_queue.put(UserInputMessage(text="Q1"))
        r1 = _next_llm_dialog(rt.tts_queue)
        assert r1.name == "A"
        assert isinstance(rt.tts_queue.get(timeout=5), LLMTurnEndMessage)

        rt.user_input_queue.put(UserInputMessage(text="Q2"))
        r2 = _next_llm_dialog(rt.tts_queue)
        assert r2.name == "B"
        assert isinstance(rt.tts_queue.get(timeout=5), LLMTurnEndMessage)

        worker.stop()
        worker.wait(3000)


# ---------------------------------------------------------------------------
# TTSWorker
# ---------------------------------------------------------------------------

class TestTTSWorker:
    def test_worker_starts_and_stops(self, qtbot):
        mock_llm = MockLLMAdapter(responses=[""])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm)
        set_app_runtime(rt)

        worker = TTSWorker(
            input_queue=rt.tts_queue,
            output_queue=rt.audio_path_queue,
        )
        worker.start()
        assert worker.isRunning()

        worker.stop()
        worker.wait(3000)
        assert not worker.isRunning()

    def test_worker_dispatches_narr_message(self, qtbot):
        """TTSWorker dispatches a NARR message through the handler chain."""
        mock_llm = MockLLMAdapter(responses=[""])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm)
        set_app_runtime(rt)

        worker = TTSWorker(
            input_queue=rt.tts_queue,
            output_queue=rt.audio_path_queue,
        )
        worker.start()

        msg = LLMDialogMessage(name="NARR", text="Once upon a time...", asset_id="-1")
        rt.tts_queue.put(msg)

        try:
            out = rt.audio_path_queue.get(timeout=5)
        except Exception:
            worker.stop()
            worker.wait(3000)
            pytest.fail("Timed out waiting for audio_path_queue output")

        assert isinstance(out, TTSOutputMessage)
        assert out.name == "NARR"
        assert out.is_system_message is True

        worker.stop()
        worker.wait(3000)


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_user_input_to_audio_output(self, qtbot):
        """End-to-end: UserInputMessage → LLMWorker → TTSWorker → audio_path_queue."""
        mock_llm = MockLLMAdapter(responses=[
            json.dumps({"character_name": "TestChar", "speech": "Pipeline works!", "sprite": "0"})
        ])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm, is_streaming=False)
        set_app_runtime(rt)

        llm_worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        tts_worker = TTSWorker(
            input_queue=rt.tts_queue,
            output_queue=rt.audio_path_queue,
        )
        llm_worker.start()
        tts_worker.start()

        # Feed user input
        rt.user_input_queue.put(UserInputMessage(text="Pipe me through!"))

        # Wait for final output
        try:
            final = rt.audio_path_queue.get(timeout=10)
        except Exception:
            llm_worker.stop()
            tts_worker.stop()
            llm_worker.wait(3000)
            tts_worker.wait(3000)
            pytest.fail("Timed out waiting for pipeline output")

        assert isinstance(final, TTSOutputMessage)
        assert "Pipeline works!" in (final.text or "")

        llm_worker.stop()
        tts_worker.stop()
        llm_worker.wait(3000)
        tts_worker.wait(3000)
