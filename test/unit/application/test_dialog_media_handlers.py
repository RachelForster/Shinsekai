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

    def test_none_asset_id_uses_default_sprite_and_continues_tts(
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
        assert output.asset_id == "-1"
        assert output.audio_path == "voice.wav"
        assert output.is_system_message is False
        assert output.effect == ""


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
