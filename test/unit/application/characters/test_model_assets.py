import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.characters.management import CharacterOperation, CharacterRequest, CharacterUseCase
from application.characters.model_files import model_file
from config.character_manager import CharacterManager
from config.schema import Character
from core.media.avatar.registry import configure_builtin_formats
from test.fixtures.pmx import pmx_bytes, pmx_sections
from test.fixtures.mmd_motion import vpd_bytes, vmd_bytes


def test_cold_authorization_of_full_batch_only_reads_dependency_indexes(harness, monkeypatch):
    from core.media.avatar import mmd

    state, use_case, body = _mmd_batch(harness)
    body["source_paths"] = [body["source_paths"][1]] * 100
    result = execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    model = Path(body["model_path"])
    mmd._metadata.cache_clear()
    mmd._cached_texture_paths.cache_clear()
    def unexpected(*args, **kwargs):
        pytest.fail("Resource authorization reparsed a preset/state")
    monkeypatch.setattr(mmd, "inspect_motion", unexpected)
    monkeypatch.setattr(mmd.MmdAdapter, "parse_state", unexpected)
    original_open = Path.open
    def bounded_open(path, *args, **kwargs):
        if path.suffix.lower() in {".vpd", ".vmd"}:
            pytest.fail("Resource authorization read motion contents")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", bounded_open)
    assert model_file(state, str(model), model.name) == model
    saved = Path(result["avatars"]["mmd"]["sprites"][-1]["path"])
    assert model_file(state, str(model), saved.relative_to(model.parent).as_posix()) == saved
    value = json.loads(saved.read_text())
    assert model_file(state, str(model), value["motion"]).is_file()


def test_invalid_legacy_motion_entry_does_not_block_model_or_indexed_states(harness):
    state, use_case, body = _mmd_batch(harness)
    result = execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    model = Path(body["model_path"])
    (model.parent / "directory.vmd").mkdir()
    bad = model.parent / "legacy.json"
    bad.write_text(json.dumps({**body["state"], "motion": "directory.vmd"}))
    bank = state.config_manager.get_character_by_name("Haru").avatars["mmd"]
    bank.sprites.insert(0, {"path": str(bad)})
    assert model_file(state, str(model), model.name) == model
    saved = Path(result["avatars"]["mmd"]["sprites"][0]["path"])
    assert model_file(state, str(model), saved.relative_to(model.parent).as_posix()) == saved
    with pytest.raises(PermissionError):
        model_file(state, str(model), "directory.vmd")


@pytest.mark.parametrize("changed", ["state", "motion", "index"])
def test_dependency_index_fails_closed_if_resources_change(harness, changed):
    from core.media.avatar.state_dependencies import index_path

    state, use_case, body = _mmd_batch(harness)
    result = execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    model = Path(body["model_path"])
    saved = Path(result["avatars"]["mmd"]["sprites"][0]["path"])
    value = json.loads(saved.read_text())
    if changed == "state":
        saved.write_text(json.dumps({**value, "morphs": {"smile": 0.5}}))
    elif changed == "motion":
        (model.parent / value["motion"]).write_bytes(b"tampered")
    else:
        index_path(saved).write_text("invalid index")
    with pytest.raises(PermissionError):
        model_file(state, str(model), value["motion"])
    assert model_file(state, str(model), model.name) == model


@pytest.mark.parametrize("phase", ["copy", "before-config", "after-config"])
def test_crashed_preset_batch_is_recovered_without_losing_committed_data(harness, monkeypatch, phase):
    from application.characters import model_assets
    from application.characters.import_recovery import recover_model_imports
    from core.media.asset_import import PENDING_MARKER

    state, use_case, body = _mmd_batch(harness)
    model = Path(body["model_path"])
    original_save = state.character_manager.save_avatar_bank
    original_copy = model_assets.shutil.copy2
    def interrupted_copy(source, target):
        Path(target).write_bytes(b"partial copy")
        raise SystemExit("process exited while staging")
    def interrupted_save(*args, **kwargs):
        if phase == "after-config":
            original_save(*args, **kwargs)
        raise SystemExit("process exited near commit")
    with monkeypatch.context() as patch:
        patch.setattr(model_assets.shutil, "copy2", interrupted_copy if phase == "copy" else original_copy)
        patch.setattr(state.character_manager, "save_avatar_bank", interrupted_save)
        with pytest.raises(SystemExit):
            execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    candidates = list(model.parent.glob(f"states/.batch-*/{PENDING_MARKER}"))
    assert len(candidates) == 1
    batch = candidates[0].parent
    state.config_manager.reload()
    recover_model_imports(state)
    if phase == "after-config":
        assert batch.is_dir()
        bank = state.config_manager.get_character_by_name("Haru").avatars["mmd"]
        assert len(bank.sprites) == 2
        saved = Path(bank.sprites[0]["path"])
        assert model_file(state, str(model), saved.relative_to(model.parent).as_posix()) == saved
    else:
        assert not batch.exists()
        assert state.config_manager.get_character_by_name("Haru").avatars["mmd"].sprites == []
    assert not list(model.parent.rglob(PENDING_MARKER))
    assert not list(model.parent.glob("states/.batch-*.lock"))
    assert model.is_file()
    recover_model_imports(state)  # Recovery is idempotent.


