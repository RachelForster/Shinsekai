"""Unit tests for core runtime pip constraints generation and host manifest detection."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from core.runtime_env.constraints import (
    core_runtime_constraint_lines,
    host_core_requirements_path,
    is_host_requirements_file,
    temporary_core_constraints_file,
)


def test_core_runtime_constraint_lines_filters_extras_torch_markers_and_comments(tmp_path: Path) -> None:
    req_file = tmp_path / "requirements-runtime-core.txt"
    other_platform = "win32" if sys.platform != "win32" else "darwin"
    req_file.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "-r other.txt",
                "--extra-index-url https://example.test/simple",
                "requests",
                "huggingface-hub==0.36.2  # pinned core package",
                "filelock>=3.13,<4",
                "rembg[cpu]>=2.0.0,<3.0",
                f'active-pkg>=1.2.3; sys_platform == "{sys.platform}"',
                f'inactive-pkg>=9.9.9; sys_platform == "{other_platform}"',
                "torch==2.7.1",
                "torchvision==0.22.1",
                "torchaudio==2.7.1",
                "excluded-pkg>=1.0",
            ]
        ),
        encoding="utf-8",
    )

    assert host_core_requirements_path(tmp_path) == req_file
    lines = core_runtime_constraint_lines(tmp_path, exclude_names=("Excluded_Pkg",))
    assert lines == [
        "huggingface-hub==0.36.2",
        "filelock<4,>=3.13",
        "rembg<3.0,>=2.0.0",
        "active-pkg>=1.2.3",
    ]


def test_is_host_requirements_file_distinguishes_root_vs_plugin_manifests(tmp_path: Path) -> None:
    root_core = tmp_path / "requirements-runtime-core.txt"
    root_reqs = tmp_path / "requirements.txt"
    other_txt = tmp_path / "other.txt"
    plugin_reqs = tmp_path / "plugins" / "demo" / "requirements.txt"
    plugin_reqs.parent.mkdir(parents=True)

    for p in (root_core, root_reqs, other_txt, plugin_reqs):
        p.write_text("requests\n", encoding="utf-8")

    assert is_host_requirements_file(root_core, project_root=tmp_path) is True
    assert is_host_requirements_file(root_reqs, project_root=tmp_path) is True
    assert is_host_requirements_file(other_txt, project_root=tmp_path) is False
    assert is_host_requirements_file(plugin_reqs, project_root=tmp_path) is False


def test_temporary_core_constraints_file_writes_and_cleans_up_on_success_and_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements-runtime-core.txt").write_text(
        "qrcode>=7.4,<9\n", encoding="utf-8"
    )

    created_path: Path | None = None
    with temporary_core_constraints_file(tmp_path) as path:
        assert path is not None and path.is_file()
        assert path.read_text(encoding="utf-8") == "qrcode<9,>=7.4\n"
        created_path = path
    assert created_path is not None and not created_path.exists()

    created_on_err: Path | None = None
    with pytest.raises(RuntimeError, match="boom"):
        with temporary_core_constraints_file(tmp_path) as path:
            created_on_err = path
            raise RuntimeError("boom")
    assert created_on_err is not None and not created_on_err.exists()

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    (empty_root / "requirements-runtime-core.txt").write_text("requests\n", encoding="utf-8")
    with temporary_core_constraints_file(empty_root) as path:
        assert path is None
