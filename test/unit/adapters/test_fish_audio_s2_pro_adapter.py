"""Unit tests for FishAudioS2ProAdapter and Fish Audio protocol helpers."""

from __future__ import annotations

import json
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from ai.tts.adapters.fish_audio_protocol import (
    DEFAULT_FISH_AUDIO_URL,
    build_fish_speech_server_cmd,
    pack_msgpack,
    parse_character_reference_ids,
    resolve_fish_audio_endpoints,
    resolve_local_fish_speech_launch,
)
from ai.tts.adapters.fish_audio_s2_pro import FishAudioS2ProAdapter
from ai.tts.tts_manager import TTSManager


def _decode_msgpack(buf: bytes) -> Any:
    """Minimal spec-compliant MessagePack decoder used purely for wire verification."""
    offset = 0

    def read(n: int) -> bytes:
        nonlocal offset
        chunk = buf[offset : offset + n]
        assert len(chunk) == n
        offset += n
        return chunk

    def read_item() -> Any:
        tag = read(1)[0]
        if tag <= 0x7F:
            return tag
        if tag >= 0xE0:
            return tag - 0x100
        if 0x80 <= tag <= 0x8F:
            return {read_item(): read_item() for _ in range(tag & 0x0F)}
        if 0x90 <= tag <= 0x9F:
            return [read_item() for _ in range(tag & 0x0F)]
        if 0xA0 <= tag <= 0xBF:
            return read(tag & 0x1F).decode("utf-8")
        if tag == 0xC0:
            return None
        if tag == 0xC2:
            return False
        if tag == 0xC3:
            return True
        if tag in (0xC4, 0xC5, 0xC6):
            fmt = {0xC4: ">B", 0xC5: ">H", 0xC6: ">I"}[tag]
            size = struct.unpack(fmt, read(struct.calcsize(fmt)))[0]
            return read(size)
        if tag == 0xCB:
            return struct.unpack(">d", read(8))[0]
        if tag in (0xCC, 0xCD, 0xCE, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3):
            fmt = {
                0xCC: ">B",
                0xCD: ">H",
                0xCE: ">I",
                0xCF: ">Q",
                0xD0: ">b",
                0xD1: ">h",
                0xD2: ">i",
                0xD3: ">q",
            }[tag]
            return struct.unpack(fmt, read(struct.calcsize(fmt)))[0]
        if tag in (0xD9, 0xDA, 0xDB):
            fmt = {0xD9: ">B", 0xDA: ">H", 0xDB: ">I"}[tag]
            size = struct.unpack(fmt, read(struct.calcsize(fmt)))[0]
            return read(size).decode("utf-8")
        if tag in (0xDC, 0xDD):
            fmt = ">H" if tag == 0xDC else ">I"
            count = struct.unpack(fmt, read(struct.calcsize(fmt)))[0]
            return [read_item() for _ in range(count)]
        if tag in (0xDE, 0xDF):
            fmt = ">H" if tag == 0xDE else ">I"
            count = struct.unpack(fmt, read(struct.calcsize(fmt)))[0]
            return {read_item(): read_item() for _ in range(count)}
        raise AssertionError(f"Unexpected MessagePack tag: 0x{tag:02x}")

    result = read_item()
    assert offset == len(buf)
    return result


def test_pack_msgpack_roundtrip_all_supported_types() -> None:
    payload = {
        "none": None,
        "flag_t": True,
        "flag_f": False,
        "ints": [0, 42, -1, -32, -33, -32768, 255, 65535, 100000, -(1 << 40), 1 << 40],
        "float": 0.75,
        "text": "你好 S2-Pro! " + ("x" * 40),
        "small_bin": b"RIFF1234",
        "large_bin": b"\xAB" * 70000,
    }
    encoded = pack_msgpack(payload)
    assert _decode_msgpack(encoded) == payload
    with pytest.raises(TypeError, match="Unsupported type"):
        pack_msgpack({"bad": {1, 2, 3}})


