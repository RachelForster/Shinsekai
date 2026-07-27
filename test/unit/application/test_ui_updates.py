from __future__ import annotations

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
    presenter.post_tts_play("Mio", "voice.wav")
    presenter.post_tts_skip()

    assert [event["type"] for event in sink.events] == [
        "background.change",
        "bgm.change",
        "cg.show",
        "tts.play",
        "tts.skip",
    ]
    assert sink.events[0]["url"] == "media://room.png"


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
