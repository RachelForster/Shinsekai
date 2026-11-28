from types import SimpleNamespace
from unittest.mock import MagicMock

from application.chat.dialog_media import (
    DefaultTtsGenerationStrategy,
    ResolvedSpriteAsset,
    TtsGenerationRequest,
)
from sdk.messages import LLMDialogMessage


def test_bound_voice_profile_uses_weights_and_prefers_valid_sprite_reference(tmp_path):
    gpt, sovits, reference, override = (
        tmp_path / name for name in ("voice.ckpt", "voice.pth", "voice.wav", "sprite.wav")
    )
    for path in (gpt, sovits, reference, override):
        path.write_bytes(b"asset")
    voice = SimpleNamespace(
        gpt_model_path=str(gpt), sovits_model_path=str(sovits),
        refer_audio_path=str(reference), prompt_text="profile prompt",
        prompt_lang="ja", speech_speed=0.9,
    )
    manager = MagicMock()
    runtime = SimpleNamespace(
        tts_manager=manager,
        text_processor=None,
        config=SimpleNamespace(config=SimpleNamespace(api_config=SimpleNamespace(
            tts_provider="gpt-sovits", gpt_sovits_url="http://localhost:9880",
        ))),
    )
    character = SimpleNamespace(voice_profiles={"mujina": voice})
    strategy = DefaultTtsGenerationStrategy()
    for sprite_audio, expected_audio, expected_text in (
        (override, override, "sprite prompt"),
        (tmp_path / "missing.wav", reference, "profile prompt"),
    ):
        request = TtsGenerationRequest(
            runtime=runtime,
            character=character,
            character_name="Alice",
            message=LLMDialogMessage(name="Alice", text="Hello", asset_id="1"),
            sprite=ResolvedSpriteAsset(
                asset_id="1", value={"voice_profile_id": "mujina"}, voice_type="reference",
                voice_path=str(sprite_audio), voice_text="sprite prompt",
            ),
        )
        list(strategy.generate(request))
        assert manager.switch_model.call_args.args[0]["gpt_model_path"] == gpt.as_posix()
        assert manager.switch_model.call_args.args[0]["sovits_model_path"] == sovits.as_posix()
        assert manager.generate_tts.call_args.kwargs["ref_audio_path"] == expected_audio.as_posix()
        assert manager.generate_tts.call_args.kwargs["prompt_text"] == expected_text
