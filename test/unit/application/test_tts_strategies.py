"""Tests for replaceable sprite lookup and TTS generation strategies."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from application.chat.handlers.tts import DefaultCharacterTtsHandler
from application.chat.tts import (
    ConfigSpriteLookupStrategy,
    DefaultTtsGenerationStrategy,
    SpriteLookupRequest,
    SpriteMatch,
    TtsGenerationRequest,
)
from sdk.messages import LLMDialogMessage, TTSOutputMessage


def _character(**overrides):
    values = {
        "name": "Alice",
        "sprites": [],
        "sovits_model_path": "model.pth",
        "gpt_model_path": "model.ckpt",
        "refer_audio_path": "reference.wav",
        "prompt_text": "reference text",
        "prompt_lang": "en",
        "speech_speed": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_config_sprite_lookup_resolves_message_asset_and_voice_metadata(tmp_path):
    character = _character(
        sprites=[
            {
                "path": "happy.png",
                "voice_type": "preset",
                "voice_path": "happy.wav",
                "voice_text": "A happy line",
            }
        ]
    )
    request = SpriteLookupRequest(
        character=character,
        message=LLMDialogMessage(name="Alice", text="Hello", asset_id="1"),
    )

    match = ConfigSpriteLookupStrategy(tmp_path / "missing.yaml").lookup(request)

    assert match.found is True
    assert match.asset_id == "1"
    assert match.index == 0
    assert match.sprite is character.sprites[0]
    assert match.voice_type == "preset"
    assert match.voice_path == "happy.wav"
    assert match.voice_text == "A happy line"


def test_config_sprite_lookup_refreshes_mutable_voice_metadata_from_yaml(tmp_path):
    characters_path = tmp_path / "characters.yaml"
    characters_path.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Alice",
                    "sprites": [
                        {
                            "voice_type": "reference",
                            "voice_path": "fresh.wav",
                            "voice_text": "Fresh text",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    character = _character(
        sprites=[
            {
                "path": "happy.png",
                "voice_type": "preset",
                "voice_path": "stale.wav",
                "voice_text": "Stale text",
            }
        ]
    )

    match = ConfigSpriteLookupStrategy(characters_path).lookup(
        SpriteLookupRequest(
            character=character,
            message=LLMDialogMessage(name="Alice", text="Hello", asset_id="1"),
        )
    )

    assert match.voice_type == "reference"
    assert match.voice_path == "fresh.wav"
    assert match.voice_text == "Fresh text"


def test_default_tts_generation_uses_fixed_sprite_voice_without_synthesis(tmp_path):
    voice_path = tmp_path / "preset.wav"
    voice_path.write_bytes(b"audio")
    manager = MagicMock()
    runtime = SimpleNamespace(tts_manager=manager)
    request = TtsGenerationRequest(
        runtime=runtime,
        character=_character(),
        character_name="Alice",
        message=LLMDialogMessage(name="Alice", text="Hello", asset_id="1"),
        sprite=SpriteMatch(
            asset_id="1",
            index=0,
            sprite={},
            voice_type="preset",
            voice_path=str(voice_path),
            voice_text="Recorded line",
        ),
    )

    outputs = list(DefaultTtsGenerationStrategy().generate(request))

    assert len(outputs) == 1
    assert outputs[0].audio_path == voice_path.resolve().as_posix()
    assert outputs[0].text == "Recorded line"
    manager.switch_model.assert_called_once()
    manager.generate_tts.assert_not_called()


def test_default_tts_generation_uses_fixed_voice_when_manager_is_unavailable(
    tmp_path,
):
    voice_path = tmp_path / "fallback.wav"
    voice_path.write_bytes(b"audio")
    request = TtsGenerationRequest(
        runtime=SimpleNamespace(tts_manager=None),
        character=_character(),
        character_name="Alice",
        message=LLMDialogMessage(name="Alice", text="Hello", asset_id="1"),
        sprite=SpriteMatch(
            asset_id="1",
            index=0,
            sprite={},
            voice_type="fallback",
            voice_path=str(voice_path),
        ),
    )

    outputs = list(DefaultTtsGenerationStrategy().generate(request))

    assert len(outputs) == 1
    assert outputs[0].audio_path == voice_path.resolve().as_posix()
    assert outputs[0].text == "Hello"


def test_default_tts_generation_preserves_segment_output_order(tmp_path):
    audio_paths = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for audio_path in audio_paths:
        audio_path.write_bytes(b"audio")
    manager = MagicMock()
    manager.generate_tts.side_effect = [
        path.resolve().as_posix() for path in audio_paths
    ]
    text_processor = MagicMock()
    text_processor.remove_parentheses.side_effect = lambda text: text
    runtime = SimpleNamespace(
        tts_manager=manager,
        text_processor=text_processor,
        config=SimpleNamespace(
            config=SimpleNamespace(
                api_config=SimpleNamespace(
                    tts_split_enabled=True,
                    tts_max_sentence_length=3,
                    tts_provider="gpt-sovits",
                    gpt_sovits_url="http://localhost:9880",
                )
            )
        ),
    )
    request = TtsGenerationRequest(
        runtime=runtime,
        character=_character(),
        character_name="Alice",
        message=LLMDialogMessage(
            name="Alice", text="Hi.Bye.", asset_id="1", effect="shake"
        ),
        sprite=SpriteMatch(asset_id="1"),
    )

    outputs = list(DefaultTtsGenerationStrategy().generate(request))

    assert [output.audio_path for output in outputs] == [
        path.resolve().as_posix() for path in audio_paths
    ]
    assert [output.text for output in outputs] == ["Hi.Bye.", ""]
    assert [output.effect for output in outputs] == ["shake", ""]
    assert [output.is_final_segment for output in outputs] == [False, True]
    assert [output.timeout for output in outputs] == [None, 0]


def test_character_handler_delegates_to_injected_strategies(mock_app_runtime):
    sprite = SpriteMatch(asset_id="7", index=6, sprite={"path": "chosen.png"})
    sprite_lookup = MagicMock()
    sprite_lookup.lookup.return_value = sprite
    expected = TTSOutputMessage(
        audio_path="chosen.wav",
        name="TestChar",
        text="Hello",
        asset_id="7",
    )
    generation = MagicMock()
    generation.generate.return_value = [expected]
    handler = DefaultCharacterTtsHandler(sprite_lookup, generation)
    message = LLMDialogMessage(name="TestChar", text="Hello", asset_id="1")

    handler.handle(message)

    lookup_request = sprite_lookup.lookup.call_args.args[0]
    assert lookup_request.message is message
    generation_request = generation.generate.call_args.args[0]
    assert generation_request.sprite is sprite
    assert mock_app_runtime.audio_path_queue.get_nowait() is expected
