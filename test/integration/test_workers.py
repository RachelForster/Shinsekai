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

from sdk.messages import UserInputMessage, LLMDialogMessage, TTSOutputMessage
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


def _wait_for_unfinished_tasks(q: Queue, expected: int = 0, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if q.unfinished_tasks == expected:
            return True
        time.sleep(0.01)
    return q.unfinished_tasks == expected


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
            result = rt.tts_queue.get(timeout=5)
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
            result = rt.tts_queue.get(timeout=5)
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
        r1 = rt.tts_queue.get(timeout=5)
        assert r1.name == "A"

        rt.user_input_queue.put(UserInputMessage(text="Q2"))
        r2 = rt.tts_queue.get(timeout=5)
        assert r2.name == "B"

        worker.stop()
        worker.wait(3000)

    def test_worker_reports_llm_http_402_as_system_message(self, qtbot):
        """LLM API 402 errors are surfaced as clear system messages."""
        error_cls = type("APIStatusError", (Exception,), {"__module__": "openai"})

        class _Request:
            url = "https://api.example.test/v1/chat/completions"

        class _Response:
            request = _Request()
            status_code = 402

        class _FailingAdapter(MockLLMAdapter):
            def chat(self, *args, **kwargs):
                exc = error_cls("payment required")
                exc.response = _Response()
                raise exc

        rt = _make_runtime_for_workers(mock_llm_adapter=_FailingAdapter(), is_streaming=False)
        set_app_runtime(rt)

        worker = LLMWorker(
            input_queue=rt.user_input_queue,
            output_queue=rt.tts_queue,
        )
        worker.start()
        rt.user_input_queue.put(UserInputMessage(text="Trigger 402"))

        try:
            out = rt.audio_path_queue.get(timeout=5)
        except Exception:
            worker.stop()
            worker.wait(3000)
            pytest.fail("Timed out waiting for HTTP error system message")

        assert isinstance(out, TTSOutputMessage)
        assert out.is_system_message is True
        assert "402" in (out.text or "")
        assert "额度" in (out.text or "")
        assert "payment required" in (out.text or "")

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
        assert _wait_for_unfinished_tasks(rt.tts_queue)

        worker.stop()
        worker.wait(3000)

    def test_worker_marks_tts_task_done_on_dispatch_error(self, qtbot):
        mock_llm = MockLLMAdapter(responses=[""])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm)
        set_app_runtime(rt)

        worker = TTSWorker(
            input_queue=rt.tts_queue,
            output_queue=rt.audio_path_queue,
        )
        worker.tts_message_dispatcher = MagicMock()
        worker.tts_message_dispatcher.dispatch.side_effect = RuntimeError("boom")
        worker.start()

        rt.tts_queue.put(LLMDialogMessage(name="TestChar", text="Failure path", asset_id="-1"))

        assert _wait_for_unfinished_tasks(rt.tts_queue)
        worker.stop()
        worker.wait(3000)


class TestUIWorker:
    def test_worker_marks_audio_task_done_after_dispatch(self, qtbot):
        mock_llm = MockLLMAdapter(responses=[""])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm)
        set_app_runtime(rt)

        worker = UIWorker(rt.audio_path_queue)
        worker.ui_out_dispatcher = MagicMock()

        out = TTSOutputMessage(
            audio_path="",
            name="NARR",
            text="Displayed",
            asset_id="-1",
            is_system_message=True,
        )
        rt.audio_path_queue.put(out)
        rt.audio_path_queue.put(None)

        worker.run()

        worker.ui_out_dispatcher.dispatch.assert_called_once_with(out)
        assert rt.audio_path_queue.unfinished_tasks == 0

    def test_worker_marks_audio_task_done_on_dispatch_error(self, qtbot):
        mock_llm = MockLLMAdapter(responses=[""])
        rt = _make_runtime_for_workers(mock_llm_adapter=mock_llm)
        set_app_runtime(rt)

        worker = UIWorker(rt.audio_path_queue)
        worker.ui_out_dispatcher = MagicMock()
        worker.ui_out_dispatcher.dispatch.side_effect = RuntimeError("boom")

        out = TTSOutputMessage(
            audio_path="",
            name="NARR",
            text="",
            asset_id="-1",
            is_system_message=True,
        )
        rt.audio_path_queue.put(out)
        rt.audio_path_queue.put(None)

        worker.run()

        worker.ui_out_dispatcher.dispatch.assert_called_once_with(out)
        assert rt.audio_path_queue.unfinished_tasks == 0


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
