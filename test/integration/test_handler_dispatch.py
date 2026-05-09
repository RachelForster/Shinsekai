"""Integration tests: full handler chain assembly and dispatch routing.

Real handler handle() methods have deep dependencies (ConfigManager singleton,
TTS manager, pygame, etc.) so this file tests chain assembly order and
dispatcher routing logic with mocks.  Handler can_handle logic is covered
extensively in unit/handlers/.
"""

import pytest
from unittest.mock import MagicMock

from sdk.messages import LLMDialogMessage, TTSOutputMessage
from core.handlers.handler_registry import (
    TtsMessageDispatcher,
    UiOutputMessageDispatcher,
    default_tts_handler_chain,
    default_ui_output_handler_chain,
)
from core.handlers.tts_message_handler import (
    ChainOfThoughtTtsHandler,
    SystemDialogTtsHandler,
    BgmTtsHandler,
    CgTtsHandler,
    DefaultCharacterTtsHandler,
)
from core.handlers.ui_message_handler import (
    OptionsUiHandler,
    NumericUiHandler,
    SceneUiHandler,
    BgmUiHandler,
    CgUiHandler,
    ChainOfThoughtUiHandler,
    SystemMiscUiHandler,
    CharacterDialogUiHandler,
)


@pytest.mark.integration
class TestTTSHandlerChainAssembly:
    def test_default_chain_has_all_builtin_handlers(self):
        chain = default_tts_handler_chain()
        types = [type(h) for h in chain._handlers]
        assert ChainOfThoughtTtsHandler in types
        assert SystemDialogTtsHandler in types
        assert BgmTtsHandler in types
        assert CgTtsHandler in types
        assert DefaultCharacterTtsHandler in types

    def test_specialized_before_default(self):
        chain = default_tts_handler_chain()
        types = [type(h) for h in chain._handlers]
        cot_idx = types.index(ChainOfThoughtTtsHandler)
        sys_idx = types.index(SystemDialogTtsHandler)
        bgm_idx = types.index(BgmTtsHandler)
        cg_idx = types.index(CgTtsHandler)
        default_idx = types.index(DefaultCharacterTtsHandler)
        assert cot_idx < default_idx
        assert sys_idx < default_idx
        assert bgm_idx < default_idx
        assert cg_idx < default_idx

    def test_default_handler_is_last_builtin(self):
        chain = default_tts_handler_chain()
        types = [type(h) for h in chain._handlers]
        # Default may not be absolute last if plugins registered handlers,
        # but it's last among built-in handlers
        builtin_types = [t for t in types if t.__module__.startswith("core.handlers.tts_message_handler")]
        assert builtin_types[-1] == DefaultCharacterTtsHandler

    def test_chain_raises_when_no_handler_matches(self):
        handler = MagicMock()
        handler.can_handle.return_value = False
        chain = TtsMessageDispatcher([handler])
        msg = LLMDialogMessage(name="Whatever", text="...", asset_id="-1")
        with pytest.raises(RuntimeError, match="无 TTS handler 匹配"):
            chain.dispatch(msg)

    def test_dispatcher_short_circuits_on_first_match(self):
        """First matching handler handles, second never called."""
        h1 = MagicMock()
        h1.can_handle.return_value = True
        h2 = MagicMock()
        h2.can_handle.return_value = True
        chain = TtsMessageDispatcher([h1, h2])
        msg = LLMDialogMessage(name="Test", text="Hi", asset_id="0")
        chain.dispatch(msg)
        h1.handle.assert_called_once()
        h2.handle.assert_not_called()


