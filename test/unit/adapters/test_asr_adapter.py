"""Unit tests for ASR Manager + Factory + adapter helper functions."""

import pytest

from ai.asr.asr_manager import ASRAdapterFactory
from ai.asr.asr_adapter import (
    VoskAdapter,
    voice_ui_to_asr_lang,
    ui_lang_to_asr_lang,
    system_config_to_asr_lang,
    normalize_asr_provider_storage_key,
    _resolve_vosk_model_path,
    _resolve_whisper_model_reference,
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


def test_relative_vosk_model_uses_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)

    assert _resolve_vosk_model_path("data/models/vosk") == (
        project / "data/models/vosk"
    ).as_posix()


def test_vosk_model_path_rejects_outer_whitespace(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

    with pytest.raises(ValueError, match="surrounding whitespace"):
        _resolve_vosk_model_path(" data/models/vosk")


def test_vosk_model_path_rejects_project_symlink_escape(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    try:
        (project / "models").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic links"):
        _resolve_vosk_model_path("models/vosk")


def test_builtin_vosk_model_uses_application_resource_not_project_shadow(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    source_model = source / "assets/system/models/vosk-model"
    project_model = project / "assets/system/models/vosk-model"
    source_model.mkdir(parents=True)
    project_model.mkdir(parents=True)
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    assert _resolve_vosk_model_path("assets/system/models/vosk-model") == (
        source_model.as_posix()
    )


def test_vosk_model_path_rejects_legacy_dot_alias_after_config_migration(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

    with pytest.raises(ValueError, match="exact relative components"):
        _resolve_vosk_model_path("./assets/system/models/vosk-model")


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

    def test_local_model_uses_project_root_after_cwd_changes(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        unrelated = tmp_path / "unrelated"
        project.mkdir()
        unrelated.mkdir()
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
        monkeypatch.chdir(unrelated)

        assert _resolve_whisper_model_reference("data/models/whisper") == (
            project / "data/models/whisper"
        ).as_posix()

    def test_huggingface_model_id_is_not_reinterpreted_as_a_local_path(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

        assert (
            _resolve_whisper_model_reference("Systran/faster-whisper-small")
            == "Systran/faster-whisper-small"
        )

    def test_local_model_rejects_linked_project_parent(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        external = tmp_path / "external"
        project.mkdir()
        external.mkdir()
        try:
            (project / "data").symlink_to(external, target_is_directory=True)
        except (NotImplementedError, OSError):
            pytest.skip("directory symlinks are unavailable")
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

        with pytest.raises(PermissionError, match="symbolic link"):
            _resolve_whisper_model_reference("data/models/whisper")

    def test_model_reference_does_not_silently_trim(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

        with pytest.raises(ValueError, match="surrounding whitespace"):
            _resolve_whisper_model_reference(" small")
