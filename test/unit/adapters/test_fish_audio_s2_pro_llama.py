"""Unit tests for Fish Audio S2 Pro local llama.cpp GGUF mode."""

from __future__ import annotations

import base64
import io
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any
import wave

import pytest
import requests

from ai.tts.adapters.fish_audio_llama import (
    DEFAULT_FISH_AUDIO_LLAMA_URL,
    FISH_AUDIO_BACKEND_API,
    FISH_AUDIO_BACKEND_LLAMA_CPP,
    build_fish_audio_llama_server_cmd,
    discover_fish_audio_gguf_files,
    is_fish_audio_llama_nan_buzz_wav,
    normalize_fish_audio_backend,
    resolve_fish_audio_llama_endpoints,
    sanitize_fish_audio_llama_ref_wav,
)
from ai.tts.adapters.fish_audio_s2_pro import FishAudioS2ProAdapter


def _seed_llama_assets(root: Path, *, include_mmproj: bool = True) -> dict[str, Path]:
    model_dir = root / "data" / "models" / "fish-audio-s2-pro-gguf"
    model_dir.mkdir(parents=True, exist_ok=True)
    backbone = model_dir / "s2-pro-Q8_0.gguf"
    backbone.write_bytes(b"gguf-q8")
    mmproj = model_dir / "mmproj-s2-pro-BF16.gguf"
    if include_mmproj:
        mmproj.write_bytes(b"gguf-mmproj")

    llama_dir = root / "data" / "cache" / "perception-gguf" / "llama.cpp"
    llama_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "llama-server.exe" if Path("C:/").exists() else "llama-server"
    server_exe = llama_dir / exe_name
    server_exe.write_bytes(b"bin")
    return {"model_dir": model_dir, "backbone": backbone, "mmproj": mmproj, "server": server_exe}


def test_normalize_backend_and_resolve_llama_endpoints() -> None:
    assert normalize_fish_audio_backend("") == FISH_AUDIO_BACKEND_API
    assert normalize_fish_audio_backend("api") == FISH_AUDIO_BACKEND_API
    assert normalize_fish_audio_backend("unknown") == FISH_AUDIO_BACKEND_API
    assert normalize_fish_audio_backend("llama-cpp") == FISH_AUDIO_BACKEND_LLAMA_CPP
    assert normalize_fish_audio_backend("LLAMA") == FISH_AUDIO_BACKEND_LLAMA_CPP
    assert normalize_fish_audio_backend("llama.cpp") == FISH_AUDIO_BACKEND_LLAMA_CPP
    assert normalize_fish_audio_backend("gguf") == FISH_AUDIO_BACKEND_LLAMA_CPP

    assert resolve_fish_audio_llama_endpoints("") == (
        f"{DEFAULT_FISH_AUDIO_LLAMA_URL}/",
        f"{DEFAULT_FISH_AUDIO_LLAMA_URL}/v1/audio/speech",
        f"{DEFAULT_FISH_AUDIO_LLAMA_URL}/health",
    )
    assert resolve_fish_audio_llama_endpoints("https://api.fish.audio") == (
        "http://127.0.0.1:9882/",
        "http://127.0.0.1:9882/v1/audio/speech",
        "http://127.0.0.1:9882/health",
    )
    assert resolve_fish_audio_llama_endpoints("http://127.0.0.1:9900/v1/audio/speech") == (
        "http://127.0.0.1:9900/",
        "http://127.0.0.1:9900/v1/audio/speech",
        "http://127.0.0.1:9900/health",
    )
    assert resolve_fish_audio_llama_endpoints("http://192.168.1.50:8080/v1") == (
        "http://192.168.1.50:8080/",
        "http://192.168.1.50:8080/v1/audio/speech",
        "http://192.168.1.50:8080/health",
    )


