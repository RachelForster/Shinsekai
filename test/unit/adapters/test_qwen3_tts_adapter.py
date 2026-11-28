from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from ai.tts.qwen3_tts_adapter import (
    DEFAULT_QWEN3_TTS_URL,
    Qwen3TTSLlamaAdapter,
    _normalize_qwen3_tts_lang,
    discover_qwen3_tts_files,
)


def _touch_gguf(path: Path, data: bytes = b"GGUFtest") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _fake_wav(payload: bytes = b"\x00\x01" * 40) -> bytes:
    return b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 28 + payload


def test_discover_qwen3_tts_files_uses_storage_layout_and_perception_fallback(tmp_path):
    project_root = tmp_path / "proj"
    model = _touch_gguf(project_root / "data" / "models" / "qwen3-tts-gguf" / "Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf")
    mmproj = _touch_gguf(
        project_root / "data" / "models" / "qwen3-tts-gguf" / "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf"
    )
    exe_name = "llama-server.exe" if Path("C:/").exists() else "llama-server"
    server = _touch_gguf(project_root / "data" / "cache" / "perception-gguf" / "llama.cpp" / exe_name, b"bin")

    found_server, found_model, found_mmproj = discover_qwen3_tts_files(project_root=project_root)

    assert Path(found_server).resolve() == server.resolve()
    assert Path(found_model).resolve() == model.resolve()
    assert Path(found_mmproj).resolve() == mmproj.resolve()


def test_discover_qwen3_tts_files_prefers_work_path_and_explicit_overrides(tmp_path):
    work_dir = tmp_path / "custom-tts"
    exe_name = "llama-server.exe" if Path("C:/").exists() else "llama-server"
    work_server = _touch_gguf(work_dir / "llama.cpp" / exe_name, b"bin")
    _touch_gguf(work_dir / "Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf")
    work_mmproj = _touch_gguf(work_dir / "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf")
    explicit_model = _touch_gguf(tmp_path / "override.gguf")

    found_server, found_model, found_mmproj = discover_qwen3_tts_files(
        work_path=str(work_dir),
        model_path=str(explicit_model),
        project_root=tmp_path,
    )

    assert Path(found_server).resolve() == work_server.resolve()
    assert Path(found_model).resolve() == explicit_model.resolve()
    assert Path(found_mmproj).resolve() == work_mmproj.resolve()


def test_local_vs_remote_proxy_and_auto_start_behavior(monkeypatch):
    popen_calls = []

    def raise_offline(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("ai.tts.qwen3_tts_adapter.requests.Session.get", raise_offline)
    monkeypatch.setattr(
        "ai.tts.qwen3_tts_adapter.subprocess.Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    remote = Qwen3TTSLlamaAdapter(tts_server_url="https://tts.example.com/")
    try:
        assert remote._session.trust_env is True
        assert popen_calls == []
    finally:
        remote.stop_server()

    monkeypatch.setattr(Qwen3TTSLlamaAdapter, "_start_server_process", lambda self: None)
    local = Qwen3TTSLlamaAdapter(tts_server_url=DEFAULT_QWEN3_TTS_URL)
    try:
        assert local._session.trust_env is False
    finally:
        local.stop_server()


def test_wait_until_ready_distinguishes_503_loading_from_200_ready(monkeypatch):
    adapter = object.__new__(Qwen3TTSLlamaAdapter)
    adapter.tts_server_url = DEFAULT_QWEN3_TTS_URL
    adapter._server_process = None
    adapter._logs = ["line 1"]
    adapter._session = requests.Session()
    statuses = iter([503, 503, 200])
    monkeypatch.setattr(
        adapter._session,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=next(statuses)),
    )
    monkeypatch.setattr("ai.tts.qwen3_tts_adapter.time.sleep", lambda _sec: None)

    adapter.wait_until_ready(timeout_seconds=2.0, poll_interval_seconds=0.01)


def test_wait_until_ready_reports_premature_exit_logs_and_timeout(monkeypatch):
    adapter = object.__new__(Qwen3TTSLlamaAdapter)
    adapter.tts_server_url = DEFAULT_QWEN3_TTS_URL
    adapter._logs = ["init failed", "missing mmproj"]
    adapter._session = requests.Session()
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: False)

    adapter._server_process = SimpleNamespace(poll=lambda: 9)
    with pytest.raises(RuntimeError, match=r"exited before becoming ready \(code 9\): init failed \| missing mmproj"):
        adapter.wait_until_ready(timeout_seconds=1.0, poll_interval_seconds=0.01)

    adapter._server_process = None
    with pytest.raises(TimeoutError, match="did not become ready within 0 seconds"):
        adapter.wait_until_ready(timeout_seconds=0.0, poll_interval_seconds=0.01)