def test_resolve_endpoints_and_character_reference_id_parsers() -> None:
    assert resolve_fish_audio_endpoints("") == (
        "https://api.fish.audio/",
        "https://api.fish.audio/v1/tts",
        "https://api.fish.audio/v1/health",
    )
    assert resolve_fish_audio_endpoints("https://api.fish.audio/v1/tts/") == (
        "https://api.fish.audio/",
        "https://api.fish.audio/v1/tts",
        "https://api.fish.audio/v1/health",
    )
    assert resolve_fish_audio_endpoints("http://127.0.0.1:8080/v1") == (
        "http://127.0.0.1:8080/",
        "http://127.0.0.1:8080/v1/tts",
        "http://127.0.0.1:8080/v1/health",
    )

    assert parse_character_reference_ids('{"Nanami": "ref_001", "Empty": " "}') == {
        "Nanami": "ref_001"
    }
    assert parse_character_reference_ids("Nanami=ref_1\nHajime: ref_2, InvalidEntry; Koma=ref_3") == {
        "Nanami": "ref_1",
        "Hajime": "ref_2",
        "Koma": "ref_3",
    }
    assert parse_character_reference_ids("{bad json") == {}


def test_cloud_api_json_synthesis_with_reference_id_and_schema(tmp_path, monkeypatch) -> None:
    schema = FishAudioS2ProAdapter.get_config_schema()
    assert schema["base_url"]["default"] == DEFAULT_FISH_AUDIO_URL
    assert schema["fish_speech_dir"]["default"] == ""
    assert schema["api_key"]["secret"] is True
    assert schema["model"]["default"] == "s2-pro"
    assert schema["latency"]["choices"] == ["normal", "balanced"]

    adapter = FishAudioS2ProAdapter(
        base_url=DEFAULT_FISH_AUDIO_URL,
        tts_server_url="http://127.0.0.1:9880",
        gpt_sovits_work_path="/legacy/gsv",
        api_key="sk-fish-test",
        reference_id="voice-default",
        temperature=0.8,
        top_p=0.9,
        chunk_length=250,
    )
    assert adapter.work_path is None
    assert adapter.owns_server_process is False
    assert adapter._session.trust_env is True
    adapter.wait_until_ready()

    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return SimpleNamespace(ok=True, status_code=200, content=b"RIFF" + (b"\x01" * 64), text="")

    monkeypatch.setattr(adapter._session, "post", fake_post)
    out_wav = tmp_path / "cloud.wav"
    result = adapter.generate_speech("你好，世界", file_path=str(out_wav), speed_factor=1.15)

    assert result == str(out_wav.resolve())
    assert out_wav.read_bytes().startswith(b"RIFF")
    assert captured["url"] == "https://api.fish.audio/v1/tts"
    headers = captured["kwargs"]["headers"]
    assert headers["Authorization"] == "Bearer sk-fish-test"
    assert headers["model"] == "s2-pro"
    assert headers["Content-Type"] == "application/json"
    body = captured["kwargs"]["json"]
    assert body["text"] == "你好，世界"
    assert body["reference_id"] == "voice-default"
    assert body["format"] == "wav"
    assert body["chunk_length"] == 250
    assert body["temperature"] == 0.8
    assert body["top_p"] == 0.9
    assert body["prosody"] == {"speed": 1.15}


def test_inline_zero_shot_msgpack_and_character_switching(tmp_path, monkeypatch) -> None:
    ref_wav = tmp_path / "nanami_ref.wav"
    ref_bytes = b"RIFF" + (b"\x02" * 64)
    ref_wav.write_bytes(ref_bytes)

    adapter = FishAudioS2ProAdapter(
        api_key="sk-fish-test",
        character_reference_ids="Kaede=ref_kaede",
    )
    posts: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        posts.append({"url": url, **kwargs})
        return SimpleNamespace(ok=True, status_code=200, content=b"RIFF" + (b"\x03" * 64), text="")

    monkeypatch.setattr(adapter._session, "post", fake_post)

    # Mapped character uses reference_id + JSON.
    adapter.switch_model({"character_name": "Kaede"})
    assert adapter.generate_speech("Line 1", file_path=str(tmp_path / "a.wav"), speed_factor=1.0)
    assert posts[-1]["headers"]["Content-Type"] == "application/json"
    assert posts[-1]["json"]["reference_id"] == "ref_kaede"
    assert "prosody" not in posts[-1]["json"]

    # Unmapped character clears override and falls back to inline msgpack zero-shot cloning.
    adapter.switch_model({"character_name": "Nanami", "model": "s2.1-pro"})
    out_msgpack = tmp_path / "b.wav"
    assert adapter.generate_speech(
        "Line 2",
        file_path=str(out_msgpack),
        ref_audio_path=str(ref_wav),
        prompt_text="Reference transcript",
    )
    assert posts[-1]["headers"]["Content-Type"] == "application/msgpack"
    assert posts[-1]["headers"]["model"] == "s2.1-pro"
    decoded = _decode_msgpack(posts[-1]["data"])
    assert decoded["text"] == "Line 2"
    assert decoded["references"] == [{"audio": ref_bytes, "text": "Reference transcript"}]
    assert "reference_id" not in decoded


