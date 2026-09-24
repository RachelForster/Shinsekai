"""Run with runtime/python.exe -m unittest test.unit.application.chat.test_player_control."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from application.chat.player_control import resolve_player
from application.chat.ui_updates import StreamingUIUpdateManager
from application.runtime.event_sink import fold_event_into_snapshot, make_empty_chat_snapshot
from config.schema import Character, PortraitCrop, Sprite
from sdk.messages import PresentationMessage


class PlayerControlTests(unittest.TestCase):
    def test_player_prompt_uses_normal_dialog_schema_and_excludes_player_from_cast(self):
        from i18n import init_i18n

        init_i18n("zh_CN")
        from ai.llm.template_generator import TemplateGenerator, _T

        player = SimpleNamespace(
            name="神羽",
            sprites=[{}],
            emotion_tags="立绘1：笑",
            character_setting="用户独有资料",
            character_brief="用户简述",
        )
        npc = SimpleNamespace(
            name="阳明",
            sprites=[{}],
            emotion_tags="立绘1：平常",
            character_setting="其他角色资料",
            character_brief="",
        )
        generator = object.__new__(TemplateGenerator)
        generator.resolve_chat_template_characters = lambda names: [
            (character.name, character)
            for character in (player, npc)
            if character.name in names
        ]
        generator._get_output_contract_patches = lambda: []
        with (
            patch("ai.llm.template_generator._format_llm_tools_block", return_value=""),
            patch("ai.llm.template_generator._target_voice_display_name", return_value="中文"),
        ):
            template, _ = generator.generate_chat_template(
                ["神羽", "阳明"],
                "",
                False,
                False,
                False,
                player_character="神羽",
                read_player_speech=True,
            )

        self.assertEqual(template.splitlines()[0], _T("preamble", names="阳明").strip())
        self.assertNotIn(_T("profile_for", name="神羽"), template)
        self.assertNotIn(_T("sprites_count", name="神羽", n=1), template)
        self.assertIn("用户独有资料", template)
        self.assertIn('"character_name":"神羽"', template)
        self.assertIn('"sprite":"-1"', template)
        self.assertNotIn("player_speech", template)
        self.assertNotIn("player_portrait", template)

    def test_player_media_restores_from_normal_dialog_items(self):
        from application.chat.dialog_media.replay import latest_media_dialogs

        content = json.dumps(
            {
                "dialog": [
                    {"character_name": "阳明", "sprite": "1", "speech": "你想怎么做？"},
                    {"character_name": "神羽", "sprite": "2", "speech": ""},
                ]
            },
            ensure_ascii=False,
        )
        dialogs = latest_media_dialogs(
            [{"role": "assistant", "content": content}],
            opencc=SimpleNamespace(convert=lambda text: text),
            player_name="神羽",
        )

        player = next(dialog for dialog in dialogs if dialog.name == "神羽")
        self.assertEqual(player.text, "")
        self.assertEqual(player.asset_id, "2")

    def test_selection_must_be_in_cast(self):
        config = SimpleNamespace(
            get_character_by_name=lambda name: SimpleNamespace(name="神羽")
        )
        self.assertEqual(resolve_player(config, ["神羽"], "神羽"), "神羽")
        with self.assertRaises(ValueError):
            resolve_player(config, ["阳明"], "神羽")

    def test_saved_history_keeps_normal_player_dialog(self):
        from application.chat.runtime_process import _serialize_history_entries_from_messages

        messages = [
            {"role": "user", "content": "我才不要（摊开手）"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "dialog": [
                            {"character_name": "神羽", "speech": "我才不要"},
                            {"character_name": "阳明", "speech": "小心！"},
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        entries = _serialize_history_entries_from_messages(messages, "神羽")
        self.assertEqual(
            [entry["text"] for entry in entries],
            ["神羽: 我才不要（摊开手）", "神羽: 我才不要", "阳明: 小心！"],
        )

    def test_portrait_has_no_stage_slot_and_uses_sprite_override(self):
        crop = PortraitCrop(x=0.4, y=0.3, zoom=2)
        character = Character.model_construct(
            name="神羽",
            sprites=[Sprite.model_construct(path="face.png", portrait_crop=crop)],
        )
        sink = MagicMock()
        sink.media_url.side_effect = lambda path: path
        ui = StreamingUIUpdateManager(sink, chat_history=[])
        ui.set_player_character("神羽")
        with patch("application.chat.ui_updates.get_character_by_name", return_value=character):
            ui.update_player_portrait("神羽", 0)

        event = sink.emit.call_args.args[0]
        self.assertEqual(event["type"], "player.portrait.show")
        self.assertEqual(event["crop"], crop.model_dump())
        self.assertFalse(ui._sprite_lru)
        snapshot = fold_event_into_snapshot(make_empty_chat_snapshot(), {**event, "seq": 1})
        snapshot = fold_event_into_snapshot(
            snapshot, {"type": "background.change", "url": "new.png", "seq": 2}
        )
        self.assertEqual(snapshot["playerPortrait"]["crop"], crop.model_dump())
        self.assertEqual(snapshot["sprites"], [])

    def test_expression_waits_for_related_narration_and_is_discarded_for_npc(self):
        ui = StreamingUIUpdateManager(MagicMock(), chat_history=[])
        ui.set_player_character("神羽")
        with patch.object(ui, "update_player_portrait") as update:
            ui.queue_player_portrait("神羽", 1)
            update.assert_not_called()
            ui.update_dialog("阳明", "神羽，小心！", "#fff", False)
            update.assert_not_called()
            ui.update_dialog("NARR", "神羽摊开手。", "#fff")
            update.assert_not_called()
            ui.queue_player_portrait("神羽", 2)
            ui.update_dialog("NARR", "神羽被阳明护住。", "#fff")
            update.assert_called_once_with("神羽", 2)
            update.reset_mock()
            ui.queue_player_portrait("神羽", 3)
            ui.update_dialog("旁白", "阳明望向窗外。", "#fff")
            update.assert_not_called()
            ui.record_user_message("我才不要（摊开手）")
            ui.queue_player_portrait("神羽", 4)
            update.assert_called_once_with("神羽", 4)

    def test_presentation_queues_portrait_without_dialogue_or_playback(self):
        from application.chat.handlers.presentation import CharacterDialogUiHandler

        ui = MagicMock()
        playback = MagicMock()
        runtime = SimpleNamespace(
            player_character="神羽",
            read_player_speech=True,
            ui_update_manager=ui,
            ui_playback=SimpleNamespace(
                playback_controller=playback,
                task_done_requested=None,
            ),
        )
        with patch(
            "application.chat.handlers.presentation.get_app_runtime",
            return_value=runtime,
        ):
            CharacterDialogUiHandler().handle(
                PresentationMessage(
                    name="神羽",
                    text="",
                    audio_path="preset.wav",
                    asset_id="2",
                    timeout=0,
                )
            )

        ui.queue_player_portrait.assert_called_once_with("神羽", 1)
        ui.update_dialog.assert_not_called()
        ui.update_sprite.assert_not_called()
        playback.play_and_wait.assert_not_called()

    def test_presentation_plays_enabled_player_speech_without_showing_dialog(self):
        from application.chat.handlers.presentation import CharacterDialogUiHandler

        ui = MagicMock()
        playback = MagicMock()
        playback.play_and_wait.return_value = SimpleNamespace(error="")
        runtime = SimpleNamespace(
            player_character="神羽",
            read_player_speech=True,
            ui_update_manager=ui,
            ui_playback=SimpleNamespace(
                playback_controller=playback,
                task_done_requested=None,
            ),
        )
        with (
            patch(
                "application.chat.handlers.presentation.get_app_runtime",
                return_value=runtime,
            ),
            patch("application.chat.handlers.presentation.get_character_by_name", return_value=None),
            patch("application.chat.handlers.presentation.Path.exists", return_value=True),
        ):
            CharacterDialogUiHandler().handle(
                PresentationMessage(
                    name="神羽",
                    text="我才不要",
                    audio_path="generated.wav",
                    asset_id=None,
                    timeout=0,
                )
            )

        ui.update_dialog.assert_not_called()
        playback.play_and_wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
