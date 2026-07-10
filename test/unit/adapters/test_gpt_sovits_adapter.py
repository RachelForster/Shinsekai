from types import SimpleNamespace

import pytest
import requests

from tts.tts_adapter import GPTSoVitsAdapter, IndexTTSAdapter, KaggleGPTSoVitsAdapter


@pytest.mark.parametrize(
    ("adapter_class", "url_attr"),
    [(GPTSoVitsAdapter, "tts_server_url"), (IndexTTSAdapter, "index_server_url")],
)
def test_server_adapter_waits_until_health_probe_succeeds(monkeypatch, adapter_class, url_attr):
    adapter = object.__new__(adapter_class)
    setattr(adapter, url_attr, "http://127.0.0.1:9880/")
    adapter._server_process = None
    checks = iter([False, False, True])
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: next(checks))
    monkeypatch.setattr("tts.tts_adapter.time.sleep", lambda _seconds: None)

    adapter.wait_until_ready(timeout_seconds=1, poll_interval_seconds=0.01)


@pytest.mark.parametrize("adapter_class", [GPTSoVitsAdapter, IndexTTSAdapter])
def test_server_adapter_reports_child_exit_before_ready(monkeypatch, adapter_class):
    adapter = object.__new__(adapter_class)
    adapter._server_process = SimpleNamespace(poll=lambda: 17)
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: False)

    with pytest.raises(RuntimeError, match=r"exited before becoming ready \(code 17\)"):
        adapter.wait_until_ready(timeout_seconds=1, poll_interval_seconds=0.01)


@pytest.mark.parametrize("adapter_class", [GPTSoVitsAdapter, IndexTTSAdapter])
def test_server_adapter_reports_readiness_timeout(monkeypatch, adapter_class):
    adapter = object.__new__(adapter_class)
    adapter._server_process = None
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: False)

    with pytest.raises(TimeoutError, match="did not become ready within 0 seconds"):
        adapter.wait_until_ready(timeout_seconds=0, poll_interval_seconds=0.01)


def test_remote_gpt_sovits_url_does_not_auto_start_local_process(monkeypatch):
    popen_calls = []

    monkeypatch.setattr(
        "tts.tts_adapter.requests.Session.get",
        lambda self, *args, **kwargs: SimpleNamespace(status_code=404),
    )
    monkeypatch.setattr("tts.tts_adapter.subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    GPTSoVitsAdapter(
        tts_server_url="https://example.trycloudflare.com/",
        gpt_sovits_work_path="/tmp/not-a-gpt-sovits-bundle",
    )

    assert popen_calls == []


def test_local_unreachable_gpt_sovits_without_work_path_requires_startup_path(monkeypatch):
    popen_calls = []

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("tts.tts_adapter.requests.Session.get", raise_connection_error)
    monkeypatch.setattr("tts.tts_adapter.subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    with pytest.raises(RuntimeError, match="GPT-SoVITS startup path"):
        GPTSoVitsAdapter(tts_server_url="http://127.0.0.1:9880/", gpt_sovits_work_path="")

    assert popen_calls == []


def test_kaggle_gpt_sovits_skips_local_model_switch(monkeypatch):
    get_calls = []

    def fake_get(self, *args, **kwargs):
        get_calls.append((args, kwargs))
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr("tts.tts_adapter.requests.Session.get", fake_get)

    adapter = KaggleGPTSoVitsAdapter(
        tts_server_url="https://example.trycloudflare.com/",
        remote_ref_audio_path="/kaggle/working/ref.wav",
    )
    adapter.switch_model({
        "gpt_model_path": "/home/user/model.ckpt",
        "sovits_model_path": "/home/user/model.pth",
    })

    assert all("set_gpt_weights" not in call[0][0] for call in get_calls)
    assert all("set_sovits_weights" not in call[0][0] for call in get_calls)


def test_kaggle_gpt_sovits_uses_remote_reference_audio(monkeypatch, tmp_path):
    post_calls = []

    monkeypatch.setattr(
        "tts.tts_adapter.requests.Session.get",
        lambda self, *args, **kwargs: SimpleNamespace(status_code=200),
    )

    def fake_post(self, *args, **kwargs):
        post_calls.append((args, kwargs))
        return SimpleNamespace(ok=True, content=b"RIFFtest", status_code=200, text="")

    monkeypatch.setattr("tts.tts_adapter.requests.Session.post", fake_post)

    adapter = KaggleGPTSoVitsAdapter(
        tts_server_url="https://example.trycloudflare.com/",
        remote_ref_audio_path="/kaggle/working/ref.wav",
    )
    out = tmp_path / "out.wav"
    result = adapter.generate_speech(
        "hello",
        file_path=str(out),
        ref_audio_path="/home/user/ref.wav",
        prompt_text="ref text",
        prompt_lang="ja",
        text_lang="ja",
    )

    assert result == str(out.resolve())
    assert post_calls[0][1]["json"]["ref_audio_path"] == "/kaggle/working/ref.wav"
    assert post_calls[0][1]["json"]["text_split_method"] == "cut5"
    assert post_calls[0][1]["json"]["batch_size"] == 4
    assert post_calls[0][1]["json"]["speed_factor"] == 1.0
    assert post_calls[0][1]["json"]["parallel_infer"] is True
    assert post_calls[0][1]["json"]["split_bucket"] is True