def test_tts_manager_synthesis_without_reference_audio(tmp_path, monkeypatch) -> None:
    adapter = FishAudioS2ProAdapter(api_key="sk-fish-test")
    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda *_a, **_kw: SimpleNamespace(
            ok=True, status_code=200, content=b"RIFF" + (b"\x04" * 64), text=""
        ),
    )
    manager = TTSManager(audio_cache_dir=tmp_path / "audio_cache")
    manager.set_tts_adapter(adapter)
    try:
        generated = manager.generate_tts("Free-form speech test")
        assert generated
        assert Path(generated).read_bytes().startswith(b"RIFF")
    finally:
        manager.shutdown(stop_server=False)


def test_cloud_error_paths_and_invalid_responses(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    no_key = FishAudioS2ProAdapter(api_key="")
    with pytest.raises(ValueError, match="Fish Audio API key is required"):
        no_key.wait_until_ready()
    assert no_key.generate_speech("hello") is None

    adapter = FishAudioS2ProAdapter(api_key="sk-fish-test")
    assert adapter.generate_speech("   ") is None
    assert adapter.generate_speech("hi", ref_audio_path=str(tmp_path / "missing.wav")) is None

    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda *_a, **_kw: SimpleNamespace(
            ok=False,
            status_code=401,
            json=lambda: {"message": "Unauthorized"},
            text="Unauthorized",
        ),
    )
    assert adapter.generate_speech("hi", file_path=str(tmp_path / "fail.wav")) is None

    monkeypatch.setattr(
        adapter._session,
        "post",
        lambda *_a, **_kw: SimpleNamespace(ok=True, status_code=200, content=b"NOT_WAV", text=""),
    )
    assert adapter.generate_speech("hi", file_path=str(tmp_path / "badwav.wav")) is None


def test_local_fish_speech_autostart_wait_and_stop(tmp_path, monkeypatch) -> None:
    fish_dir = tmp_path / "fish-speech"
    api_script = fish_dir / "tools" / "api_server.py"
    api_script.parent.mkdir(parents=True)
    api_script.write_text("# stub server", encoding="utf-8")
    ckpt_dir = fish_dir / "checkpoints" / "s2-pro"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "config.json").write_text("{}", encoding="utf-8")
    codec_path = ckpt_dir / "codec.pth"
    codec_path.write_bytes(b"codec")

    health_calls = 0

    def fake_get(url: str, **_kwargs: Any) -> SimpleNamespace:
        nonlocal health_calls
        health_calls += 1
        assert url == "http://127.0.0.1:8080/v1/health"
        if health_calls < 3:
            raise requests.ConnectionError("starting")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests.Session, "get", staticmethod(fake_get))

    spawned: list[tuple[list[str], dict[str, Any]]] = []
    events: list[str] = []

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = iter(["Loading S2 Pro...\n", "Listening on 127.0.0.1:8080\n"])

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: int | None = None) -> None:
            events.append(f"wait:{timeout}")

    def fake_popen(cmd: list[str], **kwargs: Any) -> _FakeProc:
        spawned.append((cmd, kwargs))
        return _FakeProc()

    monkeypatch.setattr("ai.tts.adapters.fish_audio_s2_pro.subprocess.Popen", fake_popen)

    adapter = FishAudioS2ProAdapter(
        base_url="http://127.0.0.1:8080",
        fish_speech_dir=str(fish_dir),
        tts_server_url="http://127.0.0.1:9880",
        gpt_sovits_work_path="/legacy/gsv",
        project_root=tmp_path,
    )
    assert adapter.owns_server_process is True
    assert adapter._session.trust_env is False
    cmd, kwargs = spawned[0]
    assert str(api_script.resolve()) in cmd
    assert "--listen" in cmd and "127.0.0.1:8080" in cmd
    assert "--llama-checkpoint-path" in cmd and str(ckpt_dir.resolve()) in cmd
    assert "--decoder-checkpoint-path" in cmd and str(codec_path.resolve()) in cmd
    assert kwargs["cwd"] == str(fish_dir.resolve())

    adapter.wait_until_ready(timeout_seconds=2.0, poll_interval_seconds=0.01)
    adapter.stop_server()
    assert events == ["terminate", "wait:5.0"]
    assert adapter.owns_server_process is False


