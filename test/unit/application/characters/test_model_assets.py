import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.characters.management import CharacterOperation, CharacterRequest, CharacterUseCase
from application.characters.model_files import model_file
from config.character_manager import CharacterManager
from config.schema import Character
from core.media.avatar.registry import configure_builtin_formats


@pytest.fixture
def harness(tmp_path):
    configure_builtin_formats()
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.moc3").write_text("moc")
    (source / "texture.png").write_text("texture")
    entry = source / "sample.model3.json"
    entry.write_text(json.dumps({"Version": 3, "FileReferences": {"Moc": "sample.moc3", "Textures": ["texture.png"]}}))
    character = Character(name="Haru", color="#fff", sprite_prefix="haru")
    class Config:
        config = SimpleNamespace(characters=[character])
        def get_character_by_name(self, name):
            return next((c for c in self.config.characters if c.name == name), None)
        def save_characters_config(self):
            (tmp_path / "characters.json").write_text(json.dumps([c.model_dump(mode="json") for c in self.config.characters]))
        def reload(self):
            self.config.characters = [Character.model_validate(c) for c in json.loads((tmp_path / "characters.json").read_text())]
    config = Config()
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = config
    state = SimpleNamespace(config_manager=config, character_manager=manager, project_root_dir=str(tmp_path))
    return state, CharacterUseCase(state), entry


def execute(use_case, operation, **body):
    return use_case.execute(CharacterRequest(operation, body))


def test_import_save_overwrite_and_authorized_files(harness):
    state, use_case, entry = harness
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = imported["avatars"]["l2d"]["model_path"]
    assert model != str(entry) and Path(model).is_file()
    body = dict(name="Haru", avatar_type="l2d", model_path=model, sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="neutral")
    result = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, **body)
    bank = result["avatars"]["l2d"]
    assert len(bank["sprites"]) == 1 and bank["emotion_tags"] == "立绘 1：neutral\n"
    path = bank["sprites"][0]["path"]
    voice = Path(model).parent / "voice.wav"
    voice.write_text("voice")
    character = state.config_manager.get_character_by_name("Haru")
    character.avatars["l2d"].sprites[0]["voice_path"] = str(voice)
    overwrite = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, **{**body, "sprite_index": 0, "path": path, "tags": "updated"})
    assert overwrite["avatars"]["l2d"]["sprites"][0]["voice_path"] == str(voice)
    assert overwrite["sprites"] == []
    assert model_file(state, model, "texture.png").name == "texture.png"
    with pytest.raises(PermissionError): model_file(state, model, "unlisted.json")
    with pytest.raises((ValueError, PermissionError)): model_file(state, model, "../characters.json")
    with pytest.raises(PermissionError): model_file(state, str(entry), "texture.png")
    with pytest.raises(ValueError): execute(use_case, CharacterOperation.SAVE_MODEL_STATE, **{**body, "model_path": "changed"})
    with pytest.raises(ValueError): execute(use_case, CharacterOperation.SAVE_MODEL_STATE, **{**body, "sprite_index": 0, "path": path})


def test_bad_state_does_not_change_bank(harness):
    state, use_case, entry = harness
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = imported["avatars"]["l2d"]["model_path"]
    with pytest.raises(ValueError):
        execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model, sprite_index=-1, path="", state={"parameters": {"X": float("nan")}, "expressions": [], "motion": ""}, tags="bad")
    assert state.config_manager.get_character_by_name("Haru").avatars["l2d"].sprites == []


def test_missing_import_dependency_preserves_configuration(harness):
    state, use_case, entry = harness
    (entry.parent / "texture.png").unlink()
    with pytest.raises(FileNotFoundError):
        execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    assert state.config_manager.get_character_by_name("Haru").avatars == {}


def test_replacement_retains_old_states_without_breaking_new_model(harness):
    state, use_case, entry = harness
    first = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = first["avatars"]["l2d"]["model_path"]
    saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
                    sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="old")
    replacement = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    assert replacement["avatars"]["l2d"]["sprites"] == saved["avatars"]["l2d"]["sprites"]
    new_model = replacement["avatars"]["l2d"]["model_path"]
    assert model_file(state, new_model, "texture.png").is_file()
