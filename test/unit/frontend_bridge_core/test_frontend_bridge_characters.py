from types import SimpleNamespace

import pytest

from frontend_bridge_core.characters import _save_character, _validate_character_payload


def _character_payload(**overrides):
    data = {
        "name": "Remote Voice",
        "color": "#ffffff",
        "sprite_prefix": "remote_voice",
        "gpt_model_path": "/kaggle/input/voice-model/model.ckpt",
        "sovits_model_path": "/kaggle/input/voice-model/model.pth",
        "refer_audio_path": "/kaggle/input/voice-model/ref.wav",
    }
    data.update(overrides)
    return data


def test_remote_voice_paths_skip_local_file_existence_checks():
    _validate_character_payload(_character_payload(), allow_remote_voice_paths=True)


def test_local_voice_paths_still_require_existing_files():
    with pytest.raises(ValueError, match="GPT 模型路径"):
        _validate_character_payload(_character_payload(), allow_remote_voice_paths=False)


def test_remote_voice_paths_still_validate_model_suffixes():
    with pytest.raises(ValueError, match="SoVITS 模型路径"):
        _validate_character_payload(
            _character_payload(sovits_model_path="/kaggle/input/voice-model/model.ckpt"),
            allow_remote_voice_paths=True,
        )


def test_character_save_propagates_rename_to_template_session(monkeypatch):
    renamed: list[tuple[str, str]] = []
    config_manager = SimpleNamespace(
        config=SimpleNamespace(api_config=SimpleNamespace(tts_provider="none")),
        get_character_by_name=lambda name: SimpleNamespace(name=name),
        reload=lambda: None,
    )
    character_manager = SimpleNamespace(
        add_character=lambda *_args, **_kwargs: ("updated", ["B", "C"]),
    )
    state = SimpleNamespace(
        character_manager=character_manager,
        config_manager=config_manager,
    )
    monkeypatch.setattr(
        "frontend_bridge_core.characters._validate_character_payload",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "application.chat.templates._rename_template_session_character",
        lambda _state, old_name, new_name: renamed.append((old_name, new_name)),
    )

    _save_character(
        state,
        {
            "character": {
                "color": "#ffffff",
                "name": "C",
                "sprite_prefix": "a",
            },
            "originalName": "A",
        },
    )

    assert renamed == [("A", "C")]