def test_recovery_cleans_interrupted_batch_under_replaced_model(harness, monkeypatch):
    from application.characters import model_assets
    from application.characters.import_recovery import recover_model_imports
    from core.media.asset_import import PENDING_MARKER

    state, use_case, body = _mmd_batch(harness)
    old_model = Path(body["model_path"])
    original_copy = model_assets.shutil.copy2
    def interrupted(source, target):
        original_copy(source, target)
        raise SystemExit("interrupted")
    with monkeypatch.context() as patch:
        patch.setattr(model_assets.shutil, "copy2", interrupted)
        with pytest.raises(SystemExit):
            execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    batch = next(old_model.parent.rglob(PENDING_MARKER)).parent
    replacement = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="mmd",
                          source_path=str(harness[2].with_name("sample.pmx")))
    recover_model_imports(state)
    assert not batch.exists()
    assert old_model.is_file()
    assert Path(replacement["avatars"]["mmd"]["model_path"]).is_file()


def test_recovery_protects_motion_references_after_all_batch_states_are_overwritten(harness, monkeypatch):
    from application.characters.import_recovery import recover_model_imports
    from core.media.asset_import import PendingAssetBatch, PENDING_MARKER

    state, use_case, body = _mmd_batch(harness)
    # Emulate a commit whose marker cleanup was interrupted.
    with monkeypatch.context() as patch:
        patch.setattr(PendingAssetBatch, "commit", lambda self: (_ for _ in ()).throw(SystemExit("after commit")))
        with pytest.raises(SystemExit):
            execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    state.config_manager.reload()
    bank = state.config_manager.get_character_by_name("Haru").avatars["mmd"]
    batch = next(Path(body["model_path"]).parent.rglob(PENDING_MARKER)).parent
    for index, sprite in enumerate(list(bank.sprites)):
        saved = Path(sprite["path"])
        execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="mmd",
                model_path=body["model_path"], sprite_index=index, path=str(saved),
                state=json.loads(saved.read_text()), tags="edited")
    recover_model_imports(state)
    assert batch.exists()
    assert len(list(batch.rglob("preset.*"))) == 2
    assert not (batch / PENDING_MARKER).exists()


def test_startup_recovery_defers_when_durable_config_cannot_be_read(harness, monkeypatch):
    from application.characters.import_recovery import recover_model_imports
    from core.media.asset_import import PendingAssetBatch, PENDING_MARKER

    state, _, body = _mmd_batch(harness)
    with pytest.raises(SystemExit), PendingAssetBatch(Path(body["model_path"]).parent / "states") as transaction:
        (transaction.path / "partial.vmd").write_bytes(b"pending")
        raise SystemExit("process exited")
    monkeypatch.setattr(state.config_manager, "reload", lambda: (_ for _ in ()).throw(OSError("config unreadable")))
    recover_model_imports(state)
    assert (transaction.path / PENDING_MARKER).is_file()
    assert (transaction.path / "partial.vmd").is_file()


