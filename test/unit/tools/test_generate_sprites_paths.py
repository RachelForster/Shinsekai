from __future__ import annotations

from pathlib import Path

import pytest

from tools.generate_sprites import (
    _existing_input_image,
    _output_parent_identity,
    _publish_generated_image,
    _writable_output_directory,
    _writable_output_file,
)


@pytest.mark.parametrize(
    "raw",
    (
        "./reference.png",
        "images//reference.png",
        "images/../reference.png",
    ),
)
def test_sprite_generator_rejects_input_aliases_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "reference.png").write_bytes(b"not-an-image")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "reference.png").write_bytes(b"not-an-image")

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        _existing_input_image(raw)


def test_sprite_generator_rejects_symlinked_input_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    target = external / "reference.png"
    target.write_bytes(b"not-an-image")
    alias = project / "reference.png"
    try:
        alias.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        _existing_input_image("reference.png")


@pytest.mark.parametrize(
    "resolver,raw",
    (
        (_writable_output_file, "./sprite.png"),
        (_writable_output_file, "images//sprite.png"),
        (_writable_output_directory, "images/../sprites"),
    ),
)
def test_sprite_generator_rejects_output_aliases_before_creating_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolver,
    raw: str,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        resolver(raw)

    assert list(tmp_path.iterdir()) == []


def test_sprite_generator_rejects_replaced_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    output = _writable_output_file("generated/sprite.png")
    expected_parent_identity = _output_parent_identity(output)
    preserved = tmp_path / "generated-preserved"
    output.parent.rename(preserved)
    output.parent.mkdir()
    peer = output.parent / output.name
    peer.write_bytes(b"peer")

    with pytest.raises(PermissionError, match="identity changed"):
        _publish_generated_image(
            output,
            b"generated",
            expected_parent_identity=expected_parent_identity,
        )

    assert peer.read_bytes() == b"peer"
    assert not (preserved / output.name).exists()