def test_discover_fish_audio_gguf_files_and_build_cmd(tmp_path: Path) -> None:
    assets = _seed_llama_assets(tmp_path)
    server, model, mmproj = discover_fish_audio_gguf_files(project_root=tmp_path)
    assert Path(server) == assets["server"].resolve()
    assert Path(model) == assets["backbone"].resolve()
    assert Path(mmproj) == assets["mmproj"].resolve()

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    alt_model = custom_dir / "s2-pro-BF16.gguf"
    alt_model.write_bytes(b"gguf-bf16")
    alt_mmproj = custom_dir / "mmproj-alt.gguf"
    alt_mmproj.write_bytes(b"gguf-mm")
    server2, model2, mmproj2 = discover_fish_audio_gguf_files(
        model_path=str(custom_dir),
        llama_server_path=str(assets["server"]),
        project_root=tmp_path,
    )
    assert Path(server2) == assets["server"].resolve()
    assert Path(model2) == alt_model.resolve()
    assert Path(mmproj2) == alt_mmproj.resolve()

    cmd = build_fish_audio_llama_server_cmd(
        llama_server=server,
        model_path=model,
        mmproj_path=mmproj,
        server_url="http://0.0.0.0:9882/",
        n_gpu_layers=48,
        ctx_size=2048,
        threads=8,
        extra_args="--flash-attn on",
    )
    assert cmd[:6] == [server, "-m", model, "--mmproj", mmproj, "--host"]
    assert cmd[cmd.index("--host") + 1] == "0.0.0.0"
    assert cmd[cmd.index("--port") + 1] == "9882"
    assert cmd[cmd.index("-ngl") + 1] == "48"
    assert cmd[cmd.index("--ctx-size") + 1] == "2048"
    assert cmd[cmd.index("-t") + 1] == "8"
    assert "--no-webui" in cmd
    assert cmd[-2:] == ["--flash-attn", "on"]


def test_llama_autostart_health_polling_and_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = _seed_llama_assets(tmp_path)
    health_calls = 0

    def fake_get(url: str, **_kwargs: Any) -> SimpleNamespace:
        nonlocal health_calls
        health_calls += 1
        assert url == "http://127.0.0.1:9882/health"
        if health_calls < 3:
            raise requests.ConnectionError("booting")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests.Session, "get", staticmethod(fake_get))

    spawned: list[tuple[list[str], dict[str, Any]]] = []
    events: list[object] = []

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = iter(["ggml_vulkan: initialized\n", "listening on 127.0.0.1:9882\n"])

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> None:
            events.append(("wait", timeout))

    def fake_popen(cmd: list[str], **kwargs: Any) -> _FakeProc:
        spawned.append((cmd, kwargs))
        return _FakeProc()

    monkeypatch.setattr("ai.tts.adapters.fish_audio_s2_pro.subprocess.Popen", fake_popen)

    adapter = FishAudioS2ProAdapter(
        backend="llama-cpp",
        base_url="https://api.fish.audio",
        project_root=tmp_path,
    )
    assert adapter.owns_server_process is True
    assert adapter._session.trust_env is False
    cmd, kwargs = spawned[0]
    assert cmd[0] == assets["server"].resolve().as_posix()
    assert str(assets["backbone"].resolve().as_posix()) in cmd
    assert str(assets["mmproj"].resolve().as_posix()) in cmd
    assert kwargs["cwd"] == str(assets["server"].resolve().parent)

    adapter.wait_until_ready(timeout_seconds=2.0, poll_interval_seconds=0.01)
    adapter.stop_server()
    assert events == ["terminate", ("wait", 5)]
    assert adapter.owns_server_process is False


def test_llama_missing_files_early_exit_and_remote_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        requests.Session,
        "get",
        staticmethod(lambda *_a, **_kw: (_ for _ in ()).throw(requests.ConnectionError("down"))),
    )

    with pytest.raises(FileNotFoundError, match="llama-server executable not found"):
        FishAudioS2ProAdapter(
            backend="llama-cpp",
            llama_server_path="",
            project_root=tmp_path,
        )

    assets = _seed_llama_assets(tmp_path, include_mmproj=False)
    with pytest.raises(FileNotFoundError, match="mmproj GGUF not found"):
        FishAudioS2ProAdapter(backend="llama-cpp", project_root=tmp_path)

    assets["backbone"].unlink()
    with pytest.raises(FileNotFoundError, match="GGUF backbone not found"):
        FishAudioS2ProAdapter(backend="llama-cpp", project_root=tmp_path)

    # Remote llama-server skips process launch and does not require a Fish cloud API key.
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    remote = FishAudioS2ProAdapter(backend="llama-cpp", base_url="http://192.168.1.50:9882")
    assert remote.owns_server_process is False
    remote.wait_until_ready(timeout_seconds=0.1)

    # Early exit surfaces captured stdout tail.
    assets_full = _seed_llama_assets(tmp_path / "early")

    class _DyingProc:
        stdout = iter(["Vulkan allocation failed\n"])

        def poll(self) -> int:
            return 3

    monkeypatch.setattr(
        "ai.tts.adapters.fish_audio_s2_pro.subprocess.Popen",
        lambda *_a, **_kw: _DyingProc(),
    )
    failing = FishAudioS2ProAdapter(
        backend="llama-cpp",
        base_url="http://127.0.0.1:9885",
        project_root=tmp_path / "early",
    )
    with pytest.raises(RuntimeError, match=r"code 3.*Vulkan allocation failed"):
        failing.wait_until_ready(timeout_seconds=0.5, poll_interval_seconds=0.01)


