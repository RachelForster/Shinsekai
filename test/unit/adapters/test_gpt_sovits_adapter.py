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


@pytest.mark.parametrize("adapter_class", [GPTSoVitsAdapter, IndexTTSAdapter])
def test_server_adapter_allows_ten_minutes_for_cold_start(adapter_class):
    assert adapter_class.STARTUP_TIMEOUT_SECONDS == 600.0


@pytest.mark.parametrize(
    ("adapter_class", "url_kwarg"),
    [(GPTSoVitsAdapter, "tts_server_url"), (IndexTTSAdapter, "index_server_url")],
)
def test_local_server_adapter_disables_environment_proxies(monkeypatch, adapter_class, url_kwarg):
    monkeypatch.setattr(adapter_class, "_start_server_process", lambda self: None)

    adapter = adapter_class(**{url_kwarg: "http://127.0.0.1:9880/"})

    try:
        assert adapter._session.trust_env is False
    finally:
        adapter.stop_server()


@pytest.mark.parametrize(
    ("adapter_class", "url_kwarg"),
    [(GPTSoVitsAdapter, "tts_server_url"), (IndexTTSAdapter, "index_server_url")],
)
def test_remote_server_adapter_keeps_environment_proxy_support(monkeypatch, adapter_class, url_kwarg):
    monkeypatch.setattr(adapter_class, "_start_server_process", lambda self: None)

    adapter = adapter_class(**{url_kwarg: "https://tts.example.com/"})

    try:
        assert adapter._session.trust_env is True
    finally:
        adapter.stop_server()


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


def test_remote_index_tts_url_does_not_auto_start_local_process(monkeypatch):
    popen_calls = []

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("tts.tts_adapter.requests.Session.get", raise_connection_error)
    monkeypatch.setattr(
        "tts.tts_adapter.subprocess.Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    IndexTTSAdapter(
        index_server_url="https://tts.example.com/",
        index_server_work_path="/tmp/not-an-index-tts-bundle",
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


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        return SimpleNamespace(ok=True)


_SWITCH_MODEL_INFO = {
    "gpt_model_path": "/models/new_gpt.ckpt",
    "sovits_model_path": "/models/new_sovits.pth",
}


def _switch_model_adapter(session, server_process=None):
    adapter = object.__new__(GPTSoVitsAdapter)
    adapter.tts_server_url = "http://127.0.0.1:9880/"
    adapter.gpt_model_path = "old.ckpt"
    adapter.sovits_model_path = "old.pth"
    adapter._session = session
    adapter._server_process = server_process
    return adapter


def test_switch_model_switches_weights_after_server_recovers(monkeypatch):
    session = _RecordingSession()
    adapter = _switch_model_adapter(session)
    checks = iter([False, False, True])
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: next(checks))
    monkeypatch.setattr("tts.tts_adapter.time.sleep", lambda _seconds: None)

    adapter.switch_model(_SWITCH_MODEL_INFO)

    # A transient startup race must retry, then switch both weights once ready.
    assert any("set_gpt_weights" in url for url in session.calls)
    assert any("set_sovits_weights" in url for url in session.calls)
    assert adapter.gpt_model_path == "/models/new_gpt.ckpt"
    assert adapter.sovits_model_path == "/models/new_sovits.pth"


def test_switch_model_aborts_without_weight_calls_on_timeout(monkeypatch):
    session = _RecordingSession()
    adapter = _switch_model_adapter(session, server_process=None)
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: False)
    # switch_model hard-codes a 10s readiness timeout; drive a fake clock so the
    # test exercises the timeout path without waiting in real time.
    clock = {"t": 0.0}

    def fake_sleep(seconds):
        clock["t"] += max(float(seconds), 0.5)

    monkeypatch.setattr("tts.tts_adapter.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("tts.tts_adapter.time.sleep", fake_sleep)

    with pytest.raises(TimeoutError):
        adapter.switch_model(_SWITCH_MODEL_INFO)

    # Never poke the weight endpoints while the server is unreachable.
    assert session.calls == []
    assert adapter.gpt_model_path == "old.ckpt"
    assert adapter.sovits_model_path == "old.pth"


def test_switch_model_aborts_without_weight_calls_when_server_exits(monkeypatch):
    session = _RecordingSession()
    adapter = _switch_model_adapter(session, server_process=SimpleNamespace(poll=lambda: 17))
    monkeypatch.setattr(adapter, "_server_is_reachable", lambda: False)
    monkeypatch.setattr("tts.tts_adapter.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match=r"exited before becoming ready \(code 17\)"):
        adapter.switch_model(_SWITCH_MODEL_INFO)

    assert session.calls == []
    assert adapter.gpt_model_path == "old.ckpt"
    assert adapter.sovits_model_path == "old.pth"
