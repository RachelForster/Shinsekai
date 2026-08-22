from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from application.chat.ui_updates import (
    HeadlessUIUpdateManager,
    StreamingUIUpdateManager,
    _format_dialog_html,
    _format_user_html,
    format_context_token_estimate,
)


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, payload: dict) -> None:
        self.events.append(dict(payload))

    def media_url(self, raw_path: str) -> str:
        return f"media://{raw_path}"


def test_presentation_html_escapes_untrusted_content() -> None:
    dialog = _format_dialog_html(
        "<img src=x>",
        "Hello<script>alert(1)</script>\nnext",
        "red;background:url(x)",
        False,
    )
    user = _format_user_html("<script>alert(1)</script>")

    assert "<img" not in dialog
    assert "<script" not in dialog
    assert "color:#FFFFFF" in dialog
    assert "<script" not in user


def test_context_token_estimate_is_compact() -> None:
    assert format_context_token_estimate(
        {
            "system_prompt_tokens": 1200,
            "history_tokens": 34567,
            "tool_definition_tokens": 890,
            "estimated_total_tokens": 36657,
        }
    ) == "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k"


def test_streaming_presenter_emits_media_and_control_events() -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)

    presenter.post_background("room.png")
    presenter.switch_bgm("room.mp3")
    presenter.post_cg("scene.png")
    presenter.post_tts_play(
        "Mio",
        "voice.wav",
        playback_id="voice-1",
        volume=0.75,
    )
    presenter.post_tts_skip(playback_id="voice-1")

    assert [event["type"] for event in sink.events] == [
        "background.change",
        "bgm.change",
        "cg.show",
        "tts.play",
        "tts.skip",
    ]
    assert sink.events[0]["url"] == "media://room.png"
    assert sink.events[3] == {
        "characterName": "Mio",
        "playbackId": "voice-1",
        "type": "tts.play",
        "url": "media://voice.wav",
        "volume": 0.75,
    }
    assert sink.events[4] == {
        "playbackId": "voice-1",
        "type": "tts.skip",
    }


def test_streaming_presenter_emits_frontend_effect_audio_events(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    one_shot = tmp_path / "impact.wav"
    loop = tmp_path / "rain.wav"
    one_shot.write_bytes(b"wav")
    loop.write_bytes(b"wav")

    presenter.play_sound_effect(str(one_shot))
    presenter.start_loop_effect("rain", str(loop))
    presenter.start_loop_effect("rain", str(loop))
    presenter.stop_loop_effect("rain")
    presenter.start_loop_effect("rain", str(loop))
    presenter.stop_all_loop_effects()

    assert presenter.audio_playback_owner == "frontend"
    assert [event["type"] for event in sink.events] == [
        "effect.play",
        "effect.loop.start",
        "effect.loop.stop",
        "effect.loop.start",
        "effect.loop.stop-all",
    ]
    assert "impact.wav" in sink.events[0]["url"]
    assert sink.events[1]["key"] == "rain"


def test_streaming_presenter_keeps_relative_effect_audio_paths_for_the_bridge() -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    presenter.play_sound_effect("data/effects/custom/typing.wav")
    presenter.start_loop_effect("typing", "data/effects/custom/typing.wav")

    assert [event["type"] for event in sink.events] == ["effect.play", "effect.loop.start"]
    assert all(event["url"] == "media://data/effects/custom/typing.wav" for event in sink.events)


def test_streaming_presenter_auto_plays_matching_dialogue_effect(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    keyboard = tmp_path / "keyboard.wav"
    keyboard.write_bytes(b"wav")

    with patch(
        "application.runtime.context.get_app_runtime",
        return_value=type("Runtime", (), {"effect_keyword_map": {"键盘敲击声": str(keyboard)}})(),
    ):
        presenter.update_dialog("旁白", "身后传来键盘敲击声。", "", True)

    assert [event["type"] for event in sink.events[:2]] == ["effect.play", "dialog.end"]
    assert "keyboard.wav" in sink.events[0]["url"]


def test_streaming_presenter_matches_configured_effects_with_nearby_wording(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    rain = tmp_path / "rain.wav"
    keyboard = tmp_path / "keyboard.wav"
    bell = tmp_path / "bell.wav"
    for path in (rain, keyboard, bell):
        path.write_bytes(b"wav")

    runtime = type(
        "Runtime",
        (),
        {
            "effect_keyword_map": {
                "雨天": str(rain),
                "下雨": str(rain),
                "雨声": str(rain),
                "敲键盘": str(keyboard),
                "按门铃": str(bell),
            }
        },
    )()
    with patch("application.runtime.context.get_app_runtime", return_value=runtime):
        presenter.update_dialog("旁白", "窗外的雨下得很急。", "", True)
        presenter.update_dialog("旁白", "他正敲击键盘。", "", True)
        presenter.update_dialog("旁白", "门铃忽然响了。", "", True)

    played = [event["url"] for event in sink.events if event["type"] == "effect.play"]
    assert [Path(url).name for url in played] == ["rain.wav", "keyboard.wav", "bell.wav"]


def test_streaming_presenter_skips_fallback_when_effect_is_explicit(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    keyboard = tmp_path / "keyboard.wav"
    keyboard.write_bytes(b"wav")

    with patch(
        "application.runtime.context.get_app_runtime",
        return_value=type("Runtime", (), {"effect_keyword_map": {"敲键盘": str(keyboard)}})(),
    ):
        presenter.update_dialog("旁白", "他正敲击键盘。", "", True, play_matching_effect=False)

    assert "effect.play" not in [event["type"] for event in sink.events]


def test_streaming_presenter_resolves_explicit_configured_effects(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)
    rain = tmp_path / "rain.wav"
    typing = tmp_path / "typing.wav"
    rain.write_bytes(b"wav")
    typing.write_bytes(b"wav")

    runtime = type(
        "Runtime",
        (),
        {"effect_keyword_map": {"雨天": str(rain), "打字": str(typing)}},
    )()
    with patch("application.runtime.context.get_app_runtime", return_value=runtime):
        assert presenter.resolve_effect("loop:雨天", {}, after_dialog=False)
        assert presenter.resolve_effect("打字", {}, after_dialog=False)

    assert [event["type"] for event in sink.events] == [
        "effect.loop.start",
        "effect.play",
    ]


def test_streaming_presenter_keeps_character_slot_across_expression_changes() -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink)

    class _Character:
        sprite_scale = 1.25
        sprites = [{"path": "neutral.png"}, {"path": "happy.png"}]

    with patch(
        "application.chat.ui_updates.get_character_by_name",
        return_value=_Character(),
    ):
        presenter.update_sprite("Mio", 0)
        presenter.update_sprite("Mio", 1)

    assert [event["slot"] for event in sink.events] == [0, 0]
    assert sink.events[-1]["url"] == "media://happy.png"


def test_headless_presenter_records_framework_neutral_history() -> None:
    history: list[str] = []
    presenter = HeadlessUIUpdateManager(chat_history=history)

    presenter.record_user_message("hello")
    presenter.update_dialog("Mio", "hi", "#ffffff", False)

    assert len(history) == 2
    assert "hello" in history[0]
    assert "Mio" in history[1]