def test_startup_recovery_rejects_redirected_nested_marker_paths(harness, monkeypatch, tmp_path):
    from application.characters import import_recovery
    from core.media.asset_import import PENDING_MARKER

    state, _, body = _mmd_batch(harness)
    model = Path(body["model_path"])
    owned = model.parent.parent
    marker = model.parent / "states" / (".batch-" + "a" * 32) / PENDING_MARKER
    original_rglob = Path.rglob
    original_safe_child = import_recovery.safe_child_path

    def redirected_marker(root, pattern):
        return iter([marker]) if root == owned else original_rglob(root, pattern)

    def redirected_path(root, relative):
        if root == owned and str(relative) == str(marker.relative_to(owned)):
            return tmp_path / "outside" / PENDING_MARKER
        return original_safe_child(root, relative)

    monkeypatch.setattr(Path, "rglob", redirected_marker)
    monkeypatch.setattr(import_recovery, "safe_child_path", redirected_path)
    monkeypatch.setattr(import_recovery, "recover_asset_batches", lambda *args: pytest.fail("Recovery accepted a redirected path"))
    import_recovery.recover_model_imports(state)


def _mmd_batch(harness):
    state, use_case, entry = harness
    model = entry.with_name("sample.pmx")
    model.write_bytes(pmx_bytes())
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="mmd", source_path=str(model))
    pose = entry.with_name("wave.vpd")
    pose.write_bytes(vpd_bytes())
    motion = entry.with_name("wave.vmd")
    motion.write_bytes(vmd_bytes())
    body = dict(name="Haru", avatar_type="mmd", model_path=imported["avatars"]["mmd"]["model_path"],
                source_paths=[str(pose), str(motion)],
                state={"morphs": {}, "mouthMorph": "", "blinkMorph": "",
                       "camera": {"yaw": 20, "pitch": 0, "zoom": 2, "panX": 0, "panY": 0}})
    return state, use_case, body


def test_import_mixed_motion_batch_and_serve_managed_copies(harness):
    state, use_case, body = _mmd_batch(harness)
    result = execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    bank = result["avatars"]["mmd"]
    assert len(bank["sprites"]) == 2
    assert bank["emotion_tags"] == "立绘 1：wave\n立绘 2：wave\n"
    model = Path(bank["model_path"])
    for sprite, source in zip(bank["sprites"], body["source_paths"]):
        file = Path(sprite["path"])
        value = json.loads(file.read_text(encoding="utf-8"))
        assert value["camera"] == body["state"]["camera"]
        assert model_file(state, str(model), file.relative_to(model.parent).as_posix()) == file
        assert model_file(state, str(model), value["motion"]).read_bytes() == Path(source).read_bytes()
        Path(source).unlink()
        assert model_file(state, str(model), value["motion"]).is_file()
    # Subsequent batches append, preserving existing tags and voice metadata.
    character = state.config_manager.get_character_by_name("Haru")
    character.avatars["mmd"].sprites[0]["voice_text"] = "keep me"
    new_pose = model.parent / "again.vpd"
    new_pose.write_bytes(vpd_bytes())
    result = execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **{**body, "source_paths": [str(new_pose)]})
    assert len(result["avatars"]["mmd"]["sprites"]) == 3
    assert result["avatars"]["mmd"]["sprites"][0]["voice_text"] == "keep me"
    with pytest.raises(PermissionError):
        model_file(state, str(model), "again.vpd")


@pytest.mark.parametrize("failure", ["invalid", "incompatible", "persist", "stale"])
def test_motion_batch_is_atomic(harness, monkeypatch, failure):
    state, use_case, body = _mmd_batch(harness)
    before = state.config_manager.get_character_by_name("Haru").model_dump(mode="json")
    model = Path(body["model_path"])
    if failure == "invalid":
        Path(body["source_paths"][1]).write_bytes(b"broken")
    elif failure == "incompatible":
        Path(body["source_paths"][1]).write_bytes(vmd_bytes("another-rig"))
    elif failure == "persist":
        monkeypatch.setattr(state.config_manager, "save_characters_config", lambda: (_ for _ in ()).throw(OSError("disk full")))
    else:
        body["model_path"] = "stale.pmx"
    with pytest.raises((ValueError, OSError)):
        execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    assert state.config_manager.get_character_by_name("Haru").model_dump(mode="json") == before
    assert not list(model.parent.rglob("*.vpd")) and not list(model.parent.rglob("*.vmd"))
    assert not list(model.parent.rglob(".import-*"))


@pytest.mark.parametrize("paths", [[], "pose.vpd", ["file"] * 101])
def test_motion_batch_limits(harness, paths):
    state, use_case, body = _mmd_batch(harness)
    with pytest.raises(ValueError, match="100"):
        execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **{**body, "source_paths": paths})


