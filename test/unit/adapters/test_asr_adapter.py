"""Unit tests for ASR Manager + Factory + adapter helper functions."""

import pytest
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

from ai.asr.asr_manager import ASRAdapterFactory
from ai.asr.asr_adapter import (
    VoskAdapter,
    voice_ui_to_asr_lang,
    ui_lang_to_asr_lang,
    system_config_to_asr_lang,
    normalize_asr_provider_storage_key,
    _whisper_triplet_from_sys,
)
from sdk.adapters.asr import ASRAdapter
from test.mocks import MockASRAdapter


class TestASRAdapterFactory:
    def test_builtin_vosk_registered(self):
        assert "vosk" in ASRAdapterFactory._adapters

    def test_factory_accepts_injection(self):
        ASRAdapterFactory._adapters["mock-asr"] = MockASRAdapter
        try:
            assert "mock-asr" in ASRAdapterFactory._adapters
        finally:
            del ASRAdapterFactory._adapters["mock-asr"]

    def test_factory_values_are_adapter_subclasses(self):
        for key, cls in ASRAdapterFactory._adapters.items():
            assert issubclass(cls, ASRAdapter), key


def test_vosk_start_raises_when_model_failed_to_load() -> None:
    adapter = object.__new__(VoskAdapter)
    adapter._is_running = False
    adapter.model = None
    adapter.model_path = "C:/missing-vosk-model"

    with pytest.raises(RuntimeError, match="Vosk model is unavailable"):
        adapter.start()


@pytest.mark.parametrize("finish", [True, False])
def test_vosk_flushes_decoder_only_on_finish_and_releases_microphone(finish):
    adapter = object.__new__(VoskAdapter)
    adapter._is_running = False
    adapter._pause_event = Event()
    adapter.model = object()
    adapter.samplerate, adapter.chunk_size = 16000, 8192
    entered, release = Event(), Event()
    transcript = []
    adapter.callback = lambda text, is_partial: transcript.append((text, is_partial))
    recognizer = Mock()
    recognizer.AcceptWaveform.return_value = False
    recognizer.PartialResult.return_value = '{"partial":"draft"}'
    recognizer.FinalResult.return_value = '{"text":"final words"}'
    adapter._KaldiRecognizer = lambda *args: recognizer
    stream = Mock()
    def read(*args, **kwargs):
        entered.set()
        assert release.wait(1)
        return b"audio"
    stream.read.side_effect = read
    audio = Mock()
    audio.open.return_value = stream
    adapter._pyaudio = SimpleNamespace(PyAudio=lambda: audio, paInt16=8)
    adapter.start()
    assert entered.wait(1)
    stopped = Event()
    def stop():
        (adapter.finish if finish else adapter.stop)()
        stopped.set()
    worker = Thread(target=stop)
    worker.start()
    release.set()
    worker.join(2)
    assert stopped.is_set()
    assert transcript == ([('draft', True), ('final words', False)] if finish else [('draft', True)])
    assert recognizer.FinalResult.call_count == int(finish)
    stream.close.assert_called_once()
    audio.terminate.assert_called_once()