def test_local_server_already_running_and_missing_path_errors(tmp_path, monkeypatch) -> None:
    # Already running local server skips Popen.
    monkeypatch.setattr(
        requests.Session,
        "get",
        staticmethod(lambda *_a, **_kw: SimpleNamespace(status_code=200)),
    )
    existing = FishAudioS2ProAdapter(base_url="http://127.0.0.1:8080")
    assert existing.owns_server_process is False
    existing.wait_until_ready(timeout_seconds=0.1)

    # Unreachable local server without fish_speech_dir or project default raises RuntimeError.
    monkeypatch.setattr(
        requests.Session,
        "get",
        staticmethod(lambda *_a, **_kw: (_ for _ in ()).throw(requests.ConnectionError("down"))),
    )
    with pytest.raises(RuntimeError, match="tools/api_server.py"):
        FishAudioS2ProAdapter(
            base_url="http://127.0.0.1:8080",
            fish_speech_dir="",
            project_root=tmp_path,
        )

    # Early exit includes captured stdout tail.
    fish_dir = tmp_path / "fish-early-exit"
    (fish_dir / "tools").mkdir(parents=True)
    (fish_dir / "tools" / "api_server.py").write_text("# stub", encoding="utf-8")
    (fish_dir / "checkpoints" / "s2-pro").mkdir(parents=True)
    (fish_dir / "checkpoints" / "s2-pro" / "config.json").write_text("{}", encoding="utf-8")

    class _DyingProc:
        stdout = iter(["CUDA OOM during load\n"])

        def poll(self) -> int:
            return 2

    monkeypatch.setattr(
        "ai.tts.adapters.fish_audio_s2_pro.subprocess.Popen",
        lambda *_a, **_kw: _DyingProc(),
    )
    failing = FishAudioS2ProAdapter(
        base_url="http://127.0.0.1:8080",
        fish_speech_dir=str(fish_dir),
        project_root=tmp_path,
    )
    with pytest.raises(RuntimeError, match=r"code 2.*CUDA OOM"):
        failing.wait_until_ready(timeout_seconds=0.5, poll_interval_seconds=0.01)


def test_missing_weights_raises_ipv6_listen_and_schema_i18n_keys(tmp_path) -> None:
    fish_dir = tmp_path / "fish-empty-weights"
    (fish_dir / "tools").mkdir(parents=True)
    api_script = fish_dir / "tools" / "api_server.py"
    api_script.write_text("# stub", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Fish Audio S2 Pro weights not found"):
        resolve_local_fish_speech_launch(
            work_path=str(fish_dir),
            llama_checkpoint_path="",
            decoder_checkpoint_path="",
            python_path="",
            project_root=tmp_path,
        )

    cmd = build_fish_speech_server_cmd(
        python_exe="python",
        api_script=api_script,
        server_url="http://[::1]:8085",
        llama_ckpt=tmp_path / "ckpt",
        decoder_ckpt=None,
        decoder_config_name="modded_dac_vq",
    )
    listen_idx = cmd.index("--listen")
    assert cmd[listen_idx + 1] == "[::1]:8085"

    schema = FishAudioS2ProAdapter.get_config_schema()
    assert len(schema) == 17
    for field_name, meta in schema.items():
        assert str(meta.get("labelKey") or "").startswith("ops.api.tts.fishAudio.extra."), field_name
