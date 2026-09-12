import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.tts.model_session import tts_model_session
from application.reminders.presentation import ReminderPresenter
from test.mocks import MockLLMAdapter


@pytest.fixture
def presenter(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ai.tts.model_session.tempfile.gettempdir", lambda: str(tmp_path)
    )
    character = SimpleNamespace(
        name="澪",
        character_setting="嘴硬但关心用户，喜欢用反问句。",
        character_brief="可靠的朋友",
        sprites=[],
        emotion_tags="",
        gpt_model_path="voice.ckpt",
        sovits_model_path="voice.pth",
        refer_audio_path="reference.wav",
        prompt_text="参考台词",
        prompt_lang="zh",
        speech_speed=1.1,
        speech_volume=0.7,
        pronunciation_map={"澪": "ミオ"},
    )
    config = SimpleNamespace(
        config=SimpleNamespace(
            system_config=SimpleNamespace(ui_language="zh_CN", voice_language="ja"),
            api_config=SimpleNamespace(tts_split_enabled=True, temperature=0.6),
            characters=[character],
        ),
        get_character_by_name=lambda name: (
            character if name == character.name else None
        ),
        get_gpt_sovits_config=lambda: ("http://tts/", "tts", "gpt-sovits"),
        merged_tts_factory_kwargs=lambda provider, kwargs: kwargs,
        get_llm_api_config=lambda: (
            "ChatGPT",
            "model",
            "https://example.invalid",
            "test-key",
        ),
        merged_llm_factory_kwargs=lambda provider, kwargs: kwargs,
    )
    result = ReminderPresenter(config, tmp_path)
    yield result
    result.close()


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


def dialog(**kwargs):
    return (
        dict(
            character_name="澪",
            speech="还不喝那 200 ml 水？",
            translate="水を200 ml飲まないの？",
            sprite="-1",
        )
        | kwargs
    )


def output(*items):
    return json.dumps({"dialog": list(items) or [dialog()]}, ensure_ascii=False)


def test_reuses_dialog_contract_personality_translation_and_single_item_limit(
    presenter,
):
    presenter.workflow.complete = Mock(return_value=output())
    result = presenter.render(reminder())
    assert result["message"] == dialog()["speech"]
    assert result["dialog"]["translate"] == dialog()["translate"]
    assert "speech_language" not in result
    system, user = presenter.workflow.complete.call_args.args
    assert json.loads(user) == reminder()
    assert "嘴硬但关心用户" in system
    assert '"dialog"' in system and '"translate"' in system
    assert "exactly one dialog item" in system
    assert "do not invent facts" in system
    from i18n import tr_in_bundle

    assert tr_in_bundle("template_gen.r_dialog_max_items", "zh_CN", n=1) in system


def test_same_language_uses_normal_contract_without_translate_field(presenter):
    presenter.config.config.system_config.voice_language = "zh"
    presenter.workflow.complete = Mock(return_value=output(dialog(translate="")))
    assert presenter.render(reminder())["message"] == dialog()["speech"]
    assert '"translate"' not in presenter.workflow.complete.call_args.args[0]


def test_extra_dialogs_and_other_speakers_never_produce_multiple_reminders(presenter):
    presenter.workflow.complete = Mock(
        return_value=output(
            dialog(character_name="NARR"), dialog(), dialog(speech="第二句")
        )
    )
    result = presenter.render(reminder())
    assert result["dialog"]["character_name"] == "澪"
    assert result["message"] == dialog()["speech"]


@pytest.mark.parametrize(
    "raw",
    [
        "invalid",
        "[]",
        '{"message":"old format","speech":"old format"}',
        output(dialog(character_name="陌生人")),
        output(dialog(speech="")),
        output(dialog(speech="x" * 401)),
    ],
)
def test_invalid_generation_keeps_original_as_standard_dialog(presenter, raw):
    presenter.workflow.complete = Mock(return_value=raw)
    result = presenter.render(reminder())
    assert result["message"] == reminder()["message"]
    assert result["dialog"]["speech"] == reminder()["message"]
    assert result["dialog"]["translate"] == ""


def test_unavailable_or_busy_workflow_does_not_lose_reminder(presenter):
    presenter.workflow.complete = Mock(side_effect=TimeoutError("slow model"))
    assert presenter.render(reminder())["message"] == reminder()["message"]
    presenter.workflow.complete.reset_mock()
    with presenter._slots:
        assert presenter.render(reminder())["message"] == reminder()["message"]
    presenter.render(reminder(character_name="removed character"))
    presenter.workflow.complete.assert_not_called()


def configure_llm(presenter, monkeypatch, responses):
    adapter = MockLLMAdapter(responses=responses)
    adapter.client = Mock()
    adapter.client.with_options.return_value = adapter.client
    monkeypatch.setattr(
        "ai.llm.llm_manager.LLMAdapterFactory.create_adapter",
        Mock(return_value=adapter),
    )
    return adapter


