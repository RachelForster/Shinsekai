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
    assert imported["avatar_type"] == "l2d"
    assert state.config_manager.get_character_by_name("Haru").avatar_type == "l2d"
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


def test_producer_transport_urls_read_imported_model_and_state(harness, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from application.chat.ui_updates import StreamingUIUpdateManager
    from frontend_bridge_core.transport.chat_session import ChatSessionTransport
    from frontend_bridge_core.transport.ws_client import WSClientSink

    state, use_case, entry = harness
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = imported["avatars"]["l2d"]["model_path"]
    saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
                    sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="neutral")
    sink = WSClientSink("ws://127.0.0.1:8788/ws?token=regression-test")
    monkeypatch.setattr(sink, "_ensure_worker", lambda: None)
    monkeypatch.setattr("application.chat.ui_updates.get_character_by_name", state.config_manager.get_character_by_name)
    transport = ChatSessionTransport(stream_sink=sink)
    StreamingUIUpdateManager(transport, resource_urls=transport.resource_urls).update_sprite("Haru", 0)
    event = sink._peek_event()
    for field, expected in (("modelUrl", model), ("url", saved["avatars"]["l2d"]["sprites"][0]["path"])):
        url = urlsplit(event[field])
        assert url.path == "/api/avatar/file"
        query = parse_qs(url.query)
        assert query["shinsekai_bridge_token"] == ["regression-test"]
        assert model_file(state, query["model_path"][0], query["path"][0]) == Path(expected)


def test_missing_import_dependency_preserves_configuration(harness):
    state, use_case, entry = harness
    (entry.parent / "texture.png").unlink()
    with pytest.raises(FileNotFoundError):
        execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    assert state.config_manager.get_character_by_name("Haru").avatars == {}


def test_replacement_excludes_old_states_but_preserves_files(harness):
    state, use_case, entry = harness
    first = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = first["avatars"]["l2d"]["model_path"]
    saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
                    sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="old")
    replacement = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    assert replacement["avatars"]["l2d"]["sprites"] == []
    assert replacement["avatars"]["l2d"]["emotion_tags"] == ""
    assert Path(saved["avatars"]["l2d"]["sprites"][0]["path"]).is_file()
    assert Path(model).is_file()
    new_model = replacement["avatars"]["l2d"]["model_path"]
    assert model_file(state, new_model, "texture.png").is_file()
    from config.character_assets import get_character_assets
    active = get_character_assets(state.config_manager.get_character_by_name("Haru"))
    assert active.sprites == []
    assert active.emotion_tags == ""
    fresh = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d",
                    model_path=new_model, sprite_index=-1, path="",
                    state={"parameters": {}, "expressions": [], "motion": ""}, tags="new")
    fresh_path = Path(fresh["avatars"]["l2d"]["sprites"][0]["path"])
    assert model_file(state, new_model, fresh_path.relative_to(Path(new_model).parent).as_posix()) == fresh_path


def test_static_cleanup_preserves_imported_models_and_saved_states(harness, monkeypatch):
    state, use_case, entry = harness
    first = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    model = first["avatars"]["l2d"]["model_path"]
    execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
            sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="keep")
    root = Path(state.project_root_dir)
    monkeypatch.setattr("config.character_manager.UPLOAD_DIR", str(root / "data/sprite"))
    monkeypatch.setattr("config.character_manager.VOICE_DIR", str(root / "data/speech"))
    static = root / "data/sprite/haru/static.png"
    static.touch()
    packaged_voice = root / "data/sprite/haru/avatar-voices/l2d/smile.wav"
    packaged_voice.parent.mkdir(parents=True)
    packaged_voice.touch()
    character = state.config_manager.get_character_by_name("Haru")
    character.avatar_type = "static"
    character.sprites = [{"path": str(static)}]
    character.emotion_tags = "立绘 1：static\n"
    banks = character.model_dump(mode="json")["avatars"]
    state.character_manager.delete_all_sprites("Haru")
    state.config_manager.reload()
    character = state.config_manager.get_character_by_name("Haru")
    assert not static.exists()
    assert packaged_voice.is_file()
    assert character.sprites == [] and character.emotion_tags == ""
    assert character.model_dump(mode="json")["avatars"] == banks
    character.avatar_type = "l2d"
    assert model_file(state, model, "texture.png").is_file()
    saved = Path(banks["l2d"]["sprites"][0]["path"])
    assert model_file(state, model, saved.relative_to(Path(model).parent).as_posix()) == saved


