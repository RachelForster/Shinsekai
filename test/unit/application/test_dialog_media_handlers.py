"""Unit tests for the application dialog-media handler chain."""

from unittest.mock import MagicMock

import pytest

from sdk.messages import LLMDialogMessage
from application.chat.handlers.registry import DialogMediaDispatcher
from application.chat.handlers.dialog_media import (
    CharacterMediaHandler,
    BgmMediaHandler,
    CgMediaHandler,
    get_dialog_media_handlers,
)


class TestCharacterMediaHandler:
    def test_can_handle_any_message(self, mock_app_runtime):
        """CharacterMediaHandler is the catch-all — always returns True."""
        handler = CharacterMediaHandler()
        msg = LLMDialogMessage(name="TestChar", text="Hello", asset_id="0")
        assert handler.can_handle(msg) is True

    def test_none_asset_id_skips_sprite_update_and_continues_tts(
        self, mock_app_runtime
    ):
        runtime = mock_app_runtime
        runtime.tts_manager = MagicMock()
        runtime.tts_manager.generate_tts.return_value = "voice.wav"

        CharacterMediaHandler().handle(
            LLMDialogMessage(name="TestChar", text="Hello", asset_id=None)
        )

        runtime.tts_manager.generate_tts.assert_called_once()
        output = runtime.presentation_queue.get_nowait()
        assert output.name == "TestChar"
        assert output.text == "Hello"
        assert output.asset_id is None
        assert output.audio_path == "voice.wav"
        assert output.is_system_message is False
        assert output.effect == ""

    @pytest.mark.parametrize("continuous_enabled", [False, True])
    @pytest.mark.parametrize(
        "scenario",
        ["tts_configured", "preset_no_manager", "fallback_no_manager"],
    )
    def test_character_speech_suppression_and_preservation(
        self, mock_app_runtime, tmp_path, continuous_enabled: bool, scenario: str
    ):
        runtime = mock_app_runtime
        runtime.config.config.system_config.asr_continuous_during_reply_experimental_enabled = (
            continuous_enabled
        )
        runtime.ui_update_manager.post_busy_bar = MagicMock()

        char = runtime.config.get_character_by_name("TestChar")
        original_refer = char.refer_audio_path
        original_sovits = char.sovits_model_path

        preset_file = tmp_path / "preset.wav"
        preset_file.write_bytes(b"preset-audio")
        fallback_file = tmp_path / "fallback.wav"
        fallback_file.write_bytes(b"fallback-audio")

        if scenario == "tts_configured":
            runtime.tts_manager = MagicMock()
            runtime.tts_manager.generate_tts.return_value = "synthesized.wav"
            char.sprites = [
                {
                    "path": "test.png",
                    "voice_type": "reference",
                    "voice_path": str(preset_file),
                    "voice_text": "Ref Line",
                }
            ]
        elif scenario == "preset_no_manager":
            runtime.tts_manager = None
            char.sprites = [
                {
                    "path": "test.png",
                    "voice_type": "preset",
                    "voice_path": str(preset_file),
                    "voice_text": "Preset Line",
                }
            ]
        else:  # fallback_no_manager
            runtime.tts_manager = None
            char.sprites = [
                {
                    "path": "test.png",
                    "voice_type": "fallback",
                    "voice_path": str(fallback_file),
                    "voice_text": "",
                }
            ]

        original_sprite_voice_type = char.sprites[0]["voice_type"]
        original_sprite_voice_path = char.sprites[0]["voice_path"]

        handler = CharacterMediaHandler()
        msg = LLMDialogMessage(name="TestChar", text="Hello", asset_id="1", effect="shake")
        handler.handle(msg)

        # Saved voice settings remain intact
        assert char.refer_audio_path == original_refer
        assert char.sovits_model_path == original_sovits
        assert char.sprites[0]["voice_type"] == original_sprite_voice_type
        assert char.sprites[0]["voice_path"] == original_sprite_voice_path

        output = runtime.presentation_queue.get_nowait()
        assert output.name == "TestChar"
        assert output.asset_id == "1"
        assert output.effect == "shake"
        assert output.is_system_message is False
        assert output.is_final_segment is True

        if continuous_enabled:
            # When continuous ASR is enabled: empty audio, no synth, no busy notification
            assert output.audio_path == ""
            if scenario == "preset_no_manager":
                assert output.text == "Preset Line"
            else:
                assert output.text == "Hello"
            if runtime.tts_manager is not None:
                runtime.tts_manager.generate_tts.assert_not_called()
            runtime.ui_update_manager.post_busy_bar.assert_not_called()
        else:
            # Default/false behavior preserved
            if scenario == "tts_configured":
                assert output.audio_path == "synthesized.wav"
                assert output.text == "Hello"
                runtime.tts_manager.generate_tts.assert_called_once()
                runtime.ui_update_manager.post_busy_bar.assert_called_once()
            elif scenario == "preset_no_manager":
                assert output.audio_path == preset_file.resolve().as_posix()
                assert output.text == "Preset Line"
                runtime.ui_update_manager.post_busy_bar.assert_not_called()
            else:  # fallback_no_manager
                assert output.audio_path == fallback_file.resolve().as_posix()
                assert output.text == "Hello"
                runtime.ui_update_manager.post_busy_bar.assert_not_called()