def test_generate_speech_sends_cached_speaker_ref_and_omits_speed(monkeypatch, tmp_path):
    monkeypatch.setattr(Qwen3TTSLlamaAdapter, "_start_server_process", lambda self: None)
    post_calls = []

    def fake_post(self, url, **kwargs):
        post_calls.append((url, kwargs))
        return SimpleNamespace(ok=True, status_code=200, content=_fake_wav(), text="")

    monkeypatch.setattr("ai.tts.qwen3_tts_adapter.requests.Session.post", fake_post)

    ref_wav = tmp_path / "ref.wav"
    ref_bytes = b"RIFFref-data"
    ref_wav.write_bytes(ref_bytes)
    out1 = tmp_path / "nested" / "out1.wav"
    out2 = tmp_path / "nested" / "out2.wav"

    adapter = Qwen3TTSLlamaAdapter(tts_server_url=DEFAULT_QWEN3_TTS_URL)
    try:
        res1 = adapter.generate_speech(
            "こんにちは",
            file_path=str(out1),
            ref_audio_path=str(ref_wav),
            text_lang="ja_JP",
            speed_factor=1.25,
        )
        res2 = adapter.generate_speech(
            "二回目",
            file_path=str(out2),
            ref_audio_path=str(ref_wav),
            text_lang="zh_CN",
        )
        assert res1 == str(out1.resolve())
        assert res2 == str(out2.resolve())
        assert out1.read_bytes().startswith(b"RIFF")

        payload1 = post_calls[0][1]["json"]
        payload2 = post_calls[1][1]["json"]
        assert post_calls[0][0] == "http://127.0.0.1:9882/v1/audio/speech"
        assert payload1 == {
            "input": "こんにちは",
            "response_format": "wav",
            "lang": "japanese",
            "speaker_ref_b64": base64.b64encode(ref_bytes).decode("ascii"),
        }
        assert "speed" not in payload1
        assert "voice" not in payload1
        assert payload2["lang"] == "chinese"
        assert payload2["speaker_ref_b64"] == payload1["speaker_ref_b64"]
    finally:
        adapter.stop_server()


def test_preset_voice_mode_disables_ref_requirement_and_excludes_speaker_ref(monkeypatch, tmp_path):
    monkeypatch.setattr(Qwen3TTSLlamaAdapter, "_start_server_process", lambda self: None)
    post_calls = []

    def fake_post(self, url, **kwargs):
        post_calls.append((url, kwargs))
        return SimpleNamespace(ok=True, status_code=200, content=_fake_wav(), text="")

    monkeypatch.setattr("ai.tts.qwen3_tts_adapter.requests.Session.post", fake_post)

    ref_wav = tmp_path / "ref.wav"
    ref_wav.write_bytes(b"RIFFunused")
    out = tmp_path / "voice.wav"

    adapter = Qwen3TTSLlamaAdapter(tts_server_url=DEFAULT_QWEN3_TTS_URL, voice="vivian")
    try:
        assert adapter.requires_ref_audio is False
        adapter.switch_model({"gpt_model_path": "ignored.ckpt"})
        assert adapter.requires_ref_audio is False

        result = adapter.generate_speech(
            "Hello world",
            file_path=str(out),
            ref_audio_path=str(ref_wav),
            text_lang="en",
        )
        assert result == str(out.resolve())
        payload = post_calls[0][1]["json"]
        assert payload == {
            "input": "Hello world",
            "response_format": "wav",
            "lang": "english",
            "voice": "vivian",
        }
        assert "speaker_ref_b64" not in payload
    finally:
        adapter.stop_server()


def test_stop_server_terminates_child_process(monkeypatch):
    monkeypatch.setattr(Qwen3TTSLlamaAdapter, "_start_server_process", lambda self: None)
    events = []

    class FakeProc:
        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append(("wait", timeout))

        def kill(self):
            events.append("kill")

    adapter = Qwen3TTSLlamaAdapter(tts_server_url=DEFAULT_QWEN3_TTS_URL)
    assert adapter.owns_server_process is False
    adapter._server_process = FakeProc()
    assert adapter.owns_server_process is True
    adapter.stop_server()

    assert events == ["terminate", ("wait", 5)]
    assert adapter._server_process is None
    assert adapter.owns_server_process is False


def test_normalize_lang_and_schema_labels():
    assert _normalize_qwen3_tts_lang("zh_CN") == "chinese"
    assert _normalize_qwen3_tts_lang("all_ja") == "japanese"
    assert _normalize_qwen3_tts_lang("en-US") == "english"
    assert _normalize_qwen3_tts_lang("auto") == ""

    schema = Qwen3TTSLlamaAdapter.get_config_schema()
    assert {"model_path", "mmproj_path", "llama_server_path", "voice", "n_gpu_layers", "ctx_size"} <= schema.keys()
