from __future__ import annotations

from pathlib import Path

import pytest

from tools.crop_sprite import batch_crop_upper_half
from tools.remove_bg import batch_remove_background


@pytest.mark.parametrize(
    "operation",
    (
        lambda: batch_crop_upper_half(0.5, "./images", "output"),
        lambda: batch_remove_background("./images", "output"),
    ),
)
def test_batch_sprite_tools_reject_input_aliases_before_creating_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "images").mkdir()

    with pytest.raises(ValueError, match="exact"):
        operation()

    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "operation",
    (
        lambda: batch_crop_upper_half(0.5, "images", "output"),
        lambda: batch_remove_background("images", "output"),
    ),
)
def test_batch_sprite_tools_reject_symlinked_input_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
) -> None:
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    try:
        (project / "images").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        operation()

    assert not (project / "output").exists()


@pytest.mark.parametrize(
    "operation",
    (
        lambda: batch_crop_upper_half(0.5, "images", "./output"),
        lambda: batch_remove_background("images", "output//nested"),
    ),
)
def test_batch_sprite_tools_reject_output_aliases_before_creating_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "images").mkdir()

    with pytest.raises(ValueError, match="exact"):
        operation()

    assert not (tmp_path / "output").exists()
