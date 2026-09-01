from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
import yaml

from application.effects import (
    EffectExportResult,
    EffectOperation,
    EffectRequest,
    EffectUseCase,
)
from config.domain.schema import Effect


def _effect(name: str, *, audio_list=None, audio_tags: str = "", **values) -> Effect:
    return Effect.model_validate(
        {
            "name": name,
            "audio_list": list(audio_list or ()),
            "audio_tags": audio_tags,
            **values,
        }
    )


class _ConfigManager:
    def __init__(self, effects=()) -> None:
        self.config = SimpleNamespace(effect_list=list(effects))
        self.saved = 0
        self.reloaded = 0

    def get_effect_by_name(self, name: str):
        return next(
            (
                effect
                for effect in self.config.effect_list
                if effect.name.lower() == name.lower()
            ),
            None,
        )

    def save_effect_config(self) -> None:
        self.saved += 1

    def reload(self) -> None:
        self.reloaded += 1


def _use_case(tmp_path: Path, effects=(), *, roots=()) -> tuple[EffectUseCase, _ConfigManager]:
    manager = _ConfigManager(effects)
    use_case = EffectUseCase(
        manager,
        project_root=tmp_path,
        local_file_access_roots=roots or (tmp_path,),
    )
    return use_case, manager


def _execute(use_case: EffectUseCase, operation: EffectOperation, **payload):
    return use_case.execute(EffectRequest(operation, payload))


def test_save_rename_resolves_collision_and_moves_managed_audio(tmp_path: Path) -> None:
    old_audio = tmp_path / "data" / "effects" / "Old" / "hit.wav"
    old_audio.parent.mkdir(parents=True)
    old_audio.write_bytes(b"audio")
    use_case, manager = _use_case(
        tmp_path,
        (
            _effect("Old", audio_list=[old_audio.as_posix()]),
            _effect("Taken"),
        ),
    )

    result = _execute(
        use_case,
        EffectOperation.SAVE,
        originalName="Old",
        effect={"name": "Taken", "audio_list": [old_audio.as_posix()]},
    )

    assert result.name == "Taken_1"
    assert {effect.name for effect in manager.config.effect_list} == {"Taken", "Taken_1"}
    assert not old_audio.exists()
    assert Path(result.audio_list[0]).read_bytes() == b"audio"
    assert manager.saved == 1


def test_save_and_delete_reject_storage_traversal(tmp_path: Path) -> None:
    use_case, manager = _use_case(tmp_path, (_effect("../outside"),))
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError):
        _execute(use_case, EffectOperation.SAVE, name="../outside")
    with pytest.raises(ValueError):
        _execute(use_case, EffectOperation.DELETE, name="../outside")

    assert outside.is_dir()
    assert manager.saved == 0


def test_upload_uses_allowed_roots_and_keeps_tag_alignment(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    first = allowed / "hit.wav"
    second = allowed / "hit-2.wav"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    use_case, manager = _use_case(tmp_path, (_effect("Impact"),), roots=(allowed,))

    result = _execute(
        use_case,
        EffectOperation.UPLOAD_AUDIO,
        name="Impact",
        paths=[first.as_posix(), second.as_posix(), (tmp_path / "blocked.wav").as_posix()],
    )

    assert len(result.audio_list) == 2
    assert result.audio_tags == "特效 1：\n特效 2：\n"
    assert all(Path(path).is_file() for path in result.audio_list)
    assert manager.saved == 1


def test_delete_audio_preserves_external_file_and_rebuilds_tags(tmp_path: Path) -> None:
    external = tmp_path / "external.wav"
    external.write_bytes(b"keep")
    use_case, _ = _use_case(
        tmp_path,
        (
            _effect(
                "Impact",
                audio_list=[external.as_posix(), "missing.wav"],
                audio_tags="特效 1：external\n特效 2：missing\n",
            ),
        ),
    )

    result = _execute(use_case, EffectOperation.DELETE_AUDIO, name="Impact", index=0)

    assert external.read_bytes() == b"keep"
    assert result.audio_list == ["missing.wav"]
    assert result.audio_tags == "特效 1：missing\n"


def test_import_validates_names_and_uses_one_config_commit(tmp_path: Path) -> None:
    archive = tmp_path / "effect.ef"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "effect.yaml",
            yaml.safe_dump([{"name": "Impact", "audio_list": ["old/hit.wav"]}]),
        )
        package.writestr("audio/hit.wav", b"audio")
    use_case, manager = _use_case(tmp_path, (_effect("Impact"),))

    result = _execute(use_case, EffectOperation.IMPORT, paths=[archive.as_posix()])

    assert [effect.name for effect in result] == ["Impact_1"]
    assert Path(result[0].audio_list[0]).read_bytes() == b"audio"
    assert manager.saved == 1
    assert manager.reloaded == 1