class TestMockASRAdapter:
    def test_init_defaults(self, mock_asr_adapter):
        assert mock_asr_adapter.language == "zh"
        assert mock_asr_adapter.get_status() == "idle"

    def test_start_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        assert mock_asr_adapter.get_status() == "listening"

    def test_stop_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.stop()
        assert mock_asr_adapter.get_status() == "stopped"

    def test_pause_changes_status(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        assert mock_asr_adapter.get_status() == "paused"

    def test_resume_after_pause(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        mock_asr_adapter.resume()
        assert mock_asr_adapter.get_status() == "listening"

    def test_callback_fires(self, mock_asr_adapter):
        results = []
        adapter = MockASRAdapter(language="en", callback=lambda text, is_final: results.append((text, is_final)))
        adapter.simulate_transcription("hello", is_final=True)
        assert results == [("hello", True)]

    def test_call_history_records(self, mock_asr_adapter):
        mock_asr_adapter.start()
        mock_asr_adapter.pause()
        mock_asr_adapter.resume()
        mock_asr_adapter.stop()
        assert mock_asr_adapter.call_history == ["start", "pause", "resume", "stop"]


class TestLanguageMapping:
    def test_voice_ui_zh(self):
        assert voice_ui_to_asr_lang("zh_CN") == "zh"
        assert voice_ui_to_asr_lang("zh") == "zh"

    def test_voice_ui_ja(self):
        assert voice_ui_to_asr_lang("ja") == "ja"
        assert voice_ui_to_asr_lang("JA") == "ja"

    def test_voice_ui_en(self):
        assert voice_ui_to_asr_lang("en") == "en"
        assert voice_ui_to_asr_lang("en_US") == "en"

    def test_voice_ui_default(self):
        assert voice_ui_to_asr_lang("") == "zh"
        assert voice_ui_to_asr_lang("fr") == "zh"

    def test_ui_lang_to_asr_mapping(self):
        assert ui_lang_to_asr_lang("zh_CN") == "zh"
        assert ui_lang_to_asr_lang("en") == "en"
        assert ui_lang_to_asr_lang("ja") == "ja"
        assert ui_lang_to_asr_lang(None) == "zh"
        assert ui_lang_to_asr_lang("fr") == "zh"


class TestSystemConfigToAsrLang:
    def test_explicit_asr_language_takes_priority(self):
        class FakeSysCfg:
            asr_language = "ja"
            ui_language = "zh_CN"
        assert system_config_to_asr_lang(FakeSysCfg()) == "ja"

    def test_empty_asr_language_falls_back_to_ui(self):
        class FakeSysCfg:
            asr_language = ""
            ui_language = "en"
        assert system_config_to_asr_lang(FakeSysCfg()) == "en"

    def test_none_asr_language_falls_back(self):
        class FakeSysCfg:
            asr_language = None
            ui_language = "ja"
        assert system_config_to_asr_lang(FakeSysCfg()) == "ja"


class TestNormalizeAsrProviderKey:
    def test_vosk(self):
        assert normalize_asr_provider_storage_key("vosk") == "vosk"

    def test_faster_whisper_variants(self):
        assert normalize_asr_provider_storage_key("faster_whisper") == "faster_whisper"
        assert normalize_asr_provider_storage_key("fasterwhisper") == "faster_whisper"
        assert normalize_asr_provider_storage_key("whisper") == "faster_whisper"

    def test_realtime_stt_variants(self):
        assert normalize_asr_provider_storage_key("realtime_stt") == "realtime_stt"
        assert normalize_asr_provider_storage_key("realtimestt") == "realtime_stt"

    def test_unknown_plugin_slug_is_preserved(self):
        assert normalize_asr_provider_storage_key("funasr_wss") == "funasr_wss"

    def test_sherpa_onnx_variants(self):
        from config.models import SystemConfig

        assert SystemConfig().asr_provider == "sherpa_onnx"
        assert normalize_asr_provider_storage_key("") == "sherpa_onnx"
        assert normalize_asr_provider_storage_key("sherpa_onnx") == "sherpa_onnx"
        assert normalize_asr_provider_storage_key("sherpa-onnx") == "sherpa_onnx"
        assert normalize_asr_provider_storage_key("sherpa") == "sherpa_onnx"
        assert "sherpa_onnx" in ASRAdapterFactory._adapters


class TestSherpaOnnxAdapter:
    def _build_stub_adapter(self, events: list[tuple[str, bool]]):
        from collections import deque
        import numpy as np
        from threading import Event, Lock
        from ai.asr.sherpa_onnx_adapter import SherpaOnnxAdapter

        adapter = object.__new__(SherpaOnnxAdapter)
        adapter.language = "zh"
        adapter.callback = lambda text, is_partial: events.append((text, is_partial))
        adapter._np = np
        adapter._rms_threshold = 0.012
        adapter._decode_lock = Lock()
        adapter._online_stream = Mock()
        adapter._preroll = deque(maxlen=SherpaOnnxAdapter.PREROLL_CHUNKS)
        adapter._utterance_chunks = []
        adapter._speech_chunks = 0
        adapter._silent_chunks = 0
        adapter._last_partial = ""
        adapter._is_running = True
        adapter._pause_event = Event()
        adapter._pause_event.set()
        return adapter

    def test_normalize_sensevoice_language(self):
        from ai.asr.sherpa_onnx_adapter import normalize_sensevoice_language

        assert normalize_sensevoice_language("") == ""
        assert normalize_sensevoice_language("auto") == ""
        assert normalize_sensevoice_language("zh_CN") == "zh"
        assert normalize_sensevoice_language("ja") == "ja"
        assert normalize_sensevoice_language("yue") == "yue"
        assert normalize_sensevoice_language("en") == "en"

    def test_dual_stage_streaming_preview_then_sensevoice_polish(self):
        import numpy as np

        events: list[tuple[str, bool]] = []
        adapter = self._build_stub_adapter(events)

        online = Mock()
        online.is_ready.return_value = False
        online.get_result.side_effect = ["你好", "你好世界", "你好世界"]
        online.is_endpoint.side_effect = [False, False, True]
        adapter._online_recognizer = online

        offline_stream = Mock()
        offline_stream.result = SimpleNamespace(text="你好，世界！")
        offline = Mock()
        offline.create_stream.return_value = offline_stream
        adapter._offline_recognizer = offline

        voiced_chunk = np.full(1600, 0.05, dtype=np.float32)
        adapter._process_audio_chunk(voiced_chunk)
        adapter._process_audio_chunk(voiced_chunk)
        adapter._process_audio_chunk(voiced_chunk)

        assert events == [
            ("你好", True),
            ("你好世界", True),
            ("你好，世界！", False),
        ]
        online.reset.assert_called_once()

    def test_rms_fallback_polishes_non_zh_en_speech_and_finish_hold_keeps_warm(self):
        import numpy as np

        events: list[tuple[str, bool]] = []
        adapter = self._build_stub_adapter(events)

        online = Mock()
        online.is_ready.return_value = False
        online.get_result.return_value = ""
        online.is_endpoint.return_value = False
        adapter._online_recognizer = online

        offline_stream = Mock()
        offline_stream.result = SimpleNamespace(text="おはようございます。")
        offline = Mock()
        offline.create_stream.return_value = offline_stream
        adapter._offline_recognizer = offline

        voiced = np.full(1600, 0.05, dtype=np.float32)
        for _ in range(3):
            adapter._process_audio_chunk(voiced)

        assert adapter.finish_hold(cancel=False) is True
        assert events == [("おはようございます。", False)]

    def test_partial_then_blank_silence_triggers_rms_endpoint(self):
        import numpy as np
        from ai.asr.sherpa_onnx_adapter import SherpaOnnxAdapter

        events: list[tuple[str, bool]] = []
        adapter = self._build_stub_adapter(events)

        silence_count = SherpaOnnxAdapter.RMS_TRAILING_SILENCE_CHUNKS
        online = Mock()
        online.is_ready.return_value = False
        online.get_result.side_effect = ["你好", *([""] * silence_count)]
        online.is_endpoint.return_value = False
        adapter._online_recognizer = online

        offline_stream = Mock()
        offline_stream.result = SimpleNamespace(text="你好。")
        offline = Mock()
        offline.create_stream.return_value = offline_stream
        adapter._offline_recognizer = offline

        voiced = np.full(1600, 0.05, dtype=np.float32)
        silent = np.zeros(1600, dtype=np.float32)
        adapter._process_audio_chunk(voiced)
        for _ in range(silence_count):
            adapter._process_audio_chunk(silent)

        assert events == [
            ("你好", True),
            ("你好。", False),
        ]
        assert adapter._silent_chunks == 0
        assert adapter._last_partial == ""
        online.reset.assert_called_once()

    def test_create_default_asr_adapter_falls_back_to_vosk_when_sherpa_missing(
        self, tmp_path, monkeypatch
    ):
        from ai.asr import asr_adapter
        from ai.asr.asr_manager import ASRAdapterFactory
        from config.config_manager import ConfigManager

        vosk_dir = tmp_path / "vosk-model"
        vosk_dir.mkdir()

        fake_cfg_mgr = Mock()
        fake_cfg_mgr.config = SimpleNamespace(
            system_config=SimpleNamespace(
                asr_provider="sherpa_onnx",
                asr_language="",
                ui_language="zh_CN",
                asr_whisper_model_size="small",
                asr_whisper_device="auto",
                asr_whisper_compute_type="",
            )
        )
        fake_cfg_mgr.get_adapter_extra_config.return_value = {}
        monkeypatch.setattr(ConfigManager, "__new__", lambda cls: fake_cfg_mgr)
        monkeypatch.setattr(asr_adapter, "VOSK_MODEL_PATH", str(vosk_dir))

        def _missing_sherpa(*_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'sherpa_onnx'", name="sherpa_onnx")

        sentinel_vosk = Mock(spec=asr_adapter.VoskAdapter)
        monkeypatch.setitem(ASRAdapterFactory._adapters, "sherpa_onnx", _missing_sherpa)
        monkeypatch.setattr(asr_adapter, "VoskAdapter", Mock(return_value=sentinel_vosk))

        created = asr_adapter.create_default_asr_adapter(lambda *_a: None)
        assert created is sentinel_vosk


class TestWhisperTriplet:
    def test_returns_defaults(self):
        class FakeSysCfg:
            asr_whisper_model_size = None
            asr_whisper_device = None
            asr_whisper_compute_type = None
        sz, dev, ct = _whisper_triplet_from_sys(FakeSysCfg())
        assert sz == "small"
        assert dev == "auto"
        assert ct == ""

    def test_returns_custom_values(self):
        class FakeSysCfg:
            asr_whisper_model_size = "large-v3"
            asr_whisper_device = "cuda"
            asr_whisper_compute_type = "float16"
        sz, dev, ct = _whisper_triplet_from_sys(FakeSysCfg())
        assert sz == "large-v3"
        assert dev == "cuda"
        assert ct == "float16"
