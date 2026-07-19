"""Unit tests for UI output message handlers — can_handle routing logic."""

from types import SimpleNamespace
import pytest
from unittest.mock import MagicMock, patch

from sdk.messages import TTSOutputMessage
from core.handlers.ui_message_handler import (
    ChainOfThoughtUiHandler,
    OptionsUiHandler,
    NumericUiHandler,
    SceneUiHandler,
    BgmUiHandler,
    CgUiHandler,
    SystemMiscUiHandler,
    CharacterDialogUiHandler,
    get_ui_output_handlers,
)


def _tts_out(name, text="", audio_path="", is_system=True, asset_id="-1"):
    return TTSOutputMessage(
        audio_path=audio_path,
        name=name,
        text=text,
        asset_id=asset_id,
        is_system_message=is_system,
    )


class TestChainOfThoughtUiHandler:
    def test_matches_cot_system(self):
        h = ChainOfThoughtUiHandler()
        assert h.can_handle(_tts_out("COT", is_system=True)) is True
        assert h.can_handle(_tts_out("思维链", is_system=True)) is True

    def test_rejects_non_system(self):
        h = ChainOfThoughtUiHandler()
        assert h.can_handle(_tts_out("COT", is_system=False)) is False

    def test_rejects_non_cot(self):
        h = ChainOfThoughtUiHandler()
        assert h.can_handle(_tts_out("NARR", is_system=True)) is False


class TestOptionsUiHandler:
    def test_matches_choice_system(self):
        h = OptionsUiHandler()
        assert h.can_handle(_tts_out("CHOICE", is_system=True)) is True
        assert h.can_handle(_tts_out("选项", is_system=True)) is True

    def test_rejects_non_system(self):
        h = OptionsUiHandler()
        assert h.can_handle(_tts_out("CHOICE", is_system=False)) is False
        assert h.can_handle(_tts_out("选项", is_system=False)) is False

    def test_rejects_non_choice(self):
        h = OptionsUiHandler()
        assert h.can_handle(_tts_out("NARR", is_system=True)) is False


class TestNumericUiHandler:
    def test_matches_stat_system(self):
        h = NumericUiHandler()
        assert h.can_handle(_tts_out("STAT", is_system=True)) is True
        assert h.can_handle(_tts_out("数值", is_system=True)) is True

    def test_rejects_non_system(self):
        h = NumericUiHandler()
        assert h.can_handle(_tts_out("STAT", is_system=False)) is False

    def test_rejects_non_stat(self):
        h = NumericUiHandler()
        assert h.can_handle(_tts_out("SCENE", is_system=True)) is False


class TestSceneUiHandler:
    def test_matches_scene_system(self):
        h = SceneUiHandler()
        assert h.can_handle(_tts_out("SCENE", is_system=True)) is True
        assert h.can_handle(_tts_out("场景", is_system=True)) is True

    def test_rejects_non_system(self):
        h = SceneUiHandler()
        assert h.can_handle(_tts_out("SCENE", is_system=False)) is False

    def test_rejects_non_scene(self):
        h = SceneUiHandler()
        assert h.can_handle(_tts_out("BGM", is_system=True)) is False


class TestBgmUiHandler:
    def test_matches_bgm_system(self):
        h = BgmUiHandler()
        assert h.can_handle(_tts_out("bgm", is_system=True)) is True
        assert h.can_handle(_tts_out("BGM", is_system=True)) is True

    def test_rejects_non_system(self):
        h = BgmUiHandler()
        assert h.can_handle(_tts_out("bgm", is_system=False)) is False

    def test_rejects_non_bgm(self):
        h = BgmUiHandler()
        assert h.can_handle(_tts_out("CG", is_system=True)) is False


class TestCgUiHandler:
    def test_matches_cg_system(self):
        h = CgUiHandler()
        assert h.can_handle(_tts_out("CG", is_system=True)) is True
        assert h.can_handle(_tts_out("cg", is_system=True)) is True

    def test_rejects_non_system(self):
        h = CgUiHandler()
        assert h.can_handle(_tts_out("CG", is_system=False)) is False

    def test_rejects_non_cg(self):
        h = CgUiHandler()
        assert h.can_handle(_tts_out("bgm", is_system=True)) is False


