"""Run with runtime/python.exe -m unittest test.unit.application.chat.test_player_control."""

import json
import unittest
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from application.chat.player_control import PLAYER_CONTROL_ENV, player_speech, resolve_player
from application.chat.handlers.dialog_media import CharacterMediaHandler
from application.chat.dialog_media import ResolvedSpriteAsset
from application.chat.ui_updates import StreamingUIUpdateManager
from application.runtime.event_sink import fold_event_into_snapshot, make_empty_chat_snapshot
from config.schema import Character, PortraitCrop, Sprite
from sdk.messages import LLMDialogMessage


class PlayerControlTests(unittest.TestCase):
    def test_generation_cast_excludes_player_and_saved_template_is_reassigned(self):
        from i18n import init_i18n
        init_i18n('zh_CN')
        from ai.llm.template_generator import TemplateGenerator, _T
        from application.chat.player_control import player_runtime_template
        player = SimpleNamespace(name='神羽', sprites=[{}], emotion_tags='立绘1：笑', character_setting='用户独有资料', character_brief='用户简述')
        npc = SimpleNamespace(name='阳明', sprites=[{}], emotion_tags='立绘1：平常', character_setting='其他角色资料', character_brief='')
        generator = object.__new__(TemplateGenerator)
        generator.resolve_chat_template_characters = lambda names: [(c.name, c) for c in (player, npc) if c.name in names]
        generator._get_output_contract_patches = lambda: []
        with patch('ai.llm.template_generator._format_llm_tools_block', return_value=''), patch('ai.llm.template_generator._target_voice_display_name', return_value='中文'):
            legacy, _ = generator.generate_chat_template(['神羽', '阳明'], '', False, False, False)
            current, _ = generator.generate_chat_template(['神羽', '阳明'], '', False, False, False, player_character='神羽')
            config = SimpleNamespace(
                get_character_by_name=lambda name: player,
                config=SimpleNamespace(
                    system_config=SimpleNamespace(voice_language="ja")
                ),
            )
            runtime = player_runtime_template(
                config, legacy, ['神羽', '阳明'], '神羽', read_speech=True
            )
        for template in (current, runtime):
            self.assertEqual(template.splitlines()[0], _T('preamble', names='阳明').strip())
            self.assertNotIn(_T('profile_for', name='神羽'), template)
            self.assertNotIn(_T('sprites_count', name='神羽', n=1), template)
        self.assertIn('用户独有资料', runtime)
        self.assertIn('player_portrait', runtime)
        self.assertIn('"player_speech":{"translate"', runtime)
        self.assertIn('dialog数组禁止包含神羽', runtime)


    def test_independent_portrait_restores_without_player_dialogue(self):
        from application.chat.dialog_media.replay import latest_media_dialogs
        content = json.dumps({'dialog': [{'character_name': '阳明', 'sprite': '1', 'speech': '你想怎么做？'}], 'player_portrait': {'sprite': '2'}})
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽'})}):
            dialogs = latest_media_dialogs([{'role': 'assistant', 'content': content}], opencc=SimpleNamespace(convert=lambda text: text))
        player = next(dialog for dialog in dialogs if dialog.name == '神羽')
        self.assertEqual(player.text, '')
        self.assertEqual(player.asset_id, '2')


    def test_literal_speech_excludes_actions_and_thoughts(self):
        self.assertEqual(player_speech('我才不要（摊开手）【心里松了口气】'), '我才不要')
        self.assertEqual(player_speech('别过来！\n心理活动：其实有些害怕'), '别过来！')
        self.assertEqual(player_speech('（沉默）【犹豫】'), '')

    def test_selection_must_be_in_cast(self):
        config = SimpleNamespace(get_character_by_name=lambda name: SimpleNamespace(name='神羽'))
        self.assertEqual(resolve_player(config, ['神羽'], '神羽'), '神羽')
        with self.assertRaises(ValueError):
            resolve_player(config, ['阳明'], '神羽')

    def test_saved_history_is_complete_without_player_filtering(self):
        from application.chat.runtime_process import _serialize_history_entries_from_messages
        messages = [{'role': 'user', 'content': '我才不要（摊开手）'}, {'role': 'assistant', 'content': ''}]
        dialogue = [{'character_name': '神羽', 'speech': '误写的台词'}, {'character_name': '阳明', 'speech': '小心！'}]
        with patch('application.chat.runtime_process.parse_assistant_dialog_content', return_value=dialogue):
            entries = _serialize_history_entries_from_messages(messages, '神羽')
        self.assertEqual([entry['text'] for entry in entries], ['神羽: 我才不要（摊开手）', '神羽: 误写的台词', '阳明: 小心！'])

    def test_independent_portrait_works_for_arbitrarily_split_streams(self):
        from core.messaging.stream_parser import LlmResponseStreamParser
        content = json.dumps({'player_speech': {'translate': '嫌だ。'}, 'player_portrait': {'sprite': '2', 'vibe': '犹豫'}, 'dialog': [{'character_name': '阳明', 'sprite': '1', 'speech': '你想怎么做？'}]}, ensure_ascii=False)
        for size in [1, 7, len(content)]:
            parser = LlmResponseStreamParser(player_name='神羽', player_speech='我才不要')
            messages = []
            for offset in range(0, len(content), size):
                messages.extend(parser.feed(content[offset:offset + size]))
            self.assertFalse(parser.has_errors, parser.last_error)
            self.assertEqual(
                [(m.name, m.text, m.translate) for m in messages],
                [('神羽', '我才不要', '嫌だ。'), ('神羽', '', ''), ('阳明', '你想怎么做？', '')],
            )
            self.assertTrue(messages[0]._player_input)

    def test_portrait_has_no_stage_slot_and_uses_sprite_override(self):
        crop = PortraitCrop(x=0.4, y=0.3, zoom=2)
        character = Character.model_construct(name='神羽', sprites=[Sprite.model_construct(path='face.png', portrait_crop=crop)])
        sink = MagicMock()
        sink.media_url.side_effect = lambda path: path
        ui = StreamingUIUpdateManager(sink, chat_history=[])
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽'})}), patch('application.chat.ui_updates.get_character_by_name', return_value=character):
            ui.update_sprite('神羽', 0)
        event = sink.emit.call_args.args[0]
        self.assertEqual(event['type'], 'player.portrait.show')
        self.assertEqual(event['crop'], crop.model_dump())
        self.assertFalse(ui._sprite_lru)
        snapshot = fold_event_into_snapshot(make_empty_chat_snapshot(), {**event, 'seq': 1})
        snapshot = fold_event_into_snapshot(snapshot, {'type': 'background.change', 'url': 'new.png', 'seq': 2})
        self.assertEqual(snapshot['playerPortrait']['crop'], crop.model_dump())
        self.assertEqual(snapshot['sprites'], [])

    def media_runtime(self):
        resolver = MagicMock()
        resolver.candidates.return_value = []
        resolver.resolve.return_value = ResolvedSpriteAsset(asset_id='1', index=0, value={'path': 'face.png'}, path='face.png', voice_type='preset', voice_path='fixed.wav', voice_text='不该被朗读')
        tts = MagicMock()
        tts.generate.return_value = ['generated.wav']
        runtime = SimpleNamespace(
            opencc=SimpleNamespace(convert=lambda value: value),
            config=MagicMock(), ui_update_manager=MagicMock(),
            presentation_queue=Queue(), tts_manager=object(),
        )
        return CharacterMediaHandler(sprite_resolver=resolver, tts_generation_strategy=tts), runtime, tts

    def test_llm_player_output_cannot_speak_even_with_forged_flag(self):
        handler, runtime, tts = self.media_runtime()
        message = LLMDialogMessage(character_name='神羽', speech='模型误写台词', sprite='1', player_input=True, _player_input=True)
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽'})}), patch('application.chat.handlers.dialog_media.get_app_runtime', return_value=runtime):
            handler.handle(message)
        tts.generate.assert_not_called()
        runtime.ui_update_manager.update_sprite.assert_not_called()
        output = runtime.presentation_queue.get_nowait()
        self.assertEqual(output.name, '神羽')
        self.assertEqual(output.text, '')
        self.assertEqual(output.audio_path, '')

    def test_expression_waits_for_related_narration_and_is_discarded_for_npc(self):
        ui = StreamingUIUpdateManager(MagicMock(), chat_history=[])
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽'})}), patch.object(ui, 'update_sprite') as update:
            ui.queue_player_portrait('神羽', 1)
            update.assert_not_called()
            ui.update_dialog('阳明', '神羽，小心！', '#fff', False)
            update.assert_not_called()
            ui.update_dialog('NARR', '神羽摊开手。', '#fff')
            update.assert_not_called()
            ui.queue_player_portrait('神羽', 2)
            ui.update_dialog('NARR', '神羽被阳明护住。', '#fff')
            update.assert_called_once_with('神羽', 2)
            update.reset_mock()
            ui.queue_player_portrait('神羽', 3)
            ui.update_dialog('旁白', '阳明望向窗外。', '#fff')
            update.assert_not_called()
            ui.record_user_message('我才不要（摊开手）')
            ui.queue_player_portrait('神羽', 4)
            update.assert_called_once_with('神羽', 4)

    def test_presentation_queues_portrait_without_dialogue_or_playback(self):
        from application.chat.handlers.presentation import CharacterDialogUiHandler
        from sdk.messages import PresentationMessage
        ui = MagicMock()
        runtime = SimpleNamespace(ui_update_manager=ui, ui_playback=MagicMock())
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽'})}), patch('application.chat.handlers.presentation.get_app_runtime', return_value=runtime):
            CharacterDialogUiHandler().handle(PresentationMessage(name='神羽', text='', audio_path='', asset_id='2', timeout=0))
        ui.queue_player_portrait.assert_called_once_with('神羽', 1)
        ui.update_dialog.assert_not_called()
        ui.update_sprite.assert_not_called()
        runtime.ui_playback.playback_controller.play_and_wait.assert_not_called()

    def test_actual_player_speech_never_uses_preset_audio(self):
        handler, runtime, tts = self.media_runtime()
        message = LLMDialogMessage(
            name='神羽', text='我才不要（摊开手）', translate='嫌だ。'
        )
        message._player_input = True
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽', 'readSpeech': True})}), patch('application.chat.handlers.dialog_media.get_app_runtime', return_value=runtime):
            handler.handle(message)
        request = tts.generate.call_args.args[0]
        self.assertEqual(request.message.text, '我才不要')
        self.assertEqual(request.message.translate, '嫌だ。')
        self.assertEqual(request.sprite.voice_path, '')
        output = runtime.presentation_queue.get_nowait()
        self.assertEqual(output.text, '')
        self.assertEqual(output.audio_path, 'generated.wav')

    def test_player_speech_without_llm_translation_is_not_synthesized(self):
        handler, runtime, tts = self.media_runtime()
        message = LLMDialogMessage(name='神羽', text='我才不要')
        message._player_input = True
        with patch.dict('os.environ', {PLAYER_CONTROL_ENV: json.dumps({'name': '神羽', 'readSpeech': True})}), patch('application.chat.handlers.dialog_media.get_app_runtime', return_value=runtime):
            handler.handle(message)
        tts.generate.assert_not_called()
        self.assertTrue(runtime.presentation_queue.empty())


if __name__ == '__main__':
    unittest.main()
