"""Unit tests for TTSManager — factory, queue behavior, adapter switching."""

import time
import os
from pathlib import Path

import pytest
import requests

from ai.tts.tts_adapter import GenieTTSAdapter, GPTSoVitsAdapter, IndexTTSAdapter
from ai.tts.tts_manager import TTSManager, TTSAdapterFactory
from test.mocks import MockTTSAdapter


class EmptyThenSuccessTTSAdapter(MockTTSAdapter):
    def __init__(self):
        super().__init__()
        self._calls = 0

    def generate_speech(self, text, file_path=None, **kwargs):
        self._calls += 1
        self.call_history.append({"text": text, "file_path": file_path, "kwargs": kwargs})
        if self._calls == 1:
            return ""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake audio data")
        return str(p)


class InvalidAudioTTSAdapter(MockTTSAdapter):
    def generate_speech(self, text, file_path=None, **kwargs):
        self.call_history.append({"text": text, "file_path": file_path, "kwargs": kwargs})
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return str(p)


class TestTTSAdapterFactoryRegistry:
    def test_all_registered_adapters_present(self):
        assert "gpt-sovits" in TTSAdapterFactory._adapters
        assert "kaggle-gpt-sovits" in TTSAdapterFactory._adapters
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

    def test_factory_can_wait_for_adapter_readiness(self):
        class ReadinessAdapter(MockTTSAdapter):
            def __init__(self):
                super().__init__()
                self.ready_waited = False

            def wait_until_ready(self, timeout_seconds=None):
                self.ready_waited = True

        TTSAdapterFactory._adapters["readiness-test"] = ReadinessAdapter
        try:
            adapter = TTSAdapterFactory.create_adapter("readiness-test", wait_until_ready=True)
            assert adapter.ready_waited is True
        finally:
            del TTSAdapterFactory._adapters["readiness-test"]

    def test_factory_stops_adapter_when_readiness_fails(self):
        class FailingReadinessAdapter(MockTTSAdapter):
            stopped = False

            def wait_until_ready(self, timeout_seconds=None):
                raise TimeoutError("not ready")

            def stop_server(self):
                type(self).stopped = True

        TTSAdapterFactory._adapters["failing-readiness-test"] = FailingReadinessAdapter
        try:
            with pytest.raises(TimeoutError, match="not ready"):
                TTSAdapterFactory.create_adapter("failing-readiness-test", wait_until_ready=True)
            assert FailingReadinessAdapter.stopped is True
        finally:
            del TTSAdapterFactory._adapters["failing-readiness-test"]

    def test_factory_stops_adapter_when_readiness_is_cancelled(self):
        class CancelledReadinessAdapter(MockTTSAdapter):
            stopped = False

            def wait_until_ready(self, timeout_seconds=None):
                raise KeyboardInterrupt()

            def stop_server(self):
                type(self).stopped = True

        TTSAdapterFactory._adapters["cancelled-readiness-test"] = CancelledReadinessAdapter
        try:
            with pytest.raises(KeyboardInterrupt):
                TTSAdapterFactory.create_adapter("cancelled-readiness-test", wait_until_ready=True)
            assert CancelledReadinessAdapter.stopped is True
        finally:
            del TTSAdapterFactory._adapters["cancelled-readiness-test"]

    def test_local_gpt_sovits_requires_startup_path_when_server_is_down(self, monkeypatch):
        monkeypatch.setattr(GPTSoVitsAdapter, "_server_is_reachable", lambda self: False)
        monkeypatch.setattr(GPTSoVitsAdapter, "_is_local_server_url", lambda self: True)

        with pytest.raises(RuntimeError, match="GPT-SoVITS startup path"):
            GPTSoVitsAdapter(gpt_sovits_work_path="")

    def test_local_genie_tts_requires_startup_path_when_server_is_down(self, monkeypatch):
        monkeypatch.setattr(GenieTTSAdapter, "_is_server_alive", lambda self: False)

        with pytest.raises(RuntimeError, match="Genie TTS startup path"):
            GenieTTSAdapter(gpt_sovits_work_path="")

    def test_local_index_tts_accepts_shared_path_argument_and_rejects_empty_path(self, monkeypatch):
        def fake_get(*_args, **_kwargs):
            raise requests.RequestException("server down")

        monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.get", fake_get)

        with pytest.raises(RuntimeError, match="IndexTTS startup path"):
            IndexTTSAdapter(tts_server_url="http://127.0.0.1:9880", gpt_sovits_work_path="")


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

    def test_generate_tts_replaces_existing_cache_file_and_removes_part(self, mock_tts_adapter, tmp_path):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.audio_cache_dir = tmp_path

        final_audio = tmp_path / "0.wav"
        final_audio.write_bytes(b"old audio")
        ref_audio = tmp_path / "ref.wav"
        ref_audio.write_text("fake ref")

        try:
            result = mgr.generate_tts(
                text="Hello world",
                ref_audio_path=str(ref_audio),
                prompt_text="Hello",
                prompt_lang="en",
            )

            assert result == str(final_audio)
            assert final_audio.read_bytes() == b"fake audio data"
            staging = Path(mock_tts_adapter.call_history[-1]["file_path"])
            assert staging.parent == tmp_path
            assert staging.name.startswith(".0.wav.")
            assert staging.name.endswith(".part")
            assert not staging.exists()
        finally:
            mgr.shutdown()

    def test_generate_tts_no_ref_audio_returns_empty(self, mock_tts_adapter):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        result = mgr.generate_tts(text="Hello", ref_audio_path=None)
        assert result == ""
        mgr.shutdown()

    def test_generate_tts_rejects_reference_audio_alias_before_adapter_call(
        self,
        mock_tts_adapter,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        reference = project / "data" / "speech" / "ref.wav"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"wav")
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        try:
            result = mgr.generate_tts(
                text="Hello",
                ref_audio_path="data/speech/./ref.wav",
            )
        finally:
            mgr.shutdown()

        assert result == ""
        assert mock_tts_adapter.call_history == []

    def test_generate_tts_rejects_symlinked_reference_before_adapter_call(
        self,
        mock_tts_adapter,
        tmp_path,
    ):
        project = tmp_path / "project"
        external = tmp_path / "external.wav"
        reference = project / "data" / "speech" / "ref.wav"
        reference.parent.mkdir(parents=True)
        external.write_bytes(b"wav")
        try:
            reference.symlink_to(external)
        except (NotImplementedError, OSError):
            pytest.skip("file symlinks are unavailable")
        mgr = TTSManager(project_root=project)
        mgr.set_tts_adapter(mock_tts_adapter)
        try:
            result = mgr.generate_tts(
                text="Hello",
                ref_audio_path="data/speech/ref.wav",
            )
        finally:
            mgr.shutdown()

        assert result == ""
        assert mock_tts_adapter.call_history == []

    def test_generate_tts_resolves_relative_reference_against_manager_root(
        self,
        mock_tts_adapter,
        tmp_path,
    ):
        project = tmp_path / "project"
        reference = project / "data" / "speech" / "ref.wav"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"wav")
        mgr = TTSManager(project_root=project)
        mgr.set_tts_adapter(mock_tts_adapter)
        try:
            result = mgr.generate_tts(
                text="Hello",
                ref_audio_path="data/speech/ref.wav",
            )
        finally:
            mgr.shutdown()

        assert result
        assert mock_tts_adapter.call_history[0]["kwargs"]["ref_audio_path"] == (
            reference.as_posix()
        )

    def test_generate_tts_retries_empty_audio_result(self):
        adapter = EmptyThenSuccessTTSAdapter()
        mgr = TTSManager()
        mgr.set_tts_adapter(adapter)
        result = mgr.generate_tts(text="Hello", ref_audio_path="ref.wav")
        assert result
        assert Path(result).is_file()
        assert len(adapter.call_history) == 2
        mgr.shutdown()

    def test_generate_tts_returns_empty_when_retries_never_create_audio(self, tmp_path):
        adapter = InvalidAudioTTSAdapter()
        mgr = TTSManager()
        mgr.set_tts_adapter(adapter)
        mgr.audio_cache_dir = tmp_path
        result = mgr.generate_tts(text="Hello", ref_audio_path="ref.wav")
        assert result == ""
        assert not list(tmp_path.glob(".0.wav.*.part"))
        assert len(adapter.call_history) == 2
        mgr.shutdown()

    def test_generate_tts_rejects_cache_directory_replaced_during_adapter_call(
        self,
        tmp_path,
    ):
        cache = tmp_path / "cache"
        cache.mkdir()
        preserved_cache = tmp_path / "preserved-cache"
        reference = tmp_path / "ref.wav"
        reference.write_bytes(b"reference")

        class ReplacingCacheAdapter(MockTTSAdapter):
            def generate_speech(self, text, file_path=None, **kwargs):
                self.call_history.append(
                    {"text": text, "file_path": file_path, "kwargs": kwargs}
                )
                cache.rename(preserved_cache)
                cache.mkdir()
                (cache / "0.wav").write_bytes(b"peer")
                staging = Path(file_path)
                staging.write_bytes(b"generated")
                return str(staging)

        mgr = TTSManager()
        mgr.audio_cache_dir = cache
        mgr.set_tts_adapter(ReplacingCacheAdapter())
        try:
            with pytest.raises(PermissionError, match="parent identity changed"):
                mgr.generate_tts(text="Hello", ref_audio_path=reference)
        finally:
            mgr.shutdown()

        assert (cache / "0.wav").read_bytes() == b"peer"
        assert list(preserved_cache.iterdir()) == []
        assert not list(cache.glob(".*.part"))

    def test_generate_tts_rejects_cache_destination_symlink(
        self,
        mock_tts_adapter,
        tmp_path,
    ):
        mgr = TTSManager()
        mgr.set_tts_adapter(mock_tts_adapter)
        mgr.audio_cache_dir = tmp_path
        external = tmp_path / "external.wav"
        final_audio = tmp_path / "0.wav"
        reference = tmp_path / "ref.wav"
        external.write_bytes(b"private")
        reference.write_bytes(b"reference")
        try:
            final_audio.symlink_to(external)
        except (OSError, NotImplementedError):
            mgr.shutdown()
            pytest.skip("symbolic links are unavailable")

        try:
            with pytest.raises(PermissionError, match="symbolic link"):
                mgr.generate_tts(text="Hello", ref_audio_path=reference)
        finally:
            mgr.shutdown()

        assert final_audio.is_symlink()
        assert external.read_bytes() == b"private"
        assert not list(tmp_path.glob(".0.wav.*.part"))

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

    def test_cache_directory_uses_project_root_after_cwd_changes(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        unrelated = tmp_path / "unrelated"
        project.mkdir()
        unrelated.mkdir()
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
        monkeypatch.chdir(unrelated)

        mgr = TTSManager()
        try:
            assert mgr.audio_cache_dir == project / "data/cache/audio"
            assert mgr.audio_cache_dir.is_dir()
            assert not (unrelated / "data").exists()
        finally:
            mgr.shutdown()

    def test_audio_validation_uses_the_manager_project_root(self, tmp_path, monkeypatch):
        manager_project = tmp_path / "manager-project"
        ambient_project = tmp_path / "ambient-project"
        ambient_project.mkdir()
        monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient_project.as_posix())

        mgr = TTSManager(project_root=manager_project)
        try:
            audio = manager_project / "data/cache/audio/probe.wav"
            audio.write_bytes(b"audio")

            assert mgr._is_valid_audio_file("data/cache/audio/probe.wav")
            assert not (ambient_project / "data/cache/audio/probe.wav").exists()
        finally:
            mgr.shutdown()

    def test_legacy_loader_uses_manager_root_and_native_bundled_python(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        work_root = project / "engines" / "gpt-sovits"
        runtime_python = (
            work_root / "runtime/python.exe"
            if os.name == "nt"
            else work_root / "runtime/bin/python3"
        )
        runtime_python.parent.mkdir(parents=True)
        runtime_python.write_bytes(b"python")
        runtime_python.chmod(runtime_python.stat().st_mode | 0o100)
        api_path = work_root / "api_v2.py"
        api_path.write_text("", encoding="utf-8")
        calls = []
        monkeypatch.setenv("PYTHONHOME", "/stale/python")
        monkeypatch.setenv("PYTHONPATH", "/stale/project")
        monkeypatch.setattr(
            "ai.tts.tts_manager.subprocess.Popen",
            lambda command, **kwargs: calls.append((command, kwargs)),
        )
        mgr = TTSManager(project_root=project)
        try:
            mgr.load_tts_model("engines/gpt-sovits")
        finally:
            mgr.shutdown()

        assert len(calls) == 1
        command, kwargs = calls[0]
        assert command == [str(runtime_python), str(api_path)]
        assert kwargs["cwd"] == str(work_root)
        assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"
        assert "PYTHONHOME" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]

    def test_legacy_loader_rejects_linked_startup_script(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        work_root = project / "engines" / "gpt-sovits"
        runtime_python = (
            work_root / "runtime/python.exe"
            if os.name == "nt"
            else work_root / "runtime/bin/python3"
        )
        runtime_python.parent.mkdir(parents=True)
        runtime_python.write_bytes(b"python")
        runtime_python.chmod(runtime_python.stat().st_mode | 0o100)
        external_script = tmp_path / "api_v2.py"
        external_script.write_text("", encoding="utf-8")
        try:
            (work_root / "api_v2.py").symlink_to(external_script)
        except (NotImplementedError, OSError):
            pytest.skip("file symlinks are unavailable")
        calls = []
        monkeypatch.setattr(
            "ai.tts.tts_manager.subprocess.Popen",
            lambda command, **kwargs: calls.append((command, kwargs)),
        )
        mgr = TTSManager(project_root=project)
        try:
            with pytest.raises(PermissionError, match="symbolic link"):
                mgr.load_tts_model("engines/gpt-sovits")
        finally:
            mgr.shutdown()

        assert calls == []

    def test_legacy_loader_has_no_machine_specific_default(self, tmp_path):
        mgr = TTSManager(project_root=tmp_path)
        try:
            with pytest.raises(ValueError, match="work path is required"):
                mgr.load_tts_model()
        finally:
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
