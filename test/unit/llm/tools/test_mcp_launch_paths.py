from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ai.tools.mcp_tool_setup import _capture_mcp_stdio_launch


def test_mcp_stdio_launch_binds_relative_cwd_independently_of_process_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    working = project / "servers/demo"
    unrelated = tmp_path / "unrelated"
    working.mkdir(parents=True)
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    launch = _capture_mcp_stdio_launch(
        {
            "command": sys.executable,
            "cwd": "servers/demo",
            "transport": "stdio",
        },
        project_root=project,
    )

    assert launch.working_directory.path == working
    assert launch.command.path == Path(sys.executable).resolve()


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_mcp_stdio_launch_resolves_bare_command_from_explicit_environment_path(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    binary_dir = tmp_path / "bin"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    binary_dir.mkdir()
    unrelated.mkdir()
    executable = binary_dir / "mcp-demo"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.chdir(unrelated)
    monkeypatch.setenv("PATH", "/does/not/exist")

    launch = _capture_mcp_stdio_launch(
        {
            "command": "mcp-demo",
            "env": {"PATH": binary_dir.as_posix()},
            "transport": "stdio",
        },
        project_root=project,
    )

    assert launch.command.path == executable
    assert launch.working_directory.path == project


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_mcp_stdio_launch_resolves_relative_command_against_bound_working_directory(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    working = project / "servers/demo"
    unrelated = tmp_path / "unrelated"
    executable = working / "bin/mcp-demo"
    executable.parent.mkdir(parents=True)
    unrelated.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.chdir(unrelated)

    launch = _capture_mcp_stdio_launch(
        {
            "command": "bin/mcp-demo",
            "cwd": "servers/demo",
            "transport": "stdio",
        },
        project_root=project,
    )

    assert launch.command.path == executable
    assert launch.working_directory.path == working