def test_existing_llm_manager_repairs_output_without_tools_or_chat_history(
    presenter, monkeypatch
):
    adapter = configure_llm(presenter, monkeypatch, ["喝水吧", output()])
    assert presenter.render(reminder())["message"] == dialog()["speech"]
    assert len(adapter.call_history) == 2
    assert all(not call["kwargs"].get("tools") for call in adapter.call_history)
    adapter.client.with_options.assert_called_once_with(timeout=10, max_retries=0)
    adapter.client.close.assert_called_once()
    # A later reminder has its own chat turn, not the preceding reminder history.
    adapter.responses = [output()]
    presenter.render(reminder())
    assert (
        len([m for m in adapter.call_history[-1]["messages"] if m["role"] == "user"])
        == 1
    )


def test_dialog_workflow_rejects_unexpected_tool_calls(presenter, monkeypatch):
    adapter = configure_llm(presenter, monkeypatch, [output()])
    adapter.chat = Mock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="", tool_calls=[object()])
                )
            ]
        )
    )
    execute = Mock()
    monkeypatch.setattr("ai.llm.llm_manager.tool_executor.execute", execute)
    assert presenter.render(reminder())["message"] == reminder()["message"]
    execute.assert_not_called()
    adapter.chat.assert_called_once()


def configure_tts(monkeypatch):
    adapter = Mock()

    def generate(text, **kwargs):
        Path(kwargs["file_path"]).write_bytes(b"RIFF-test-audio")
        return kwargs["file_path"]

    adapter.generate_speech.side_effect = generate
    monkeypatch.setattr(
        "ai.tts.tts_manager.TTSAdapterFactory.create_adapter",
        Mock(return_value=adapter),
    )
    return adapter


def test_shared_tts_uses_translate_cleanup_pronunciation_and_unique_audio(
    presenter, monkeypatch
):
    adapter = configure_tts(monkeypatch)
    translate = Mock(side_effect=AssertionError("Already translated"))
    monkeypatch.setattr(
        "ai.llm.text_processor.TextProcessor.libre_translate", translate
    )
    payload = {"dialog": dialog(translate="（笑）澪、水を飲んで。")}
    first, second = presenter.speech(payload), presenter.speech(payload)
    assert first["audio_path"] != second["audio_path"]
    assert Path(first["audio_path"]).read_bytes() == b"RIFF-test-audio"
    assert first["audio_volume"] == 0.7
    args = adapter.generate_speech.call_args.kwargs
    assert args["text"] == "ミオ、水を飲んで。"
    assert args["text_lang"] == "ja"
    assert args["speed_factor"] == 1.1
    assert (
        args["ref_audio_path"]
        == (presenter.audio_dir.parent.parent / "reference.wav").as_posix()
    )
    assert presenter.config.config.api_config.tts_split_enabled is True
    translate.assert_not_called()


def test_missing_translate_uses_existing_tts_translation_fallback(
    presenter, monkeypatch
):
    adapter = configure_tts(monkeypatch)
    translate = Mock(return_value="水を飲んで。")
    monkeypatch.setattr(
        "ai.llm.text_processor.TextProcessor.libre_translate", translate
    )
    assert presenter.speech(
        {"dialog": dialog(speech="（招手）<b>喝水吧。</b>", translate="")}
    )["audio_path"]
    translate.assert_called_once_with("喝水吧。", source="zh", target="ja")
    assert adapter.generate_speech.call_args.kwargs["text"] == "水を飲んで。"


def test_failed_tts_removes_partial_files_and_allows_next_attempt(
    presenter, monkeypatch
):
    adapter = configure_tts(monkeypatch)

    def generate(**kwargs):
        Path(kwargs["file_path"]).write_bytes(b"partial")
        raise TimeoutError("tts timeout")

    adapter.generate_speech.side_effect = generate
    assert presenter.speech({"dialog": dialog()}) == {"audio_path": None}
    assert list(presenter.audio_dir.iterdir()) == []
    assert presenter.speech({"dialog": dialog()}) == {"audio_path": None}
    assert adapter.generate_speech.call_count == 2


def test_disabled_voice_and_missing_character_are_text_only(presenter):
    presenter.config.get_gpt_sovits_config = lambda: ("", "", "none")
    assert presenter.speech({"dialog": dialog()}) == {"audio_path": None}
    assert presenter.speech({"dialog": dialog(character_name="unknown")}) == {
        "audio_path": None
    }


@pytest.mark.parametrize(
    "payload", [None, {}, reminder(message=""), reminder(character_name="x" * 121)]
)
def test_invalid_presentation_request_is_rejected(presenter, payload):
    with pytest.raises(ValueError):
        presenter.render(payload)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"dialog": {}},
        {"dialog": dialog(speech="")},
        {"dialog": dialog(translate="x" * 2001)},
    ],
)
def test_invalid_speech_request_is_rejected(presenter, payload):
    with pytest.raises(ValueError):
        presenter.speech(payload)


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
    with tts_model_session(SimpleNamespace(), "http://tts"):
        with pytest.raises(Timeout):
            with tts_model_session(SimpleNamespace(), "http://tts", timeout=0):
                pytest.fail("Concurrent model switch was allowed")