def test_motion_batch_rejects_ungranted_inputs(harness, tmp_path_factory):
    state, use_case, body = _mmd_batch(harness)
    outside = tmp_path_factory.mktemp("ungranted") / "pose.vpd"
    outside.write_bytes(vpd_bytes())
    with pytest.raises(PermissionError):
        execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **{**body, "source_paths": [str(outside)]})
    assert not list(Path(body["model_path"]).parent.rglob("*.vpd"))


def test_motion_batch_does_not_overwrite_concurrent_character_edit(harness, monkeypatch):
    from core.media.avatar.mmd import MmdAdapter
    state, use_case, body = _mmd_batch(harness)
    original = MmdAdapter.import_state
    def prepare(adapter, *args):
        result = original(adapter, *args)
        state.config_manager.get_character_by_name("Haru").character_setting = "Edited while importing"
        return result
    monkeypatch.setattr(MmdAdapter, "import_state", prepare)
    with pytest.raises(ValueError, match="changed during"):
        execute(use_case, CharacterOperation.IMPORT_MODEL_STATES, **body)
    character = state.config_manager.get_character_by_name("Haru")
    assert character.character_setting == "Edited while importing"
    assert character.avatars["mmd"].sprites == []
    assert not list(Path(body["model_path"]).parent.rglob("*.vpd"))


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


def test_pmx_import_state_and_protected_texture_route(harness):
    state, use_case, entry = harness
    texture = entry.parent / "TEX" / "face.png"
    texture.parent.mkdir()
    texture.write_bytes(b"texture")
    model_entry = entry.parent / "model.pmx"
    model_entry.write_bytes(pmx_bytes(r"TEX\face.png"))
    imported = execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="mmd", source_path=str(model_entry))
    model = imported["avatars"]["mmd"]["model_path"]
    assert imported["avatar_type"] == "mmd"
    assert model_file(state, model, "TEX/face.png").read_bytes() == b"texture"
    with pytest.raises(PermissionError):
        model_file(state, model, "sample.moc3")
    camera = {"yaw": 25, "pitch": -5, "zoom": 1.5, "panX": 0.1, "panY": 0}
    saved = execute(use_case, CharacterOperation.SAVE_MODEL_STATE, name="Haru", avatar_type="mmd", model_path=model,
                    sprite_index=-1, path="", state={"morphs": {"笑顔": 0.5}, "mouthMorph": "あ", "blinkMorph": "まばたき", "camera": camera}, tags="happy")
    state_path = Path(saved["avatars"]["mmd"]["sprites"][0]["path"])
    restored = json.loads(model_file(state, model, state_path.relative_to(Path(model).parent).as_posix()).read_text())
    assert restored["morphs"] == {"笑顔": 0.5}
    assert restored["camera"] == camera


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("invalid", ["truncated", "empty"])
def test_invalid_pmx_never_replaces_bank_or_leaves_managed_files(harness, monkeypatch, staged, invalid):
    from application.characters import model_assets

    state, use_case, entry = harness
    execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="l2d", source_path=str(entry))
    before = state.config_manager.get_character_by_name("Haru").model_dump(mode="json")
    root = Path(state.project_root_dir)
    persisted = (root / "characters.json").read_bytes()
    managed = root / "data" / "sprite" / "haru" / "avatars"
    files_before = {path for path in managed.rglob("*") if path.is_file()}
    sections = pmx_sections()
    broken = (b"".join(sections[key] for key in ("header", "vertices", "faces", "textures"))
              if invalid == "truncated" else pmx_bytes(vertex_count=0))
    source = entry.parent / "model.pmx"
    source.write_bytes(pmx_bytes() if staged else broken)
    if staged:
        original_copy = model_assets.shutil.copy2

        def corrupt_staged_copy(src, dst):
            result = original_copy(src, dst)
            if Path(src) == source:
                Path(dst).write_bytes(broken)
            return result

        monkeypatch.setattr(model_assets.shutil, "copy2", corrupt_staged_copy)
    with pytest.raises(ValueError):
        execute(use_case, CharacterOperation.IMPORT_MODEL, name="Haru", avatar_type="mmd", source_path=str(source))
    assert state.config_manager.get_character_by_name("Haru").model_dump(mode="json") == before
    assert (root / "characters.json").read_bytes() == persisted
    assert {path for path in managed.rglob("*") if path.is_file()} == files_before
    assert not list(managed.rglob(".import-*"))


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