def test_import_rejects_unsafe_effect_name(tmp_path: Path) -> None:
    archive = tmp_path / "bad.ef"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "effect.yaml",
            yaml.safe_dump([{"name": "../outside", "audio_list": []}]),
        )
    use_case, manager = _use_case(tmp_path)

    with pytest.raises(ValueError):
        _execute(use_case, EffectOperation.IMPORT, paths=[archive.as_posix()])

    assert not (tmp_path / "outside").exists()
    assert manager.saved == 0


def test_export_packages_managed_and_allowed_external_audio(tmp_path: Path) -> None:
    managed = tmp_path / "data" / "effects" / "Impact" / "hit.wav"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"managed")
    external = tmp_path / "external.wav"
    external.write_bytes(b"external")
    use_case, _ = _use_case(
        tmp_path,
        (
            _effect(
                "Impact",
                audio_list=["data/effects/Impact/hit.wav", external.as_posix()],
            ),
        ),
    )

    result = _execute(use_case, EffectOperation.EXPORT, name="Impact")

    assert isinstance(result, EffectExportResult)
    assert result.path == "output/Impact.ef"
    with zipfile.ZipFile(tmp_path / result.path) as package:
        assert sorted(package.namelist()) == [
            "audio/external.wav",
            "audio/hit.wav",
            "effect.yaml",
        ]
        exported = yaml.safe_load(package.read("effect.yaml"))[0]
        assert exported["audio_list"] == [
            "audio/hit.wav",
            "audio/external.wav",
        ]
        assert package.read("audio/hit.wav") == b"managed"
        assert package.read("audio/external.wav") == b"external"


def test_export_renames_colliding_audio_filenames(tmp_path: Path) -> None:
    managed = tmp_path / "data" / "effects" / "Impact" / "hit.wav"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"managed")
    external = tmp_path / "external" / "hit.wav"
    external.parent.mkdir()
    external.write_bytes(b"external")
    use_case, _ = _use_case(
        tmp_path,
        (_effect("Impact", audio_list=[managed.as_posix(), external.as_posix()]),),
    )

    result = _execute(use_case, EffectOperation.EXPORT, name="Impact")

    assert isinstance(result, EffectExportResult)
    with zipfile.ZipFile(tmp_path / result.path) as package:
        exported = yaml.safe_load(package.read("effect.yaml"))[0]
        assert exported["audio_list"] == ["audio/hit.wav", "audio/hit_1.wav"]
        assert package.read("audio/hit.wav") == b"managed"
        assert package.read("audio/hit_1.wav") == b"external"


def test_export_rejects_missing_audio_instead_of_writing_dangling_path(
    tmp_path: Path,
) -> None:
    use_case, _ = _use_case(
        tmp_path,
        (_effect("Impact", audio_list=["missing.wav"]),),
    )

    with pytest.raises(FileNotFoundError):
        _execute(use_case, EffectOperation.EXPORT, name="Impact")

    assert not (tmp_path / "output" / "Impact.ef").exists()