class TestSystemMiscUiHandler:
    def test_matches_narr_system(self):
        h = SystemMiscUiHandler()
        assert h.can_handle(_tts_out("NARR", is_system=True)) is True
        assert h.can_handle(_tts_out("旁白", is_system=True)) is True

    def test_rejects_non_system(self):
        h = SystemMiscUiHandler()
        assert h.can_handle(_tts_out("NARR", is_system=False)) is False

    def test_skips_system_ui_skip_members(self):
        h = SystemMiscUiHandler()
        # SYSTEM_UI_SKIP uses raw alias strings (mostly lowercase codes);
        # BgmUiHandler catches bgm before SystemMisc in the dispatcher chain.
        for name in ("COT", "思维链", "CHOICE", "选项", "STAT", "数值", "SCENE", "场景", "bgm", "cg", "CG"):
            assert h.can_handle(_tts_out(name, is_system=True)) is False, f"Should skip {name}"

    def test_matches_unknown_system_names(self):
        h = SystemMiscUiHandler()
        assert h.can_handle(_tts_out("SomeSystemThing", is_system=True)) is True


class TestCharacterDialogUiHandler:
    def test_matches_non_system_messages(self):
        h = CharacterDialogUiHandler()
        assert h.can_handle(_tts_out("Alice", is_system=False)) is True
        assert h.can_handle(_tts_out("Bob", is_system=False)) is True

    def test_rejects_system_messages(self):
        h = CharacterDialogUiHandler()
        assert h.can_handle(_tts_out("Alice", is_system=True)) is False
        assert h.can_handle(_tts_out("NARR", is_system=True)) is False

    def test_emits_tts_play_when_audio_starts(self, tmp_path):
        audio_path = tmp_path / "alice.wav"
        audio_path.write_bytes(b"wav")

        ui = MagicMock()
        playback = SimpleNamespace(
            task_done_requested=SimpleNamespace(
                is_set=lambda: False,
                wait=lambda timeout=None: False,
            ),
            dialog_channel=MagicMock(),
            current_audio_path=None,
        )
        playback.dialog_channel.get_busy.side_effect = [True, False]
        runtime = SimpleNamespace(ui_update_manager=ui, ui_playback=playback)
        sound = MagicMock()

        class _Character:
            color = "#abcdef"
            speech_volume = 0.8

        handler = CharacterDialogUiHandler()
        out = TTSOutputMessage(
            audio_path=audio_path.as_posix(),
            name="Alice",
            text="Hello",
            asset_id="1",
            is_system_message=False,
            is_final_segment=True,
        )

        with patch("core.handlers.ui_message_handler.get_app_runtime", return_value=runtime), patch(
            "core.handlers.ui_message_handler.get_character_by_name", return_value=_Character()
        ), patch("core.handlers.ui_message_handler.time.sleep", return_value=None), patch(
            "core.handlers.ui_message_handler.pygame.mixer.Sound", return_value=sound
        ), patch("core.handlers.ui_message_handler.get_asr_log", return_value=MagicMock()), patch(
            "sdk.logging.timing.tracker.stop_cross", return_value=None
        ):
            handler.handle(out)

        ui.hide_busy_bar.assert_called_once_with()
        ui.post_tts_play.assert_called_once_with("Alice", audio_path.as_posix())
        ui.post_pause_asr.assert_called_once_with()
        ui.post_llm_reply_finished.assert_not_called()
        playback.dialog_channel.play.assert_called_once_with(sound)
        sound.set_volume.assert_called_once_with(0.8)
        assert playback.current_audio_path is None


class TestHandlerChainAssembly:
    def test_get_ui_output_handlers_returns_all_eight(self):
        handlers = list(get_ui_output_handlers())
        assert len(handlers) == 8

    def test_specialized_handlers_before_generic(self):
        """Specialized handlers must come before catch-all handlers (SystemMisc, CharacterDialog)."""
        handlers = list(get_ui_output_handlers())
        # Check that no catch-all appears before specialized ones
        types = [type(h) for h in handlers]
        misc_idx = types.index(SystemMiscUiHandler)
        char_idx = types.index(CharacterDialogUiHandler)
        # OptionsUiHandler (specialized) should be before SystemMiscUiHandler (generic)
        opt_idx = types.index(OptionsUiHandler)
        assert opt_idx < misc_idx
        assert opt_idx < char_idx

    def test_character_dialog_handler_is_last(self):
        handlers = list(get_ui_output_handlers())
        assert isinstance(handlers[-1], CharacterDialogUiHandler)
