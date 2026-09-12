import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.tts.model_session import tts_model_session
from application.reminders.presentation import ReminderPresenter, _text_response


@pytest.fixture
def presenter(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai.tts.model_session.tempfile.gettempdir", lambda: str(tmp_path)
    )
    character = SimpleNamespace(
        name="澪",
        character_setting="嘴硬但关心用户，喜欢用反问句。",
        character_brief="可靠的朋友",
        gpt_model_path="voice.ckpt",
        sovits_model_path="voice.pth",
        refer_audio_path="reference.wav",
        prompt_text="参考台词",
        prompt_lang="zh",
        speech_speed=1.1,
        speech_volume=0.7,
    )
    config = SimpleNamespace(
        config=SimpleNamespace(
            system_config=SimpleNamespace(ui_language="zh_CN", voice_language="ja")
        ),
        get_character_by_name=lambda name: (
            character if name == character.name else None
        ),
        get_gpt_sovits_config=lambda: ("http://tts/", "tts", "gpt-sovits"),
        merged_tts_factory_kwargs=lambda provider, kwargs: kwargs,
    )
    return ReminderPresenter(config, tmp_path)


def reminder(**kwargs):
    return (
        dict(
            character_name="澪",
            title="喝水",
            message="该喝 200 ml 水了。",
            due_at="2026-09-12T23:00:00+08:00",
        )
        | kwargs
    )


def test_generates_personality_dialogue_and_same_meaning_voice_language(presenter):
    presenter._complete = Mock(
        return_value=json.dumps(
            {"message": "还不喝那 200 ml 水？", "speech": "水を200 ml飲まないの？"}
        )
    )
    result = presenter.render(reminder())
    assert result == {
        "message": "还不喝那 200 ml 水？",
        "speech": "水を200 ml飲まないの？",
        "speech_language": "ja",
    }
    system, user = presenter._complete.call_args.args[0]
    context = json.loads(user["content"])
    assert context["character_setting"] == "嘴硬但关心用户，喜欢用反问句。"
    assert context["message"] == reminder()["message"]
    assert context["due_at"] == reminder()["due_at"]
    assert context["display_language"] == "zh_CN"
    assert context["voice_language"] == "ja"
    assert "do not invent facts" in system["content"]


@pytest.mark.parametrize(
    "output",
    [
        "invalid",
        "[]",
        '{"message":"hi"}',
        '{"message":"","speech":"hi"}',
        json.dumps({"message": "x" * 401, "speech": "hi"}),
    ],
)
def test_invalid_generation_keeps_original_reminder(presenter, output):
    presenter._complete = Mock(return_value=output)
    assert presenter.render(reminder()) == {
        "message": reminder()["message"],
        "speech": reminder()["message"],
        "speech_language": "zh",
    }


def test_unavailable_or_busy_llm_does_not_lose_reminder(presenter):
    presenter._complete = Mock(side_effect=TimeoutError("slow model"))
    assert presenter.render(reminder())["message"] == reminder()["message"]
    presenter._complete.reset_mock()
    with presenter._slots:
        assert presenter.render(reminder())["message"] == reminder()["message"]
    presenter.render(reminder(character_name="removed character"))
    presenter._complete.assert_not_called()


def test_speech_uses_character_voice_and_unique_replay_files(presenter, monkeypatch):
    adapter = Mock()

    def generate(**kwargs):
        Path(kwargs["file_path"]).write_bytes(b"RIFF-test-audio")
        return kwargs["file_path"]

    adapter.generate_speech.side_effect = generate
    factory = Mock(return_value=adapter)
    monkeypatch.setattr("ai.tts.tts_manager.TTSAdapterFactory.create_adapter", factory)
    payload = {
        "character_name": "澪",
        "speech": "水を飲んで。",
        "speech_language": "ja",
    }
    first, second = presenter.speech(payload), presenter.speech(payload)
    assert first["audio_path"] != second["audio_path"]
    assert Path(first["audio_path"]).read_bytes() == b"RIFF-test-audio"
    assert first["audio_volume"] == 0.7
    factory.assert_called_once()
    project = presenter.audio_dir.parent.parent
    adapter.switch_model.assert_called_with(
        {
            "character_name": "澪",
            "gpt_model_path": (project / "voice.ckpt").as_posix(),
            "sovits_model_path": (project / "voice.pth").as_posix(),
        }
    )
    args = adapter.generate_speech.call_args.kwargs
    assert args["text"] == payload["speech"]
    assert args["text_lang"] == "ja"
    assert args["ref_audio_path"] == (project / "reference.wav").as_posix()
    assert args["prompt_text"] == "参考台词"
    assert args["speed_factor"] == 1.1
    adapter.wait_until_ready.assert_called_with(timeout_seconds=30)
    presenter.close()
    adapter.stop_server.assert_called_once()


