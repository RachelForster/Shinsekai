"""Unit tests for Pass-Through packaging, temp-dir isolation, and rollback guarantees."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zipfile

import pytest

from application.backgrounds import (
    BackgroundOperation,
    BackgroundUseCase,
    parse_background_request,
)
from application.characters import (
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.effects import EffectOperation, EffectRequest, EffectUseCase
from application.runtime.stores import AppStoresConfigBackend, build_app_stores
from config.config_manager import ConfigManager
from config.models import Background, Character, Effect, Sprite
from core.packaging import (
    export_character_package,
    stage_character_package_import,
)


def test_sprite_validation_performs_no_disk_io() -> None:
    sprite = Sprite(
        path="nonexistent/folder/missing_sprite.png",
        voice_path="nonexistent/folder/missing_voice.wav",
    )
    assert sprite.path == "nonexistent/folder/missing_sprite.png"
    assert sprite.voice_path == "nonexistent/folder/missing_voice.wav"


def test_packaging_uses_system_temp_dir_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    char = Character(name="Rin", color="#cc2244", sprite_prefix="rin")
    out_zip = tmp_path / "out" / "Rin.char"
    export_character_package(
        [char],
        out_zip,
        sprite_dir=tmp_path / "data" / "sprite",
        speech_dir=tmp_path / "data" / "speech",
        model_dir=tmp_path / "data" / "models",
    )
    assert out_zip.is_file()
    staged = stage_character_package_import(
        out_zip,
        existing_names=(),
        existing_prefixes=(),
        sprite_dir=tmp_path / "dst" / "sprite",
        speech_dir=tmp_path / "dst" / "speech",
        model_dir=tmp_path / "dst" / "models",
    )
    assert len(staged.characters) == 1
    assert list(cwd_dir.iterdir()) == []


def test_character_import_rolls_back_media_dirs_on_db_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Build valid .char package
    src = tmp_path / "src"
    sprite_src = src / "data" / "sprite" / "nana"
    sprite_src.mkdir(parents=True)
    (sprite_src / "smile.png").write_bytes(b"png-bytes")
    char = Character(
        name="Nana",
        color="#ff88aa",
        sprite_prefix="nana",
        sprites=[Sprite(path=str(sprite_src / "smile.png"))],
    )
    archive = tmp_path / "Nana.char"
    export_character_package(
        [char],
        archive,
        sprite_dir=src / "data" / "sprite",
        speech_dir=src / "data" / "speech",
        model_dir=src / "data" / "models",
    )

    dst = tmp_path / "dst"
    dst.mkdir()
    stores = build_app_stores(dst, bind_globals=False)
    try:
        cm = object.__new__(ConfigManager)
        cm._backend = AppStoresConfigBackend(stores)
        cm._config = None
        cm.reload()

        state = SimpleNamespace(
            project_root_dir=str(dst),
            template_dir_path=str(dst / "data" / "character_templates"),
            config_manager=cm,
            character_manager=SimpleNamespace(),
            stores=stores,
        )
        uc = CharacterUseCase(state, file_access_roots=(tmp_path,))

        def fail_put(*_args, **_kwargs):
            raise sqlite3.OperationalError("simulated db commit failure")

        monkeypatch.setattr(stores.characters, "put", fail_put)
        with pytest.raises(sqlite3.OperationalError, match="simulated db commit failure"):
            uc.execute(parse_character_request(CharacterOperation.IMPORT, {"paths": [str(archive)]}))

        assert not (dst / "data" / "sprite" / "nana").exists()
        assert stores.characters.list_all() == ()
    finally:
        stores.close()


def test_background_and_effect_import_roll_back_media_on_save_failure(tmp_path: Path) -> None:
    # Build minimal .bg and .ef archives
    bg_archive = tmp_path / "room.bg"
    with zipfile.ZipFile(bg_archive, "w") as zf:
        zf.writestr(
            "background.yaml",
            '[{"name": "Room", "sprite_prefix": "room", "sprites": [{"path": "bg.png"}]}]',
        )
        zf.writestr("sprites/room/bg.png", b"png")

    ef_archive = tmp_path / "boom.ef"
    with zipfile.ZipFile(ef_archive, "w") as zf:
        zf.writestr("effect.yaml", '[{"name": "Boom", "audio_list": ["audio/hit.wav"]}]')
        zf.writestr("audio/hit.wav", b"wav")

    class FailingConfigManager:
        def __init__(self):
            self.config = SimpleNamespace(background_list=[], effect_list=[])

        def save_background_config(self):
            raise OSError("disk full")

        def save_effect_config(self):
            raise OSError("disk full")

    cfg = FailingConfigManager()
    bg_uc = BackgroundUseCase(
        SimpleNamespace(config_manager=cfg, background_manager=SimpleNamespace(), project_root_dir=str(tmp_path)),
        file_access_roots=(tmp_path,),
    )
    with pytest.raises(OSError, match="disk full"):
        bg_uc.execute(parse_background_request(BackgroundOperation.IMPORT, {"paths": [str(bg_archive)]}))
    assert not (tmp_path / "data" / "backgrounds" / "room").exists()

    ef_uc = EffectUseCase(cfg, project_root=tmp_path, local_file_access_roots=(tmp_path,))
    with pytest.raises(OSError, match="disk full"):
        ef_uc.execute(EffectRequest(EffectOperation.IMPORT, {"paths": [str(ef_archive)]}))
    assert not (tmp_path / "data" / "effects" / "Boom").exists()
