"""Integration tests: LLMWorker → TTSWorker → UIWorker pipeline with mock adapters."""

import json
import time
from queue import Queue

import pytest

from sdk.messages import UserInputMessage, LLMDialogMessage, TTSOutputMessage


@pytest.mark.integration
class TestWorkerPipeline:
    def test_llm_manager_chat_with_mock(self, mock_app_runtime, mock_llm_adapter):
        """LLMManager.chat() produces a response via the mock adapter."""
        mock_llm_adapter.responses = ["Hello from mock!"]
        llm_mgr = mock_app_runtime.llm_manager

        result = llm_mgr.chat("Hi there!", stream=False, include_local_time=False)

        assert "Hello from mock!" in result
        assert len(llm_mgr.messages) >= 2  # system + user (+ assistant)

    def test_llm_manager_streaming_with_mock(self, mock_app_runtime, mock_llm_adapter):
        """LLMManager.chat() streaming yields chunks via mock adapter."""
        mock_llm_adapter.responses = ["AB"]
        llm_mgr = mock_app_runtime.llm_manager

        chunks = []
        for chunk in llm_mgr.chat("Hi", stream=True, include_local_time=False):
            if isinstance(chunk, str):
                chunks.append(chunk)

        assert len(chunks) > 0

    def test_queue_flow_user_to_tts(self, mock_app_runtime, mock_llm_adapter):
        """Simulate the worker pipeline: user_input → llm → tts_queue entries."""
        mock_llm_adapter.responses = [
            json.dumps({"character_name": "TestChar", "speech": "Hello!", "sprite": "0"})
        ]

        # Simulate what LLMWorker does
        llm_mgr = mock_app_runtime.llm_manager
        response = llm_mgr.chat("Hello?", stream=False, include_local_time=False)

        # Parse response (normally done by LlmResponseStreamParser in LLMWorker)
        from core.messaging.stream_parser import LlmResponseStreamParser

        parser = LlmResponseStreamParser()
        dialogs = list(parser.feed(response))

        for d in dialogs:
            mock_app_runtime.tts_queue.put(d)

        # Verify the dialog reached the tts_queue
        assert mock_app_runtime.tts_queue.qsize() == 1
        msg = mock_app_runtime.tts_queue.get()
        assert isinstance(msg, LLMDialogMessage)
        assert msg.name == "TestChar"
        assert msg.text == "Hello!"

    def test_full_queue_pipeline(self, mock_app_runtime, mock_llm_adapter, tmp_path):
        """End-to-end queue pipeline with mock LLM output simulating real dialog."""
        # Step 1: Put user input
        mock_app_runtime.user_input_queue.put(UserInputMessage(text="Hi"))

        # Step 2: Simulate LLM processing (normally LLMWorker)
        mock_llm_adapter.responses = [
            json.dumps({"character_name": "Alice", "speech": "Hey there!", "sprite": "1"})
        ]
        llm_mgr = mock_app_runtime.llm_manager

        input_msg = mock_app_runtime.user_input_queue.get()
        response = llm_mgr.chat(input_msg.text, stream=False, include_local_time=False)

        from core.messaging.stream_parser import LlmResponseStreamParser

        parser = LlmResponseStreamParser()
        for dialog in parser.feed(response):
            mock_app_runtime.tts_queue.put(dialog)

        # Step 3: Simulate TTS processing (normally TTSWorker)
        tts_msg = mock_app_runtime.tts_queue.get()
        assert tts_msg.name == "Alice"

        # For testing, write a fake audio file
        audio_file = tmp_path / "output.wav"
        audio_file.write_text("fake wav")

        tts_out = TTSOutputMessage(
            audio_path=str(audio_file),
            name=tts_msg.name,
            text=tts_msg.text,
            asset_id=tts_msg.asset_id or "-1",
        )
        mock_app_runtime.audio_path_queue.put(tts_out)
        mock_app_runtime.tts_queue.task_done()

        # Step 4: Verify the audio_path_queue received the output
        ui_msg = mock_app_runtime.audio_path_queue.get()
        assert isinstance(ui_msg, TTSOutputMessage)
        assert ui_msg.name == "Alice"
        assert ui_msg.text == "Hey there!"
        assert ui_msg.asset_id == "1"