def test_failed_tts_removes_partial_file_and_allows_next_attempt(
    presenter, monkeypatch
):
    adapter = Mock()

    def generate(**kwargs):
        Path(kwargs["file_path"]).write_bytes(b"partial")
        raise TimeoutError("tts timeout")

    adapter.generate_speech.side_effect = generate
    monkeypatch.setattr(
        "ai.tts.tts_manager.TTSAdapterFactory.create_adapter",
        Mock(return_value=adapter),
    )
    payload = {"character_name": "澪", "speech": "你好", "speech_language": "zh"}
    assert presenter.speech(payload) == {"audio_path": None}
    assert list(presenter.audio_dir.glob("*.wav")) == []
    assert presenter.speech(payload) == {"audio_path": None}
    assert adapter.generate_speech.call_count == 2


def test_remote_voice_paths_are_preserved(presenter):
    assert (
        presenter._voice_path("/kaggle/working/reference.wav")
        == "/kaggle/working/reference.wav"
    )
    assert presenter._voice_path(None) == ""


def test_disabled_voice_and_missing_character_are_text_only(presenter):
    presenter.config.get_gpt_sovits_config = lambda: ("", "", "none")
    assert presenter.speech(
        {"character_name": "澪", "speech": "你好", "speech_language": "zh"}
    ) == {"audio_path": None}
    assert presenter.speech(
        {"character_name": "unknown", "speech": "你好", "speech_language": "zh"}
    ) == {"audio_path": None}


@pytest.mark.parametrize(
    "payload", [None, {}, reminder(message=""), reminder(character_name="x" * 121)]
)
def test_invalid_presentation_request_is_rejected(presenter, payload):
    with pytest.raises(ValueError):
        presenter.render(payload)


def test_model_owner_handoff_invalidates_cached_server_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai.tts.model_session.tempfile.gettempdir", lambda: str(tmp_path)
    )
    first = SimpleNamespace(gpt_model_path="old", sovits_model_path="old")
    second = SimpleNamespace(gpt_model_path="second", sovits_model_path="second")
    with tts_model_session(first, "http://tts/"):
        assert first.gpt_model_path is None
        first.gpt_model_path = "first.ckpt"
    with tts_model_session(first, "http://tts"):
        assert first.gpt_model_path == "first.ckpt"
    with tts_model_session(second, "http://tts"):
        assert second.gpt_model_path is None
    with tts_model_session(first, "http://tts"):
        assert first.gpt_model_path is None


def test_other_adapter_cannot_switch_models_during_synthesis(tmp_path, monkeypatch):
    from filelock import Timeout

    monkeypatch.setattr(
        "ai.tts.model_session.tempfile.gettempdir", lambda: str(tmp_path)
    )
    first, second = SimpleNamespace(), SimpleNamespace()
    with tts_model_session(first, "http://tts"):
        with pytest.raises(Timeout):
            with tts_model_session(second, "http://tts", timeout=0):
                pytest.fail("Concurrent model switch was allowed")


def test_llm_request_uses_current_provider_without_tools_and_bounds_wait(
    presenter, monkeypatch
):
    adapter = Mock()
    client = adapter.client
    client.with_options.return_value = client
    adapter.chat.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"message":"你好","speech":"こんにちは"}'
                )
            )
        ]
    )
    factory = Mock(return_value=adapter)
    monkeypatch.setattr("ai.llm.llm_manager.LLMAdapterFactory.create_adapter", factory)
    presenter.config.get_llm_api_config = lambda: (
        "ChatGPT",
        "model",
        "https://example.invalid",
        "test-key",
    )
    presenter.config.merged_llm_factory_kwargs = lambda provider, kwargs: kwargs | {
        "temperature": 0.6
    }
    assert presenter.render(reminder())["message"] == "你好"
    assert factory.call_args.kwargs["model"] == "model"
    assert factory.call_args.kwargs["temperature"] == 0.6
    client.with_options.assert_called_once_with(timeout=25, max_retries=0)
    assert "tools" not in adapter.chat.call_args.kwargs
    client.close.assert_called_once()


def test_routes_share_presenter_and_do_not_change_schedule_store(presenter):
    import threading
    from frontend_bridge_core.routes.reminder_routes import _presentation, _speech
    from frontend_bridge_core.routes.router import ApiRequest

    state = SimpleNamespace(task_lock=threading.Lock(), reminder_presenter=presenter)
    presenter.render = Mock(return_value={"message": "台词"})
    presenter.speech = Mock(return_value={"audio_path": None})
    request = ApiRequest(
        state=state,
        method="POST",
        path="/api/reminders/presentation",
        query={},
        params={},
        body=reminder(),
    )
    assert _presentation(request).data == {"message": "台词"}
    assert _speech(request).data == {"audio_path": None}
    presenter.render.assert_called_once_with(request.body)
    presenter.speech.assert_called_once_with(request.body)
    assert state.reminder_presenter is presenter


def test_openai_and_anthropic_text_responses():
    assert (
        _text_response(
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="openai"))]
            )
        )
        == "openai"
    )
    assert (
        _text_response(
            SimpleNamespace(content=[SimpleNamespace(type="text", text="claude")])
        )
        == "claude"
    )
