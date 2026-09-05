"""Tests for replaceable sprite lookup and TTS generation strategies."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from application.chat.handlers.dialog_media import (
    BgmMediaHandler,
    CharacterMediaHandler,
    SceneMediaHandler,
)
from application.chat.dialog_media import (
    AssetCandidate,
    AssetIdMatch,
    AssetLookupRequest,
    AssetLookupResult,
    CompositeAssetLookupStrategy,
    create_asset_lookup_strategy,
    DefaultTtsGenerationStrategy,
    MessageAssetIdLookupStrategy,
    ResolvedSpriteAsset,
    SpriteAssetResolver,
    TtsGenerationRequest,
    VectorDatabaseAssetLookupStrategy,
)
from application.runtime.workers import DialogMediaWorker
from sdk.messages import LLMDialogMessage, PresentationMessage


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


def test_message_asset_id_lookup_and_sprite_resolver_resolve_voice_metadata(tmp_path):
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
    resolver = SpriteAssetResolver(tmp_path / "missing.yaml")
    candidates = resolver.candidates(character)
    result = MessageAssetIdLookupStrategy().lookup(
        AssetLookupRequest(
            scope="sprite:Alice",
            candidates=candidates,
            explicit_asset_id="1",
        )
    )
    match = resolver.resolve(character, candidates, result)

    assert match.found is True
    assert match.asset_id == "1"
    assert match.index == 0
    assert match.sprite is character.sprites[0]
    assert match.voice_type == "preset"
    assert match.voice_path == "happy.wav"
    assert match.voice_text == "A happy line"


def test_vector_database_asset_lookup_returns_ranked_current_candidates():
    search = MagicMock(
        return_value=[
            {"asset_id": "2", "score": 0.91},
            {"asset_id": "stale", "score": 0.85},
            {"asset_id": "1", "score": 0.62},
        ]
    )
    candidates = (
        AssetCandidate("1", 0, "first.png", tags="calm"),
        AssetCandidate("2", 1, "second.png", tags="angry"),
    )

    result = VectorDatabaseAssetLookupStrategy(search).lookup(
        AssetLookupRequest(
            scope="sprite:alice",
            candidates=candidates,
            vibe="furious",
        )
    )

    assert result.matches == (
        AssetIdMatch("2", 0.91),
        AssetIdMatch("1", 0.62),
    )
    search.assert_called_once_with(
        scope="sprite:alice",
        vibe="furious",
        candidates=candidates,
        limit=2,
    )


def test_composite_asset_lookup_falls_back_to_explicit_id():
    empty = MagicMock()
    empty.lookup.return_value = AssetLookupResult()
    strategy = CompositeAssetLookupStrategy((empty, MessageAssetIdLookupStrategy()))

    result = strategy.lookup(
        AssetLookupRequest(
            scope="scene:school",
            candidates=(),
            explicit_asset_id="03",
        )
    )

    assert result.best == AssetIdMatch("03")


def test_asset_lookup_factory_uses_vector_then_direct_fallback():
    strategy = create_asset_lookup_strategy("semantic")

    assert isinstance(strategy, CompositeAssetLookupStrategy)
    assert isinstance(strategy.strategies[0], VectorDatabaseAssetLookupStrategy)
    assert isinstance(strategy.strategies[1], MessageAssetIdLookupStrategy)
    assert isinstance(
        create_asset_lookup_strategy("indexed"),
        MessageAssetIdLookupStrategy,
    )


def test_sprite_resolver_refreshes_mutable_voice_metadata_from_yaml(tmp_path):
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

    resolver = SpriteAssetResolver(characters_path)
    candidates = resolver.candidates(character)
    result = MessageAssetIdLookupStrategy().lookup(
        AssetLookupRequest(
            scope="sprite:Alice",
            candidates=candidates,
            explicit_asset_id="1",
        )
    )
    match = resolver.resolve(character, candidates, result)

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
        sprite=ResolvedSpriteAsset(
            asset_id="1",
            index=0,
            value={},
            voice_type="preset",
            voice_path=str(voice_path),
            voice_text="Recorded line",
        ),
    )

    audio_paths = list(DefaultTtsGenerationStrategy().generate(request))

    assert audio_paths == [voice_path.resolve().as_posix()]
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
        sprite=ResolvedSpriteAsset(
            asset_id="1",
            index=0,
            value={},
            voice_type="fallback",
            voice_path=str(voice_path),
        ),
    )

    audio_paths = list(DefaultTtsGenerationStrategy().generate(request))

    assert audio_paths == [voice_path.resolve().as_posix()]


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
        sprite=ResolvedSpriteAsset(asset_id="1"),
    )

    generated_paths = list(DefaultTtsGenerationStrategy().generate(request))

    assert generated_paths == [path.resolve().as_posix() for path in audio_paths]


def test_character_handler_builds_presentation_from_injected_path_strategy(
    mock_app_runtime,
):
    sprite = ResolvedSpriteAsset(
        asset_id="7",
        index=6,
        value={"path": "chosen.png"},
        voice_type="preset",
        voice_path="recorded.wav",
        voice_text="Recorded line",
    )
    asset_lookup = MagicMock()
    sprite_resolver = MagicMock()
    sprite_resolver.candidates.return_value = ()
    sprite_resolver.resolve.return_value = sprite
    generation = MagicMock()
    generation.generate.return_value = ["first.wav", "second.wav"]
    handler = CharacterMediaHandler(asset_lookup, generation, sprite_resolver)
    message = LLMDialogMessage(name="TestChar", text="Hello", asset_id="1")

    handler.handle(message)

    lookup_request = asset_lookup.lookup.call_args.args[0]
    assert lookup_request.explicit_asset_id == "1"
    assert lookup_request.scope == "sprite:TestChar"
    generation_request = generation.generate.call_args.args[0]
    assert generation_request.sprite is sprite
    assert mock_app_runtime.presentation_queue.get_nowait() == PresentationMessage(
        audio_path="first.wav",
        name="TestChar",
        text="Recorded line",
        asset_id="7",
        is_final_segment=False,
    )
    assert mock_app_runtime.presentation_queue.get_nowait() == PresentationMessage(
        audio_path="second.wav",
        name="TestChar",
        text="",
        asset_id="7",
        effect="",
        is_final_segment=True,
        timeout=0,
    )


def test_scene_handler_resolves_vibe_match_through_shared_asset_strategy(
    mock_app_runtime,
):
    mock_app_runtime.background = SimpleNamespace(
        name="School",
        sprites=[{"path": "day.png"}, {"path": "rain.png"}],
        bg_tags="daylight\nrainy, lonely",
    )
    lookup = MagicMock(
        return_value=AssetLookupResult(matches=(AssetIdMatch("2", 0.9),))
    )
    lookup.lookup = lookup
    handler = SceneMediaHandler(lookup)

    handler.handle(LLMDialogMessage(name="scene", text="", vibe="lonely rain"))

    request = lookup.call_args.args[0]
    assert request.scope == "scene:School"
    assert request.vibe == "lonely rain"
    assert request.candidates[1].tags == "rainy, lonely"
    assert mock_app_runtime.presentation_queue.get_nowait().asset_id == "2"


def test_bgm_handler_resolves_vibe_match_through_shared_asset_strategy(
    mock_app_runtime,
):
    mock_app_runtime.background = SimpleNamespace(
        name="School",
        bgm_tags="quiet\ntense pursuit",
    )
    mock_app_runtime.bgm_list = ["quiet.mp3", "chase.mp3"]
    lookup = MagicMock(
        return_value=AssetLookupResult(matches=(AssetIdMatch("2", 0.88),))
    )
    lookup.lookup = lookup
    handler = BgmMediaHandler(lookup)

    handler.handle(LLMDialogMessage(name="bgm", text="", vibe="danger"))

    request = lookup.call_args.args[0]
    assert request.scope == "bgm:School"
    assert request.vibe == "danger"
    assert request.candidates[1].tags == "tense pursuit"
    output = mock_app_runtime.presentation_queue.get_nowait()
    assert output.asset_id == "2"
    assert output.audio_path == "chase.mp3"


def test_dialog_media_worker_passes_injected_strategies_to_handler_chain(monkeypatch):
    asset_lookup = MagicMock()
    sprite_resolver = MagicMock()
    generation = MagicMock()
    dispatcher = MagicMock()
    chain_factory = MagicMock(return_value=dispatcher)
    monkeypatch.setattr(
        "application.runtime.workers.dialog_media_worker.default_dialog_media_handler_chain",
        chain_factory,
    )
    worker = DialogMediaWorker(
        input_queue=MagicMock(),
        output_queue=MagicMock(),
        asset_lookup_strategy=asset_lookup,
        sprite_resolver=sprite_resolver,
        tts_generation_strategy=generation,
    )

    worker._init_app()

    chain_factory.assert_called_once_with(
        asset_lookup_strategy=asset_lookup,
        sprite_resolver=sprite_resolver,
        tts_generation_strategy=generation,
    )
    dispatcher.init_handlers.assert_called_once_with()