@pytest.mark.integration
class TestUIHandlerChainAssembly:
    def test_default_chain_has_all_builtin_handlers(self):
        chain = default_ui_output_handler_chain()
        types = [type(h) for h in chain._handlers]
        assert OptionsUiHandler in types
        assert NumericUiHandler in types
        assert SceneUiHandler in types
        assert BgmUiHandler in types
        assert CgUiHandler in types
        assert ChainOfThoughtUiHandler in types
        assert SystemMiscUiHandler in types
        assert CharacterDialogUiHandler in types

    def test_specialized_before_generic(self):
        chain = default_ui_output_handler_chain()
        types = [type(h) for h in chain._handlers]
        char_idx = types.index(CharacterDialogUiHandler)
        opt_idx = types.index(OptionsUiHandler)
        scene_idx = types.index(SceneUiHandler)
        cot_idx = types.index(ChainOfThoughtUiHandler)
        assert opt_idx < char_idx
        assert scene_idx < char_idx
        assert cot_idx < char_idx

    def test_builtin_character_dialog_after_all_builtins(self):
        chain = default_ui_output_handler_chain()
        types = [type(h) for h in chain._handlers]
        builtin_types = [t for t in types if t.__module__.startswith("core.handlers.ui_message_handler")]
        assert builtin_types[-1] == CharacterDialogUiHandler

    def test_chain_raises_when_no_handler_matches(self):
        handler = MagicMock()
        handler.can_handle.return_value = False
        chain = UiOutputMessageDispatcher([handler])
        out = TTSOutputMessage(
            audio_path="", name="X", text="", asset_id="-1", is_system_message=True
        )
        with pytest.raises(RuntimeError, match="无 UI handler 匹配"):
            chain.dispatch(out)

    def test_dispatcher_calls_only_first_matching_ui_handler(self):
        h1 = MagicMock()
        h1.can_handle.return_value = True
        h2 = MagicMock()
        h2.can_handle.return_value = True
        chain = UiOutputMessageDispatcher([h1, h2])
        out = TTSOutputMessage(
            audio_path="", name="X", text="", asset_id="-1", is_system_message=False
        )
        chain.dispatch(out)
        h1.handle.assert_called_once()
        h2.handle.assert_not_called()


@pytest.mark.integration
class TestHandlerChainCoordination:
    """Verify that TTS and UI handler chains route matching message types to the right handler type."""

    def test_tts_chain_cot_handler_matches_cot_name(self, mock_app_runtime):
        handler = ChainOfThoughtTtsHandler()
        assert handler.can_handle(LLMDialogMessage(name="COT", text="...", asset_id="-1")) is True

    def test_tts_chain_bgm_handler_matches_bgm_name(self):
        handler = BgmTtsHandler()
        assert handler.can_handle(LLMDialogMessage(name="bgm", text="", asset_id="1")) is True

    def test_tts_chain_cg_handler_matches_cg_name(self):
        handler = CgTtsHandler()
        assert handler.can_handle(LLMDialogMessage(name="CG", text="prompt", asset_id="-1")) is True

    def test_tts_chain_system_dialog_matches_narr_and_choice(self, mock_app_runtime):
        handler = SystemDialogTtsHandler()
        assert handler.can_handle(LLMDialogMessage(name="NARR", text="...", asset_id="-1")) is True
        assert handler.can_handle(LLMDialogMessage(name="CHOICE", text="...", asset_id="-1")) is True

    def test_tts_chain_default_matches_any_character(self):
        handler = DefaultCharacterTtsHandler()
        assert handler.can_handle(LLMDialogMessage(name="Alice", text="...", asset_id="0")) is True
        assert handler.can_handle(LLMDialogMessage(name="Anything", text="...", asset_id="-1")) is True

    def test_ui_chain_option_handler_matches_choice(self):
        handler = OptionsUiHandler()
        out = TTSOutputMessage(audio_path="", name="CHOICE", text="A/B", asset_id="-1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_numeric_handler_matches_stat(self):
        handler = NumericUiHandler()
        out = TTSOutputMessage(audio_path="", name="STAT", text="100", asset_id="-1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_scene_handler_matches_scene(self):
        handler = SceneUiHandler()
        out = TTSOutputMessage(audio_path="", name="SCENE", text="", asset_id="5", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_bgm_handler_matches_bgm(self):
        handler = BgmUiHandler()
        out = TTSOutputMessage(audio_path="/bgm.mp3", name="bgm", text="", asset_id="1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_cg_handler_matches_cg(self):
        handler = CgUiHandler()
        out = TTSOutputMessage(audio_path="/cg.png", name="CG", text="", asset_id="-1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_cot_handler_matches_cot(self):
        handler = ChainOfThoughtUiHandler()
        out = TTSOutputMessage(audio_path="", name="COT", text="thinking", asset_id="-1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_system_misc_matches_narr(self):
        handler = SystemMiscUiHandler()
        out = TTSOutputMessage(audio_path="", name="NARR", text="...", asset_id="-1", is_system_message=True)
        assert handler.can_handle(out) is True

    def test_ui_chain_character_dialog_matches_non_system(self):
        handler = CharacterDialogUiHandler()
        out = TTSOutputMessage(audio_path="", name="Alice", text="Hi", asset_id="0", is_system_message=False)
        assert handler.can_handle(out) is True
