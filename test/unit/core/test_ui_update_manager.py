import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy  # noqa: F401

    _HAS_NUMPY = True
except ModuleNotFoundError:
    _HAS_NUMPY = False

try:
    from core.runtime.ui_update_manager import (
        StreamingUIUpdateManager,
        connect_to_stream_sink,
        _format_dialog_html,
        _format_user_html,
        _load_image_rgba_array,
        format_context_token_estimate,
    )
    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    StreamingUIUpdateManager = None
    _format_dialog_html = None
    _format_user_html = None
    _load_image_rgba_array = None
    format_context_token_estimate = None
    _IMPORT_ERROR = exc


class _SinkStub:
    def __init__(self):
        self.events = []

    def emit(self, payload):
        self.events.append(dict(payload))

    def media_url(self, raw_path):
        value = str(raw_path or "").replace("\\", "/")
        return f"http://127.0.0.1:8787/api/media?path={value}"


class _MirrorUiStub:
    def __init__(self):
        self.bg_group = []
        self.chat_history = []
        self.current_background_path = None
        self.current_bgm_path = None
        self.calls = []
        self.next_update_sprite_from_path_result = True

    def update_dialog(self, name, speech, color, is_system=True):
        self.calls.append(("update_dialog", name, speech, color, is_system))
        self.chat_history.append(_format_dialog_html(name, speech, color, is_system))

    def record_user_message(self, text):
        self.calls.append(("record_user_message", text))
        value = str(text or "").strip()
        if value:
            self.chat_history.append(_format_user_html(value))

    def update_sprite(self, character_name, sprite_id):
        self.calls.append(("update_sprite", character_name, sprite_id))

    def update_sprite_from_path(self, image_path, *, character_name="", scale=1.0):
        self.calls.append(("update_sprite_from_path", image_path, character_name, scale))
        return self.next_update_sprite_from_path_result

    def remove_character_sprite(self, character_name):
        self.calls.append(("remove_character_sprite", character_name))

    def post_notification(self, text):
        self.calls.append(("post_notification", text))

    def post_busy_bar(self, text, duration_seconds=3.0):
        self.calls.append(("post_busy_bar", text, duration_seconds))

    def hide_busy_bar(self):
        self.calls.append(("hide_busy_bar",))

    def post_options(self, option_list):
        self.calls.append(("post_options", list(option_list)))

    def post_numeric_value(self, text):
        self.calls.append(("post_numeric_value", text))

    def post_context_token_estimate(self, estimate):
        self.calls.append(("post_context_token_estimate", dict(estimate)))

    def post_background(self, path):
        self.calls.append(("post_background", path))
        self.current_background_path = path

    def switch_bgm(self, path):
        self.calls.append(("switch_bgm", path))
        self.current_bgm_path = path

    def post_cg(self, path):
        self.calls.append(("post_cg", path))

    def post_llm_reply_finished(self):
        self.calls.append(("post_llm_reply_finished",))

    def post_pause_asr(self):
        self.calls.append(("post_pause_asr",))

    def post_tts_play(self, character_name, audio_path):
        self.calls.append(("post_tts_play", character_name, audio_path))

    def post_tts_skip(self):
        self.calls.append(("post_tts_skip",))

    def resolve_effect(self, effect, args, after_dialog=False):
        self.calls.append(("resolve_effect", effect, dict(args), after_dialog))
        if str(effect or "").upper() == "LEAVE" and after_dialog:
            self.remove_character_sprite(str(args.get("character_name") or ""))


