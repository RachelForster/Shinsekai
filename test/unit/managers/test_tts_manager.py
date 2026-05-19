"""Unit tests for TTSManager — factory, queue behavior, adapter switching."""

import time
from pathlib import Path

import pytest

from tts.tts_manager import TTSManager, TTSAdapterFactory
from test.mocks import MockTTSAdapter


class TestTTSAdapterFactoryRegistry:
    def test_all_registered_adapters_present(self):
        assert "gpt-sovits" in TTSAdapterFactory._adapters
        assert "genie-tts" in TTSAdapterFactory._adapters
        assert "cosyvoice" in TTSAdapterFactory._adapters

    def test_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unsupported TTS adapter"):
            TTSAdapterFactory.create_adapter("nonexistent-tts")

    def test_factory_can_be_injected_with_mock(self):
        """Register a mock adapter in the factory dict and create via factory."""
        TTSAdapterFactory._adapters["mock-tts"] = MockTTSAdapter
        try:
            adapter = TTSAdapterFactory.create_adapter("mock-tts")
            assert isinstance(adapter, MockTTSAdapter)
        finally:
            del TTSAdapterFactory._adapters["mock-tts"]

    def test_factory_filters_irrelevant_kwargs_for_cosyvoice(self):
        adapter = TTSAdapterFactory.create_adapter(
            "cosyvoice",
            api_key="test-key",
            tts_server_url="http://ignored.local",
            gpt_sovits_work_path="/ignored",
        )

        assert adapter.api_key == "test-key"

    def test_factory_filters_irrelevant_kwargs_for_index_tts(self, monkeypatch):
        class _Resp:
            status_code = 200

        monkeypatch.setattr("tts.tts_adapter.requests.get", lambda *a, **k: _Resp())

        adapter = TTSAdapterFactory.create_adapter(
            "index-tts",
            index_server_url="http://index.local/",
            index_server_work_path="/tmp/index",
            tts_server_url="http://ignored.local",
            gpt_sovits_work_path="/ignored",
        )

        assert adapter.index_server_url == "http://index.local/"
        assert adapter.gpt_sovits_work_path == "/tmp/index"


class TestTTSManagerWithMock:
    def test_set_adapter(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        assert mgr.tts_adapter is mock_tts_adapter
        mgr.shutdown()

    def test_generate_tts_with_ref_audio(self, mock_tts_adapter, tmp_path):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)

        ref_audio = tmp_path / "ref.wav"
        ref_audio.write_text("fake ref")

        result = mgr.generate_tts(
            text="Hello world",
            ref_audio_path=str(ref_audio),
            prompt_text="Hello",
            prompt_lang="en",
            character_name="TestChar",
            speed_factor=1.0,
        )
        assert result is not None
        assert len(mock_tts_adapter.call_history) == 1
        call = mock_tts_adapter.call_history[0]
        assert call["text"] == "Hello world"
        assert call["kwargs"]["character_name"] == "TestChar"
        mgr.shutdown()

    def test_generate_tts_no_ref_audio_returns_empty(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        result = mgr.generate_tts(text="Hello", ref_audio_path=None)
        assert result == ""
        mgr.shutdown()

    def test_set_language(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.set_language("zh_CN")
        assert mgr.voice_language == "zh_CN"
        mgr.shutdown()

    def test_switch_model_delegates(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.switch_model({"model": "new-model"})
        assert any("switch_model" in str(c) for c in mock_tts_adapter.call_history)
        mgr.shutdown()

    def test_switch_model_none_noop(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.switch_model(None)  # should not raise
        mgr.shutdown()

    def test_shutdown_terminates_worker(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.shutdown()
        mgr.worker_thread.join(timeout=2)
        assert not mgr.worker_thread.is_alive()

    def test_init_creates_cache_dir(self):
        mgr = TTSManager()
        assert mgr.audio_cache_dir.exists()
        mgr.shutdown()

    def test_queue_speech_with_mock(self, mock_tts_adapter, tmp_path):
        """queue_speech calls generate_tts which queues work; mock generate_tts."""
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)

        ref_audio = tmp_path / "ref.wav"
        ref_audio.write_text("fake ref audio")

        # queue_speech passes (text, language_processor) to generate_tts
        out_file = str(tmp_path / "out.wav")
        mgr.generate_tts = lambda text, text_processor=None, ref_audio_path=None, **kw: mock_tts_adapter.generate_speech(
            text=text, file_path=out_file, ref_audio_path=str(ref_audio)
        )

        mgr.queue_speech(text="Queued speech")
        time.sleep(0.2)
        assert len(mock_tts_adapter.call_history) >= 1
        mgr.shutdown()
