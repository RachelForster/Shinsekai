"""Unit tests for ASR Manager + Factory + adapter helper functions."""

import pytest

from asr.asr_manager import ASRAdapterFactory
from asr.asr_adapter import (
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
            assert issubclass(cls, ASRAdapter), f"{key} → {cls} is not an ASRAdapter subclass"


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