@unittest.skipIf(_IMPORT_ERROR is not None, f"ui_update_manager import unavailable: {_IMPORT_ERROR}")
class UIUpdateManagerTests(unittest.TestCase):
    def test_format_context_token_estimate_is_compact(self):
        text = format_context_token_estimate(
            {
                "system_prompt_tokens": 1200,
                "history_tokens": 34567,
                "tool_definition_tokens": 890,
                "estimated_total_tokens": 36657,
            }
        )

        self.assertEqual(text, "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k")

    def test_dialog_html_escapes_content_and_rejects_unsafe_color(self):
        formatted = _format_dialog_html(
            "<img src=x onerror=alert(1)>",
            "Hello<script>alert(1)</script>\nnext",
            "red;background:url(javascript:alert(1))",
            False,
        )

        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", formatted)
        self.assertIn("Hello&lt;script&gt;alert(1)&lt;/script&gt;<br>next", formatted)
        self.assertIn("color:#FFFFFF", formatted)
        self.assertNotIn("<img", formatted)
        self.assertNotIn("<script", formatted)
        self.assertNotIn("javascript:", formatted)

    def test_user_html_escapes_content(self):
        formatted = _format_user_html("<script>alert(1)</script>\nnext")

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;<br>next", formatted)
        self.assertNotIn("<script", formatted)

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed")
    def test_load_image_rgba_array_supports_unicode_paths(self):
        from PySide6.QtGui import QColor, QImage

        image_format = getattr(getattr(QImage, "Format", QImage), "Format_RGBA8888")
        image = QImage(2, 1, image_format)
        image.setPixelColor(0, 0, QColor(10, 20, 30, 40))
        image.setPixelColor(1, 0, QColor(50, 60, 70, 255))

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "立绘.png"
            self.assertTrue(image.save(str(image_path)))

            array = _load_image_rgba_array(str(image_path))

        self.assertIsNotNone(array)
        self.assertEqual(array.shape, (1, 2, 4))
        self.assertEqual(array[0, 0].tolist(), [10, 20, 30, 40])
        self.assertEqual(array[0, 1].tolist(), [50, 60, 70, 255])

    def test_streaming_ui_update_manager_maps_background_bgm_and_cg_paths_to_media_urls(self):
        sink = _SinkStub()
        bg_group = [{"path": "data/backgrounds/room.png"}]
        manager = StreamingUIUpdateManager(sink, bg_group=bg_group)

        manager.post_background("data/backgrounds/room.png")
        manager.switch_bgm("data/bgm/room.mp3")
        manager.post_cg("data/cg/scene.png")
        manager.post_cg("")

        self.assertEqual(manager.bg_group, bg_group)
        self.assertEqual(
            sink.events,
            [
                {
                    "type": "background.change",
                    "url": "http://127.0.0.1:8787/api/media?path=data/backgrounds/room.png",
                },
                {
                    "type": "bgm.change",
                    "url": "http://127.0.0.1:8787/api/media?path=data/bgm/room.mp3",
                },
                {
                    "type": "cg.show",
                    "url": "http://127.0.0.1:8787/api/media?path=data/cg/scene.png",
                },
                {
                    "type": "cg.hide",
                },
            ],
        )

    def test_streaming_ui_update_manager_maps_sprite_paths_to_media_urls(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink)

        class _Character:
            sprite_scale = 1.25
            sprites = [{"path": "data/sprites/mio_happy.png"}]

        with patch("core.runtime.ui_update_manager.get_character_by_name", return_value=_Character()):
            manager.update_sprite("Mio", 0)

        self.assertEqual(
            sink.events,
            [
                {
                    "characterName": "Mio",
                    "scale": 1.25,
                    "slot": 0,
                    "type": "sprite.show",
                    "url": "http://127.0.0.1:8787/api/media?path=data/sprites/mio_happy.png",
                }
            ],
        )

    def test_streaming_ui_update_manager_keeps_display_slot_when_expression_changes(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink)

        class _Character:
            sprite_scale = 1.0
            sprites = [
                {"path": "data/sprites/mio-neutral.png"},
                {"path": "data/sprites/mio-happy.png"},
            ]

        with patch("core.runtime.ui_update_manager.get_character_by_name", return_value=_Character()):
            manager.update_sprite("Mio", 0)
            manager.update_sprite("Mio", 1)

        self.assertEqual([event["slot"] for event in sink.events], [0, 0])
        self.assertTrue(sink.events[1]["url"].endswith("mio-happy.png"))

    def test_streaming_ui_update_manager_reuses_slots_with_character_lru(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink, max_sprite_slots=2)

        manager.update_sprite_from_path("data/sprites/mio.png", character_name="Mio")
        manager.update_sprite_from_path("data/sprites/ren.png", character_name="Ren")
        manager.update_sprite_from_path("data/sprites/mio-2.png", character_name="Mio")
        manager.update_sprite_from_path("data/sprites/aoi.png", character_name="Aoi")

        self.assertEqual([event["slot"] for event in sink.events], [0, 1, 0, 1])
        self.assertEqual(list(manager._sprite_lru.items()), [("Mio", 0), ("Aoi", 1)])

        manager.remove_character_sprite("Mio")
        manager.update_sprite_from_path("data/sprites/ren-2.png", character_name="Ren")
        self.assertEqual(sink.events[-1]["slot"], 0)

    def test_streaming_ui_update_manager_emits_tts_play_and_skip_events(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink)

        manager.post_tts_play("Mio", "data/audio/mio.wav")
        manager.post_tts_skip()

        self.assertEqual(
            sink.events,
            [
                {
                    "characterName": "Mio",
                    "type": "tts.play",
                    "url": "http://127.0.0.1:8787/api/media?path=data/audio/mio.wav",
                },
                {
                    "type": "tts.skip",
                },
            ],
        )

    def test_streaming_ui_update_manager_emits_session_closed_event(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink)

        manager.post_session_closed("聊天会话已结束。")

        self.assertEqual(
            sink.events,
            [
                {
                    "type": "session.closed",
                    "reason": "聊天会话已结束。",
                }
            ],
        )

    def test_streaming_ui_update_manager_emits_control_and_cleanup_events(self):
        sink = _SinkStub()
        manager = StreamingUIUpdateManager(sink)

        manager.record_user_message("hello")
        sink.events.clear()

        manager.post_notification("Ready")
        manager.post_busy_bar("Loading", 1.5)
        manager.post_busy_bar("", 9.0)
        manager.hide_busy_bar()
        manager.post_options([])
        manager.post_numeric_value("heart|HP|42|100")
        manager.post_context_token_estimate(
            {
                "system_prompt_tokens": 1200,
                "history_tokens": 34567,
                "tool_definition_tokens": 890,
                "estimated_total_tokens": 36657,
            }
        )
        manager.remove_character_sprite("Mio")
        manager.resolve_effect("LEAVE", {"character_name": "Nanami"}, after_dialog=True)
        manager.post_llm_reply_finished()

        self.assertEqual(
            [event["type"] for event in sink.events],
            [
                "notification.change",
                "busy.show",
                "busy.hide",
                "busy.hide",
                "options.clear",
                "history.replace",
                "stats.update",
                "numeric.update",
                "sprite.remove",
                "sprite.remove",
                "reply.finished",
                "status.change",
            ],
        )
        self.assertEqual(sink.events[0]["text"], "Ready")
        self.assertEqual(sink.events[1]["text"], "Loading")
        self.assertEqual(sink.events[1]["durationSeconds"], 1.5)
        self.assertEqual(sink.events[5]["entries"][0]["role"], "user")
        self.assertEqual(sink.events[5]["entries"][0]["text"], "你: hello")
        self.assertEqual(
            sink.events[6]["stats"],
            [{"icon": "heart", "label": "HP", "max": 100, "value": 42}],
        )
        self.assertEqual(
            sink.events[7]["html"],
            "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k",
        )
        self.assertEqual(sink.events[8]["characterName"], "Mio")
        self.assertEqual(sink.events[9]["characterName"], "Nanami")
        self.assertEqual(sink.events[11]["status"], "idle")

    def test_connect_to_stream_sink_mirrors_desktop_updates(self):
        sink = _SinkStub()
        ui = _MirrorUiStub()

        connect_to_stream_sink(ui, sink)

        ui.record_user_message("hello")
        ui.update_dialog("Mio", "Ready", "#fff", False)
        ui.post_background("data/backgrounds/room.png")
        ui.switch_bgm("data/bgm/room.mp3")
        ui.update_sprite_from_path("data/sprites/mio.png", character_name="Mio", scale=1.25)
        ui.post_options(["Go"])
        ui.post_llm_reply_finished()
        ui.post_pause_asr()
        ui.post_tts_play("Mio", "data/audio/mio.wav")
        ui.post_tts_skip()

        event_types = [event["type"] for event in sink.events]
        self.assertEqual(
            event_types,
            [
                "history.replace",
                "history.replace",
                "dialog.end",
                "history.replace",
                "background.change",
                "bgm.change",
                "sprite.show",
                "options.show",
                "history.replace",
                "reply.finished",
                "status.change",
                "asr.state",
                "tts.play",
                "tts.skip",
            ],
        )
        self.assertEqual(sink.events[0]["entries"], [])
        self.assertEqual([item["text"] for item in sink.events[1]["entries"]], ["你: hello"])
        self.assertEqual([item["text"] for item in sink.events[3]["entries"]], ["你: hello", "Mio：Ready"])
        self.assertEqual([item["text"] for item in sink.events[8]["entries"]], ["你: hello", "Mio：Ready"])
        self.assertEqual(sink.events[4]["url"], "http://127.0.0.1:8787/api/media?path=data/backgrounds/room.png")
        self.assertEqual(sink.events[5]["url"], "http://127.0.0.1:8787/api/media?path=data/bgm/room.mp3")
        self.assertEqual(sink.events[6]["url"], "http://127.0.0.1:8787/api/media?path=data/sprites/mio.png")
        self.assertEqual(sink.events[12]["url"], "http://127.0.0.1:8787/api/media?path=data/audio/mio.wav")

    def test_connect_to_stream_sink_mirrors_control_events_and_skips_failed_sprite_updates(self):
        sink = _SinkStub()
        ui = _MirrorUiStub()

        connect_to_stream_sink(ui, sink)
        sink.events.clear()

        ui.record_user_message("hello")
        ui.post_notification("Ready")
        ui.post_busy_bar("Loading", 1.5)
        ui.post_busy_bar("", 9.0)
        ui.hide_busy_bar()
        ui.post_options([])
        ui.post_numeric_value("heart|HP|42|100")
        ui.post_context_token_estimate(
            {
                "system_prompt_tokens": 1200,
                "history_tokens": 34567,
                "tool_definition_tokens": 890,
                "estimated_total_tokens": 36657,
            }
        )
        ui.remove_character_sprite("Mio")
        ui.resolve_effect("LEAVE", {"character_name": "Nanami"}, after_dialog=True)
        ui.next_update_sprite_from_path_result = False
        ok = ui.update_sprite_from_path("data/sprites/missing.png", character_name="Ignored", scale=2.0)
        ui.post_llm_reply_finished()

        self.assertFalse(ok)
        self.assertEqual(
            [event["type"] for event in sink.events],
            [
                "history.replace",
                "notification.change",
                "busy.show",
                "busy.hide",
                "busy.hide",
                "options.clear",
                "history.replace",
                "stats.update",
                "numeric.update",
                "sprite.remove",
                "sprite.remove",
                "reply.finished",
                "status.change",
            ],
        )
        self.assertEqual(sink.events[0]["entries"][0]["text"], "你: hello")
        self.assertEqual(sink.events[1]["text"], "Ready")
        self.assertEqual(sink.events[2]["durationSeconds"], 1.5)
        self.assertEqual(sink.events[6]["entries"][0]["text"], "你: hello")
        self.assertEqual(
            sink.events[7]["stats"],
            [{"icon": "heart", "label": "HP", "max": 100, "value": 42}],
        )
        self.assertEqual(
            sink.events[8]["html"],
            "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k",
        )
        self.assertEqual(sink.events[9]["characterName"], "Mio")
        self.assertEqual(sink.events[10]["characterName"], "Nanami")
        self.assertFalse(
            any(
                event["type"] == "sprite.show" and event.get("characterName") == "Ignored"
                for event in sink.events
            )
        )


if __name__ == "__main__":
    unittest.main()