def test_llama_generate_speech_cloning_tags_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        requests.Session,
        "get",
        staticmethod(lambda *_a, **_kw: SimpleNamespace(status_code=200)),
    )
    adapter = FishAudioS2ProAdapter(
        backend="llama-cpp",
        base_url="http://127.0.0.1:9882",
        enable_inline_tags=True,
    )
    assert adapter.supports_inline_voice_tags is True

    posts: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        posts.append({"url": url, **kwargs})
        return SimpleNamespace(ok=True, status_code=200, content=b"RIFF" + (b"\x09" * 64), text="")

    monkeypatch.setattr(adapter._session, "post", fake_post)

    # Without reference audio, applies voice_instruct tag prefix.
    out_plain = tmp_path / "plain.wav"
    assert adapter.generate_speech(
        "Hello world",
        file_path=str(out_plain),
        voice_instruct="laugh",
    ) == str(out_plain.resolve())
    assert posts[-1]["url"] == "http://127.0.0.1:9882/v1/audio/speech"
    assert posts[-1]["json"] == {
        "input": "[laugh] Hello world",
        "response_format": "wav",
    }

    # With reference audio + prompt transcript, encodes base64 and speaker_ref_text.
    ref_wav = tmp_path / "ref.wav"
    ref_bytes = b"RIFF" + (b"\x07" * 48)
    ref_wav.write_bytes(ref_bytes)
    out_clone = tmp_path / "clone.wav"
    assert adapter.generate_speech(
        "[whisper] Nice to meet you",
        file_path=str(out_clone),
        ref_audio_path=str(ref_wav),
        prompt_text="Reference transcript",
        voice_instruct="ignored when already tagged",
    ) == str(out_clone.resolve())
    assert posts[-1]["json"] == {
        "input": "[whisper] Nice to meet you",
        "response_format": "wav",
        "speaker_ref_b64": base64.b64encode(ref_bytes).decode("ascii"),
        "speaker_ref_text": "Reference transcript",
    }

    # Missing ref audio returns None without making an HTTP call.
    prev_count = len(posts)
    assert adapter.generate_speech("Hi", ref_audio_path=str(tmp_path / "missing.wav")) is None
    assert len(posts) == prev_count

    # HTTP error and invalid WAV payload return None.
    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda *_a, **_kw: SimpleNamespace(ok=False, status_code=500, text="server error", json=lambda: {"message": "bad"}),
    )
    assert adapter.generate_speech("Hi", file_path=str(tmp_path / "err.wav")) is None

    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda *_a, **_kw: SimpleNamespace(ok=True, status_code=200, content=b"BAD", text=""),
    )
    assert adapter.generate_speech("Hi", file_path=str(tmp_path / "bad.wav")) is None

    disabled_tags = FishAudioS2ProAdapter(
        backend="llama-cpp",
        base_url="http://127.0.0.1:9882",
        enable_inline_tags=False,
    )
    assert disabled_tags.supports_inline_voice_tags is False