@pytest.mark.parametrize("operation", ["import", "replace", "append", "overwrite"])
@pytest.mark.parametrize("failure", ["serialize", "flush", "replace"])
def test_real_persistence_failure_rolls_back_files_and_bank(harness, monkeypatch, operation, failure):
    """Exercise the real YAML commit, not a fake save method that already raises."""
    import yaml
    from config.config_manager import ConfigManager

    state, use_case, entry = harness
    manager = object.__new__(ConfigManager)
    manager._config = state.config_manager.config
    manager._CHARACTERS_CONFIG_PATH = Path(state.project_root_dir) / "characters.yaml"
    def reload():
        manager._config.characters = [Character.model_validate(item) for item in
                                     yaml.safe_load(manager._CHARACTERS_CONFIG_PATH.read_text(encoding="utf-8"))]
    monkeypatch.setattr(manager, "reload", reload)
    state.config_manager = manager
    state.character_manager._config_manager = manager
    manager.save_characters_config()
    if operation != "import":
        imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
        model = imported["avatars"]["l2d"]["model_path"]
        saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
                        sprite_index=-1, path="", state={"parameters": {}, "expressions": [], "motion": ""}, tags="old")
    original = manager.get_character_by_name("Haru").model_dump(mode="json")
    disk = manager._CHARACTERS_CONFIG_PATH.read_bytes()
    root = Path(state.project_root_dir)
    files = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    def fail(*args, **kwargs):
        if failure == "serialize":
            args[1].write("partial YAML")
        raise OSError("simulated disk write failure")
    target = {"serialize": "yaml.dump", "flush": "os.fsync", "replace": "os.replace"}[failure]
    monkeypatch.setattr(f"config.config_manager.{target}", fail)
    with pytest.raises(OSError, match="simulated disk write failure"):
        if operation in {"import", "replace"}:
            execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
        else:
            execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="l2d", model_path=model,
                    sprite_index=0 if operation == "overwrite" else -1,
                    path=saved["avatars"]["l2d"]["sprites"][0]["path"] if operation == "overwrite" else "",
                    state={"parameters": {"ParamAngleX": 2}, "expressions": [], "motion": ""}, tags="new")
    assert manager.get_character_by_name("Haru").model_dump(mode="json") == original
    assert manager._CHARACTERS_CONFIG_PATH.read_bytes() == disk
    assert {p.relative_to(root) for p in root.rglob("*") if p.is_file()} == files
    reload()
    assert manager.get_character_by_name("Haru").model_dump(mode="json") == original


def test_import_activates_model_without_replacing_static_or_other_banks(harness):
    state, use_case, entry = harness
    character = state.config_manager.get_character_by_name("Haru")
    character.sprites = [{"path": str(entry.parent / "static.png")}]
    character.emotion_tags = "立绘 1：static\n"
    from config.schema import ModelSprites
    character.avatars["future"] = ModelSprites(model_path="future.model", emotion_tags="keep")
    result = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    assert result["avatar_type"] == "l2d"
    assert result["sprites"][0]["path"] == str(entry.parent / "static.png")
    assert result["emotion_tags"] == "立绘 1：static\n"
    assert result["avatars"]["future"]["emotion_tags"] == "keep"
    state.config_manager.reload()
    assert state.config_manager.get_character_by_name("Haru").avatar_type == "l2d"


def test_failed_import_rolls_back_active_type_and_bank(harness, monkeypatch):
    state, use_case, entry = harness
    def fail_save():
        raise OSError("Cannot save configuration")
    monkeypatch.setattr(state.character_manager, "_save_characters_config", fail_save)
    with pytest.raises(OSError, match="Cannot save"):
        execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    character = state.config_manager.get_character_by_name("Haru")
    assert character.avatar_type == "static"
    assert character.avatars == {}
    parent = Path(state.project_root_dir) / "data/sprite/haru/avatars/l2d"
    assert list(parent.iterdir()) == []


def test_new_format_reuses_import_startup_events_and_snapshot(harness, monkeypatch):
    """An opaque, non-Cubism format must need no changes to the shared pipeline."""
    from application.chat.initial_sprite import display_initial_sprite, initial_sprite_path_for_characters
    from application.chat.runtime_process import _chat_session_media
    from application.chat.ui_updates import StreamingUIUpdateManager
    from application.runtime.event_sink import fold_event_into_snapshot, make_empty_chat_snapshot
    from core.media.avatar import registry
    from frontend_bridge_core.resource_urls import BridgeResourceUrls
    from sdk.adapters.avatar import ModelAssetAdapter, ModelFiles

    class DemoAdapter(ModelAssetAdapter):
        format_id = "demo"

        def inspect(self, source):
            return ModelFiles(source.resolve(), (source.resolve(),))

        def parse_state(self, model, value):
            assert "pose" in value
            return dict(value)

        def state_files(self, model, state):
            return ()

    monkeypatch.setattr(registry, "_builtin", dict(registry._builtin))
    registry.register_adapter(DemoAdapter())
    state, use_case, entry = harness
    entry = entry.with_name("sample.demo")
    entry.write_text("demo")
    old_sprite = entry.with_name("static.png")
    old_sprite.touch()
    state.config_manager.get_character_by_name("Haru").sprites = [{"path": str(old_sprite)}]
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="demo", source_path=str(entry))
    model = imported["avatars"]["demo"]["model_path"]
    saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="demo", model_path=model,
                    sprite_index=-1, path="", state={"pose": [1, 2, 3]}, tags="demo pose")
    saved_path = saved["avatars"]["demo"]["sprites"][0]["path"]
    assert initial_sprite_path_for_characters(state.config_manager, str(old_sprite), ["Haru"]) == saved_path

    events = []
    urls = BridgeResourceUrls("http://127.0.0.1:8787", "test-token")
    presenter = StreamingUIUpdateManager(SimpleNamespace(emit=events.append), resource_urls=urls)
    monkeypatch.setattr("application.chat.ui_updates.get_character_by_name", state.config_manager.get_character_by_name)
    assert display_initial_sprite(saved_path, config=state.config_manager, ui_updates=presenter)
    assert events[0]["avatarType"] == "demo"
    restored = fold_event_into_snapshot(make_empty_chat_snapshot(), events[0])["sprites"][0]
    state.chat_session = {"characterName": "Haru"}
    state.resource_urls = urls
    _, _, initial = _chat_session_media(state)
    for key in ("avatarType", "modelUrl", "path", "scale"):
        assert initial[0][key] == restored[key]
    relative_state = Path(saved_path).relative_to(Path(model).parent).as_posix()
    assert json.loads(model_file(state, model, relative_state).read_text()) == {"pose": [1, 2, 3]}