class TestSpecializedHandlers:
    def test_bgm_handler_matches_bgm(self, mock_app_runtime):
        handler = BgmMediaHandler()
        msg = LLMDialogMessage(name="BGM", text="...", asset_id="0")
        assert handler.can_handle(msg) is True

    def test_cg_handler_matches_cg(self, mock_app_runtime):
        handler = CgMediaHandler()
        msg = LLMDialogMessage(name="CG", text="...", asset_id="0")
        assert handler.can_handle(msg) is True

    def test_handler_chain_has_default_last(self):
        handlers = list(get_dialog_media_handlers())
        assert len(handlers) > 0
        assert isinstance(handlers[-1], CharacterMediaHandler)


class TestDialogMediaDispatcher:
    def test_dispatcher_requires_at_least_one_handler(self):
        with pytest.raises(ValueError, match="至少需要一个"):
            DialogMediaDispatcher([])

    def test_dispatcher_calls_first_matching_handler(self):
        handler1 = MagicMock()
        handler1.can_handle.return_value = True
        handler2 = MagicMock()
        handler2.can_handle.return_value = True

        dispatcher = DialogMediaDispatcher([handler1, handler2])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")
        dispatcher.dispatch(msg)

        handler1.pre_process.assert_called_once()
        handler1.handle.assert_called_once()
        handler1.post_process.assert_called_once()
        # handler2 should NOT be called since handler1 matched first
        handler2.handle.assert_not_called()

    def test_dispatcher_skips_non_matching(self):
        handler1 = MagicMock()
        handler1.can_handle.return_value = False
        handler2 = MagicMock()
        handler2.can_handle.return_value = True

        dispatcher = DialogMediaDispatcher([handler1, handler2])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")
        dispatcher.dispatch(msg)

        handler1.handle.assert_not_called()
        handler2.handle.assert_called_once()

    def test_dispatcher_raises_when_no_handler_matches(self):
        handler = MagicMock()
        handler.can_handle.return_value = False
        dispatcher = DialogMediaDispatcher([handler])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")

        with pytest.raises(RuntimeError, match="无 dialog media handler 匹配"):
            dispatcher.dispatch(msg)

    def test_init_handlers_called_on_all(self):
        handler1 = MagicMock()
        handler2 = MagicMock()
        dispatcher = DialogMediaDispatcher([handler1, handler2])
        dispatcher.init_handlers()
        handler1.init.assert_called_once()
        handler2.init.assert_called_once()
