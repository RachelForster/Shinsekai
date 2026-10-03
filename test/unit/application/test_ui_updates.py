from __future__ import annotations

from unittest.mock import patch

import pytest

from types import SimpleNamespace
from core.media.effect_image import ImageEffectAsset

from application.runtime.event_sink import fold_event_into_snapshot, make_empty_chat_snapshot
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

class _Urls:
    def media_url(self, raw_path: str) -> str:
        return f"media://{raw_path}"

    def avatar_url(self, model_path: str, path: str) -> str:
        return f"avatar://{model_path}/{path}"


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
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())

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
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
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
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    presenter.play_sound_effect("data/effects/custom/typing.wav")
    presenter.start_loop_effect("typing", "data/effects/custom/typing.wav")

    assert [event["type"] for event in sink.events] == ["effect.play", "effect.loop.start"]
    assert all(event["url"] == "media://data/effects/custom/typing.wav" for event in sink.events)


def test_streaming_presenter_does_not_guess_effects_from_dialogue(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    keyboard = tmp_path / "keyboard.wav"
    keyboard.write_bytes(b"wav")

    with patch(
        "application.runtime.context.get_app_runtime",
        return_value=type("Runtime", (), {"effect_keyword_map": {"键盘敲击声": str(keyboard)}})(),
    ):
        presenter.update_dialog("旁白", "身后传来键盘敲击声。", "", True)

    assert [event["type"] for event in sink.events] == ["dialog.end", "history.replace"]


def test_streaming_presenter_does_not_match_nearby_effect_wording(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
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

    assert "effect.play" not in [event["type"] for event in sink.events]


def test_streaming_presenter_resolves_explicit_configured_effects(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
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


def test_streaming_presenter_resolves_image_and_audio_for_the_same_keyword(tmp_path) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    audio = tmp_path / "item.wav"
    image = tmp_path / "item.png"
    bound_audio = tmp_path / "bound-item.wav"
    audio.write_bytes(b"wav")
    image.write_bytes(b"png")
    bound_audio.write_bytes(b"wav")
    runtime = type(
        "Runtime",
        (),
        {
            "effect_keyword_map": {"获得钥匙": str(audio)},
            "effect_image_keyword_map": {"获得钥匙": ImageEffectAsset(str(image), str(bound_audio))},
        },
    )()

    with patch("application.runtime.context.get_app_runtime", return_value=runtime):
        assert presenter.resolve_effect("获得钥匙", {}, after_dialog=False)

    assert [event["type"] for event in sink.events] == ["effect.play", "effect.image.show"]
    assert "bound-item.wav" in sink.events[0]["url"]
    assert sink.events[-1]["durationMs"] == 8_800
    assert sink.events[-1]["label"] == "获得钥匙"


def test_exact_audio_label_is_not_replaced_by_a_substring_image():
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    runtime = SimpleNamespace(
        effect_keyword_map={"keyboard": "typing.wav"},
        effect_image_keyword_map={"key": ImageEffectAsset("key.png", "pickup.wav")},
    )
    with patch("application.runtime.context.get_app_runtime", return_value=runtime):
        assert presenter.resolve_effect("  KEYBOARD  ", {}, after_dialog=False)
        assert not presenter.resolve_effect("获得了key", {}, after_dialog=False)
    assert sink.events == [{"type": "effect.play", "url": "media://typing.wav"}]


@pytest.mark.parametrize("timing", ["before", "after"])
def test_image_and_bound_audio_follow_explicit_timing_once(timing):
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    runtime = SimpleNamespace(effect_image_keyword_map={
        "key": ImageEffectAsset("key.png", "pickup.wav"),
    })
    with patch("application.runtime.context.get_app_runtime", return_value=runtime):
        presenter.resolve_effect(f"{timing}:key", {}, after_dialog=False)
        assert len(sink.events) == (2 if timing == "before" else 0)
        presenter.resolve_effect(f"{timing}:key", {}, after_dialog=True)
        assert len(sink.events) == 2
        assert not presenter.resolve_effect("loop:key", {}, after_dialog=False)
        assert len(sink.events) == 2


def test_streaming_presenter_keeps_character_slot_across_expression_changes() -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())

    class _Character:
        name = "Mio"
        sprite_scale = 1.25
        sprites = [{"path": "neutral.png"}, {"path": "happy.png"}]

    with patch(
        "application.chat.ui_updates.get_character_by_name",
        return_value=_Character(),
    ):
        presenter.update_sprite("Mio", 0)
        presenter.update_sprite("mio", 1)

    assert [event["slot"] for event in sink.events] == [0, 0]
    assert [event["characterName"] for event in sink.events] == ["Mio", "Mio"]
    assert [event["identityKey"] for event in sink.events] == ["character:mio", "character:mio"]
    assert sink.events[-1]["url"] == "media://happy.png"
    assert sink.events[-1]["avatarType"] == "static"
    assert sink.events[-1]["modelUrl"] == ""
    presenter.remove_character_sprite("mio")
    assert not presenter._sprite_lru
    assert sink.events[-1] == {"type": "sprite.remove", "characterName": "Mio"}


def test_unowned_initial_images_have_path_identities_before_transport(tmp_path, monkeypatch) -> None:
    from application.chat.initial_sprite import display_initial_sprite
    from application.chat.character_visual import image_visual_identity

    monkeypatch.chdir(tmp_path)
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    config = SimpleNamespace(config=SimpleNamespace(characters=[]))
    for path in ("a/portrait.png", "b/portrait.png", str(tmp_path / "a/portrait.png")):
        assert display_initial_sprite(path, config=config, ui_updates=presenter)
    first, second, repeated = sink.events
    assert first["characterName"] == second["characterName"] == "portrait"
    assert first["identityKey"] != second["identityKey"]
    assert first["identityKey"] == repeated["identityKey"]
    assert image_visual_identity("a\\portrait.png") == first["identityKey"]
    snapshot = fold_event_into_snapshot(make_empty_chat_snapshot(), first)
    assert snapshot["sprites"][0]["identityKey"] == first["identityKey"]


def test_model_presentation_uses_its_own_bank_and_preserves_metadata_in_snapshot():
    from config.schema import Character

    character = Character(
        name="Mio", color="#fff", sprite_prefix="mio", avatar_type=" VRM ",
        sprites=[{"path": "static.png"}],
        avatars={" VRM ": {"model_path": "mio.vrm", "sprites": [{"path": "smile.json"}]}},
    )
    sink = _Sink()
    with patch("application.chat.ui_updates.get_character_by_name", return_value=character):
        StreamingUIUpdateManager(sink, resource_urls=_Urls()).update_sprite("Mio", 0)
    event = sink.events[-1]
    assert event["url"] == "avatar://mio.vrm/smile.json"
    assert event["avatarType"] == "vrm"
    assert event["modelUrl"] == "avatar://mio.vrm/mio.vrm"
    sprite = fold_event_into_snapshot(make_empty_chat_snapshot(), event)["sprites"][0]
    assert sprite["avatarType"] == "vrm"
    assert sprite["modelUrl"] == "avatar://mio.vrm/mio.vrm"
    assert sprite["path"] == "avatar://mio.vrm/smile.json"
    assert sprite["identityKey"] == "character:mio"


def test_model_stage_and_static_player_portrait_keep_separate_resource_routes():
    character = SimpleNamespace(
        avatar_type="l2d", sprite_scale=1.25,
        avatars={"l2d": {"model_path": "mio.model3.json", "sprites": [{"path": "smile.json"}]}},
        sprites=[{"path": "portrait.png", "portrait_crop": {"x": 0.2, "y": 0.3, "zoom": 2}}],
    )
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    with patch("application.chat.ui_updates.get_character_by_name", return_value=character):
        presenter.update_sprite("Mio", 0)
        presenter.update_player_portrait("Mio", 0)
    assert sink.events[0]["url"] == "avatar://mio.model3.json/smile.json"
    assert sink.events[0]["modelUrl"] == "avatar://mio.model3.json/mio.model3.json"
    assert sink.events[1] == {
        "type": "player.portrait.show", "characterName": "Mio", "url": "media://portrait.png",
        "crop": {"x": 0.2, "y": 0.3, "zoom": 2},
    }
    assert list(presenter._sprite_lru) == ["Mio"]


@pytest.mark.parametrize("next_background", ["street.png", ""])
def test_background_switch_clears_reconnect_sprites_and_reassigns_slots(next_background) -> None:
    sink = _Sink()
    presenter = StreamingUIUpdateManager(sink, resource_urls=_Urls())
    presenter.post_background("room.png")
    presenter.update_sprite_from_path("mio.png", character_name="Mio")
    presenter.update_sprite_from_path("ren.png", character_name="Ren")
    presenter.post_background("room.png")
    presenter.update_sprite_from_path("aoi.png", character_name="Aoi")
    assert [event["slot"] for event in sink.events if event["type"] == "sprite.show"] == [0, 1, 2]

    snapshot = make_empty_chat_snapshot()
    for event in sink.events:
        snapshot = fold_event_into_snapshot(snapshot, event)
    assert len(snapshot["sprites"]) == 3

    presenter.post_background(next_background)
    cleared = fold_event_into_snapshot(snapshot, sink.events[-1])
    assert cleared["sprites"] == []
    assert len(snapshot["sprites"]) == 3

    presenter.update_sprite_from_path("ren-happy.png", character_name="Ren")
    returned = fold_event_into_snapshot(cleared, sink.events[-1])
    assert [(sprite["characterName"], sprite["slot"]) for sprite in returned["sprites"]] == [("Ren", 0)]
    presenter.update_sprite_from_path("mio.png", character_name="Mio")
    assert sink.events[-1]["slot"] == 1


def test_headless_presenter_records_framework_neutral_history() -> None:
    history: list[str] = []
    presenter = HeadlessUIUpdateManager(chat_history=history)

    presenter.record_user_message("hello")
    presenter.update_dialog("Mio", "hi", "#ffffff", False)

    assert len(history) == 2
    assert "hello" in history[0]
    assert "Mio" in history[1]
