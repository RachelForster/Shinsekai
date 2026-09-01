from pathlib import Path
from types import SimpleNamespace

import pytest

from application.characters import (
    CharacterExportResult,
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
    validate_character_payload,
)
from config.domain.schema import Character


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
    validate_character_payload(_character_payload(), allow_remote_voice_paths=True)


def test_local_voice_paths_still_require_existing_files():
    with pytest.raises(ValueError, match="GPT 模型路径"):
        validate_character_payload(_character_payload(), allow_remote_voice_paths=False)


def test_remote_voice_paths_still_validate_model_suffixes():
    with pytest.raises(ValueError, match="SoVITS 模型路径"):
        validate_character_payload(
            _character_payload(sovits_model_path="/kaggle/input/voice-model/model.ckpt"),
            allow_remote_voice_paths=True,
        )


class FakeCharacterManager:
    def __init__(self, character):
        self.character = character

    def add_character(self, *_args, **_kwargs):
        return "updated", [self.character.name]

    def save_sprite_voice_type(self, _character_name, sprite_index, voice_type):
        self.character.sprites[sprite_index]["voice_type"] = voice_type
        return "voice type saved"

    def upload_voice(self, _character_name, sprite_index, voice_file, voice_text, voice_type=""):
        sprite = self.character.sprites[sprite_index]
        sprite["voice_path"] = voice_file
        sprite["voice_text"] = voice_text
        sprite["voice_type"] = voice_type or None
        return "voice uploaded", voice_file


class FakeConfigManager:
    def __init__(self, character):
        self.character = character
        self.config = SimpleNamespace(api_config=SimpleNamespace(tts_provider="none"))

    def get_character_by_name(self, name):
        return self.character if name == self.character.name else None

    def reload(self):
        pass


def make_character(**sprite_fields):
    return Character(
        name="Mika",
        color="#66ccff",
        sprite_prefix="mika",
        gpt_model_path=sprite_fields.pop("gpt_model_path", ""),
        sovits_model_path=sprite_fields.pop("sovits_model_path", ""),
        sprites=[{"path": "data/sprite/mika/0.png", **sprite_fields}],
    )


def make_use_case(character, project_root: Path):
    state = SimpleNamespace(
        character_manager=FakeCharacterManager(character),
        config_manager=FakeConfigManager(character),
        project_root_dir=str(project_root),
    )
    return CharacterUseCase(state, file_access_roots=(project_root,))


def execute(use_case, operation, payload):
    return use_case.execute(parse_character_request(operation, payload))


def test_character_save_propagates_rename_to_template_session(tmp_path, monkeypatch):
    character = make_character()
    use_case = make_use_case(character, tmp_path)
    renamed = []
    monkeypatch.setattr(
        "application.characters.management.validate_character_payload",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "application.chat.templates._rename_template_session_character",
        lambda _state, old_name, new_name: renamed.append((old_name, new_name)),
    )

    execute(
        use_case,
        CharacterOperation.SAVE,
        {
            "character": {"color": "#ffffff", "name": "Mika", "sprite_prefix": "a"},
            "originalName": "A",
        },
    )

    assert renamed == [("A", "Mika")]


def test_upload_sprite_voice_rejects_invalid_voice_type(tmp_path):
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"not really audio")
    use_case = make_use_case(make_character(), tmp_path)

    with pytest.raises(ValueError, match="voice type"):
        execute(
            use_case,
            CharacterOperation.UPLOAD_SPRITE_VOICE,
            {
                "name": "Mika",
                "spriteIndex": 0,
                "voicePath": str(voice),
                "voiceText": "",
                "voiceType": "bad",
            },
        )


def test_upload_sprite_voice_defaults_to_fallback_without_model(tmp_path):
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"not really audio")
    character = make_character()
    use_case = make_use_case(character, tmp_path)

    execute(
        use_case,
        CharacterOperation.UPLOAD_SPRITE_VOICE,
        {"name": "Mika", "spriteIndex": 0, "voicePath": str(voice), "voiceText": ""},
    )

    assert character.sprites[0]["voice_type"] == "fallback"


def test_upload_sprite_voice_defaults_to_reference_with_model(tmp_path, monkeypatch):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"not really audio")
    character = make_character(gpt_model_path="model.ckpt", sovits_model_path="model.pth")
    use_case = make_use_case(character, tmp_path)
    monkeypatch.setattr(use_case, "_validate_reference_audio", lambda _path: None)

    execute(
        use_case,
        CharacterOperation.UPLOAD_SPRITE_VOICE,
        {"name": "Mika", "spriteIndex": 0, "voicePath": str(voice), "voiceText": ""},
    )

    assert character.sprites[0]["voice_type"] == "reference"


def test_save_sprite_voice_type_rejects_missing_reference_audio(tmp_path):
    use_case = make_use_case(make_character(voice_path="missing.wav"), tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        execute(
            use_case,
            CharacterOperation.SAVE_SPRITE_VOICE_TYPE,
            {"name": "Mika", "spriteIndex": 0, "voiceType": "reference"},
        )


def test_export_returns_transport_neutral_path_result(tmp_path, monkeypatch):
    use_case = make_use_case(make_character(), tmp_path)
    exported = []
    monkeypatch.setattr(
        "tools.file_util.export_character",
        lambda _characters, output, *, open_folder: exported.append(output),
    )

    result = execute(use_case, CharacterOperation.EXPORT, {"name": "Mika"})

    assert result == CharacterExportResult(path="output/Mika.char")
    assert exported == [(tmp_path / "output" / "Mika.char").as_posix()]