def _make_pcm16_wav(sr: int, samples: list[int], *, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _read_mono_wav(wav_bytes: bytes) -> tuple[int, int, list[int]]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
        return wf.getnchannels(), wf.getframerate(), samples


def _make_nan_buzz_wav() -> bytes:
    period = [((i * 7) % 3000) - 1500 for i in range(2048)]
    return _make_pcm16_wav(44100, period * 512, channels=1)


def test_sanitize_ref_wav_and_detect_nan_buzz() -> None:
    speech = [1200, -900, 0, 850, -1400, 0, 2200, -1800] * 800
    noisy_mono = _make_pcm16_wav(44100, ([0] * 5000) + speech, channels=1)
    sanitized_mono = sanitize_fish_audio_llama_ref_wav(noisy_mono)
    ch, sr, s_mono = _read_mono_wav(sanitized_mono)
    assert (ch, sr) == (1, 44100)
    assert abs(s_mono[0]) > 2
    assert len(s_mono) == len(speech)
    assert 0 not in s_mono

    stereo_samples = []
    for val in ([0] * 5000) + speech:
        stereo_samples.extend((val, val))
    noisy_stereo = _make_pcm16_wav(32000, stereo_samples, channels=2)
    sanitized_stereo = sanitize_fish_audio_llama_ref_wav(noisy_stereo)
    ch_s, sr_s, s_stereo = _read_mono_wav(sanitized_stereo)
    assert (ch_s, sr_s) == (1, 32000)
    assert abs(s_stereo[0]) > 2
    assert 0 not in s_stereo

    clean_mono = _make_pcm16_wav(22050, [900, -700, 1500, -1200] * 400, channels=1)
    assert sanitize_fish_audio_llama_ref_wav(clean_mono) == clean_mono

    dummy = b"RIFF" + (b"\x07" * 48)
    assert sanitize_fish_audio_llama_ref_wav(dummy) == dummy
    assert sanitize_fish_audio_llama_ref_wav(b"not-audio") == b"not-audio"

    assert is_fish_audio_llama_nan_buzz_wav(_make_nan_buzz_wav()) is True
    assert is_fish_audio_llama_nan_buzz_wav(clean_mono) is False
    real_long = _make_pcm16_wav(44100, [((i * 199) % 28000) - 14000 for i in range(512 * 2048)])
    assert is_fish_audio_llama_nan_buzz_wav(real_long) is False


def test_llama_ref_sanitization_and_poison_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_llama_assets(tmp_path)
    events: list[object] = []
    spawned: list[list[str]] = []

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = iter(["listening\n"])

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> None:
            events.append(("wait", timeout))

    monkeypatch.setattr(
        "ai.tts.adapters.fish_audio_s2_pro.subprocess.Popen",
        lambda cmd, **_kw: spawned.append(cmd) or _FakeProc(),
    )

    reach_count = 0

    def fake_get(_self: Any, url: str, **_kw: Any) -> SimpleNamespace:
        nonlocal reach_count
        reach_count += 1
        assert url == "http://127.0.0.1:9882/health"
        if reach_count == 1:
            raise requests.ConnectionError("not running yet")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    adapter = FishAudioS2ProAdapter(
        backend="llama-cpp",
        base_url="http://127.0.0.1:9882",
        project_root=tmp_path,
    )
    assert adapter.owns_server_process is True
    assert len(spawned) == 1

    session_closed = False
    orig_close = adapter._session.close

    def _spy_close() -> None:
        nonlocal session_closed
        session_closed = True
        orig_close()

    # 1) Ref WAV with leading zeros is sanitized before base64 encoding.
    ref_file = tmp_path / "leading_zero_ref.wav"
    ref_file.write_bytes(
        _make_pcm16_wav(44100, ([0] * 5000) + ([1500, -1400, 0, 1100] * 1500), channels=1)
    )
    posts: list[dict[str, Any]] = []
    valid_wav = _make_pcm16_wav(44100, [5000, -4000, 3000, -2000] * 500)
    buzz_wav = _make_nan_buzz_wav()
    responses = [
        SimpleNamespace(ok=True, status_code=200, content=valid_wav, text=""),
        SimpleNamespace(ok=True, status_code=200, content=buzz_wav, text=""),
        SimpleNamespace(ok=True, status_code=200, content=valid_wav, text=""),
    ]

    def fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        posts.append({"url": url, **kwargs})
        return responses.pop(0)

    monkeypatch.setattr(adapter._session, "post", fake_post)
    monkeypatch.setattr(adapter._session, "close", _spy_close)

    ok_out = tmp_path / "ok.wav"
    assert adapter.generate_speech("hello", file_path=str(ok_out), ref_audio_path=str(ref_file)) == str(
        ok_out.resolve()
    )
    sent_ref = base64.b64decode(posts[0]["json"]["speaker_ref_b64"])
    _ch, _sr, sent_samples = _read_mono_wav(sent_ref)
    assert abs(sent_samples[0]) > 2
    assert 0 not in sent_samples

    # 2) Poisoned 512-frame buzz triggers restart without saving the buzz file or closing session.
    poison_out = tmp_path / "poisoned.wav"
    assert adapter.generate_speech("broken", file_path=str(poison_out)) is None
    assert not poison_out.exists()
    assert events == ["terminate", ("wait", 5)]
    assert len(spawned) == 2
    assert session_closed is False
    assert adapter.owns_server_process is True

    # 3) Retry on restarted server succeeds.
    retry_out = tmp_path / "retry.wav"
    assert adapter.generate_speech("recovered", file_path=str(retry_out)) == str(retry_out.resolve())
    assert retry_out.read_bytes() == valid_wav
