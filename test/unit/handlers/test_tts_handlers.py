"""Unit tests for TTS message handlers — can_handle, dispatch routing."""

import pytest
from unittest.mock import MagicMock

from sdk.messages import LLMDialogMessage
from core.handlers.handler_registry import TtsMessageDispatcher
from core.handlers.tts_message_handler import (
    DefaultCharacterTtsHandler,
    BgmTtsHandler,
    CgTtsHandler,
    get_tts_handlers,
)


class TestDefaultCharacterTtsHandler:
    def test_can_handle_any_message(self, mock_app_runtime):
        """DefaultCharacterTtsHandler is the catch-all — always returns True."""
        handler = DefaultCharacterTtsHandler()
        msg = LLMDialogMessage(name="TestChar", text="Hello", asset_id="0")
        assert handler.can_handle(msg) is True


class TestSpecializedHandlers:
    def test_bgm_handler_matches_bgm(self, mock_app_runtime):
        handler = BgmTtsHandler()
        msg = LLMDialogMessage(name="BGM", text="...", asset_id="0")
        assert handler.can_handle(msg) is True

    def test_cg_handler_matches_cg(self, mock_app_runtime):
        handler = CgTtsHandler()
        msg = LLMDialogMessage(name="CG", text="...", asset_id="0")
        assert handler.can_handle(msg) is True

    def test_cg_handler_generates_image_via_t2i(self, mock_app_runtime, tmp_path):
        handler = CgTtsHandler()
        msg = LLMDialogMessage(name="CG", text="wide anime scene", asset_id="-1")
        out_path = tmp_path / "cg.png"
        mock_app_runtime.t2i_manager = MagicMock()
        mock_app_runtime.t2i_manager.t2i.return_value = str(out_path)

        mock_app_runtime.tts_queue.put(msg)
        handler.handle(msg)

        mock_app_runtime.t2i_manager.t2i.assert_called_once_with(
            prompt="wide anime scene",
            prompt_processor=None,
            image_size="landscape",
        )
        out = mock_app_runtime.audio_path_queue.get_nowait()
        assert out.name == "CG"
        assert out.text == "wide anime scene"
        assert out.audio_path == str(out_path)
        assert out.is_system_message is True

    def test_handler_chain_has_default_last(self):
        handlers = list(get_tts_handlers())
        assert len(handlers) > 0
        assert isinstance(handlers[-1], DefaultCharacterTtsHandler)


class TestTtsMessageDispatcher:
    def test_dispatcher_requires_at_least_one_handler(self):
        with pytest.raises(ValueError, match="至少需要一个"):
            TtsMessageDispatcher([])

    def test_dispatcher_calls_first_matching_handler(self):
        handler1 = MagicMock()
        handler1.can_handle.return_value = True
        handler2 = MagicMock()
        handler2.can_handle.return_value = True

        dispatcher = TtsMessageDispatcher([handler1, handler2])
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

        dispatcher = TtsMessageDispatcher([handler1, handler2])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")
        dispatcher.dispatch(msg)

        handler1.handle.assert_not_called()
        handler2.handle.assert_called_once()

    def test_dispatcher_raises_when_no_handler_matches(self):
        handler = MagicMock()
        handler.can_handle.return_value = False
        dispatcher = TtsMessageDispatcher([handler])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")

        with pytest.raises(RuntimeError, match="无 TTS handler 匹配"):
            dispatcher.dispatch(msg)

    def test_init_handlers_called_on_all(self):
        handler1 = MagicMock()
        handler2 = MagicMock()
        dispatcher = TtsMessageDispatcher([handler1, handler2])
        dispatcher.init_handlers()
        handler1.init.assert_called_once()
        handler2.init.assert_called_once()
