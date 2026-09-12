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
from config.schema import Effect


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


def test_image_upload_audio_and_delete_keep_entries_aligned(tmp_path: Path) -> None:
    image = tmp_path / "item.png"
    audio = tmp_path / "item.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")
    use_case, manager = _use_case(tmp_path, (_effect("Items"),), roots=(tmp_path,))

    uploaded = _execute(
        use_case,
        EffectOperation.UPLOAD_IMAGES,
        name="Items",
        paths=[image.as_posix()],
    )
    paired = _execute(
        use_case,
        EffectOperation.UPLOAD_IMAGE_AUDIO,
        name="Items",
        index=0,
        path=audio.as_posix(),
    )

    assert len(uploaded.image_list) == 1
    assert paired.image_tags == "图片 1：\n"
    assert Path(paired.image_audio_list[0]).read_bytes() == b"audio"

    deleted = _execute(use_case, EffectOperation.DELETE_IMAGE, name="Items", index=0)

    assert deleted.image_list == []
    assert deleted.image_audio_list == []
    assert deleted.image_tags == ""
    assert manager.saved == 3


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


def test_effect_package_round_trips_images_and_bound_audio(tmp_path: Path) -> None:
    effect_dir = tmp_path / "data" / "effects" / "Items"
    effect_dir.mkdir(parents=True)
    image = effect_dir / "letter.png"
    bound_audio = effect_dir / "paper.wav"
    image.write_bytes(b"image")
    bound_audio.write_bytes(b"audio")
    effect = _effect(
        "Items",
        image_list=[image.as_posix()],
        image_tags="图片 1：letter\n",
        image_audio_list=[bound_audio.as_posix()],
    )
    use_case, _ = _use_case(tmp_path, (effect,), roots=(tmp_path,))

    exported = _execute(use_case, EffectOperation.EXPORT, name="Items")
    imported = _execute(
        use_case,
        EffectOperation.IMPORT,
        paths=[(tmp_path / exported.path).as_posix()],
    )

    assert imported[0].name == "Items_1"
    assert imported[0].image_tags == "图片 1：letter\n"
    assert Path(imported[0].image_list[0]).read_bytes() == b"image"
    assert Path(imported[0].image_audio_list[0]).read_bytes() == b"audio"
    with zipfile.ZipFile(tmp_path / exported.path) as package:
        assert "images/letter.png" in package.namelist()
        assert "image-audio/paper.wav" in package.namelist()


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


@pytest.mark.parametrize("media", ["audio", "image"])
def test_upload_keeps_existing_blank_rows_and_handles_missing_trailing_newline(tmp_path, media):
    source = tmp_path / ("new.png" if media == "image" else "new.wav")
    source.write_bytes(b"asset")
    effect = _effect("Rows", **{
        f"{media}_list": ["a.png", "b.png", "c.png"],
        f"{media}_tags": "Row 1: first\n\nRow 3: third：detail",
    })
    use_case, _ = _use_case(tmp_path, (effect,))
    operation = EffectOperation.UPLOAD_IMAGES if media == "image" else EffectOperation.UPLOAD_AUDIO
    uploaded = _execute(use_case, operation, name="Rows", paths=[str(source)])
    lines = getattr(uploaded, f"{media}_tags").splitlines()
    assert len(lines) == 4
    assert lines[0].endswith("：first")
    assert lines[1].endswith("：")
    assert lines[2].endswith("：third：detail")
    assert lines[3].endswith("：")
