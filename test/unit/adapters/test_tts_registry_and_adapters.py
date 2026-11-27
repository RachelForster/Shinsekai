"""Unit tests for split TTS adapters and TTS AdapterRegistry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.tts.adapters import (
    CosyVoiceAdapter,
    GenieTTSAdapter,
    GPTSoVitsAdapter,
    IndexTTSAdapter,
    KaggleGPTSoVitsAdapter,
    LocalHttpTTSAdapter,
    Qwen3TTSLlamaAdapter,
)
from ai.tts.registry import (
    configure_registered_tts_adapters,
    create_tts_adapter,
    create_tts_adapter_registry,
    get_tts_adapter_registry,
)
from ai.tts.tts_manager import TTSAdapterFactory
from test.mocks import MockTTSAdapter


def test_isolated_tts_registry_builtins_and_cleanup_on_wait_failure() -> None:
    isolated = create_tts_adapter_registry(include_builtins=True)
    assert isolated.keys() == (
        "genie-tts",
        "kaggle-gpt-sovits",
        "gpt-sovits",
        "qwen3-tts-gguf",
        "index-tts",
        "cosyvoice",
    )
    assert isolated.get("gpt-sovits") is GPTSoVitsAdapter
    assert isolated.get("kaggle-gpt-sovits") is KaggleGPTSoVitsAdapter
    assert isolated.get("genie-tts") is GenieTTSAdapter
    assert isolated.get("qwen3-tts-gguf") is Qwen3TTSLlamaAdapter
    assert isolated.get("index-tts") is IndexTTSAdapter
    assert isolated.get("cosyvoice") is CosyVoiceAdapter

    stopped: list[str] = []

    class _FailingReady(MockTTSAdapter):
        def wait_until_ready(self, timeout_seconds=None) -> None:
            raise RuntimeError("boom")

        def stop_server(self) -> None:
            stopped.append("stopped")

    custom_reg = create_tts_adapter_registry(include_builtins=False)
    custom_reg.register("failing", _FailingReady)
    with pytest.raises(RuntimeError, match="boom"):
        create_tts_adapter("failing", wait_until_ready=True, registry=custom_reg)
    assert stopped == ["stopped"]
    assert "failing" not in get_tts_adapter_registry()


def test_local_http_tts_base_and_genie_tts_loopback_session_and_wav(
    monkeypatch, tmp_path
) -> None:
    events: list[str] = []

    class _FakeProc:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout=None) -> None:
            events.append(f"wait:{timeout}")

        def kill(self) -> None:
            events.append("kill")

    class _MinimalLocal(LocalHttpTTSAdapter):
        def generate_speech(self, text, file_path=None, **kwargs):
            return None

        def switch_model(self, model_info):
            return None

    minimal = _MinimalLocal()
    minimal._init_http_runtime("http://127.0.0.1:9880")
    assert minimal._session.trust_env is False
    minimal._server_process = _FakeProc()
    minimal.stop_server()
    assert events == ["terminate", "wait:5"]

    monkeypatch.setattr(GenieTTSAdapter, "_start_server_process", lambda self: None)
    genie = GenieTTSAdapter(tts_server_url="http://127.0.0.1:9880/")
    try:
        assert genie._session.trust_env is False

        onnx_dir = tmp_path / "onnx"
        onnx_dir.mkdir(parents=True, exist_ok=True)
        (onnx_dir / "model.onnx").write_bytes(b"onnx")

        post_calls: list[str] = []

        class _StreamResponse:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = chunks

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size=4096):
                return iter(self._chunks)

        def fake_post(url, **kwargs):
            post_calls.append(url)
            if url.endswith("load_character"):
                return SimpleNamespace(raise_for_status=lambda: None)
            return _StreamResponse([b"\x01\x00" * 160])

        monkeypatch.setattr(genie._session, "post", fake_post)
        genie.switch_model(
            {
                "character_name": "Mika",
                "onnx_model_dir": str(onnx_dir),
            }
        )
        assert genie.character_name == "Mika"

        out_wav = tmp_path / "genie.wav"
        result = genie.generate_speech("hello", file_path=str(out_wav))
        assert result == str(out_wav.resolve())
        assert out_wav.read_bytes().startswith(b"RIFF")
        assert post_calls == [
            "http://127.0.0.1:9880/load_character",
            "http://127.0.0.1:9880/tts",
        ]
    finally:
        genie.stop_server()


def test_cosyvoice_and_plugin_tts_registration_lifecycle(monkeypatch, tmp_path) -> None:
    adapter = CosyVoiceAdapter(api_key="sk-cosy")
    adapter.switch_model({"voice": "v2", "model": "cosy-next"})
    assert adapter.current_voice == "v2"
    assert adapter.current_model == "cosy-next"

    monkeypatch.setattr(
        "ai.tts.adapters.cosyvoice.requests.post",
        lambda *_a, **_kw: SimpleNamespace(
            content=b"RIFFaudio", raise_for_status=lambda: None
        ),
    )
    out = tmp_path / "cosy.wav"
    assert adapter.generate_speech("hi", file_path=str(out)) == str(out.resolve())
    assert out.read_bytes() == b"RIFFaudio"

    try:
        configure_registered_tts_adapters({"plugin-tts": MockTTSAdapter})
        assert "plugin-tts" in TTSAdapterFactory._adapters
        assert isinstance(TTSAdapterFactory.create_adapter("PLUGIN-TTS"), MockTTSAdapter)
    finally:
        configure_registered_tts_adapters({})

    assert "plugin-tts" not in TTSAdapterFactory._adapters
