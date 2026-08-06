from __future__ import annotations

import pytest

from ai.tools.mcp_config_file import (
    read_mcp_config,
    require_openable_mcp_config_path,
    resolve_mcp_config_path,
    resolve_mcp_stdio_working_directory,
    write_mcp_config,
)


def test_default_mcp_config_uses_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)

    write_mcp_config({"enabled": False, "servers": [{"name": "demo"}]})

    expected = project / "data/config/mcp.yaml"
    assert expected.is_file()
    assert read_mcp_config()["enabled"] is False
    assert not (unrelated / "data").exists()


def test_explicit_mcp_project_root_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        resolve_mcp_config_path(project_root="relative-project")


def test_explicit_empty_mcp_config_path_does_not_select_the_default(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        resolve_mcp_config_path("", project_root=tmp_path)


@pytest.mark.parametrize(
    ("path", "project_root"),
    [
        (" data/config/mcp.yaml", None),
        (None, " /tmp/project"),
    ],
)
def test_mcp_paths_reject_outer_whitespace(path, project_root):
    with pytest.raises(ValueError, match="non-portable|project root"):
        resolve_mcp_config_path(path, project_root=project_root)


@pytest.mark.parametrize(
    "path",
    (
        "./data/config/mcp.yaml",
        "data//config/mcp.yaml",
        "data/other/../config/mcp.yaml",
    ),
)
def test_mcp_paths_reject_lexical_aliases(tmp_path, path):
    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        resolve_mcp_config_path(path, project_root=tmp_path)


def test_mcp_path_rejects_absolute_lexical_alias(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="lexical path aliases"):
        resolve_mcp_config_path(
            f"{project.as_posix()}/./data/config/mcp.yaml",
            project_root=project,
        )


def test_explicit_external_mcp_config_rejects_linked_parent(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    project.mkdir()
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_mcp_config_path(
            alias / "mcp.yaml",
            project_root=project,
        )


def test_default_mcp_config_rejects_intermediate_symlink_escape(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    marker = external / "mcp.yaml"
    marker.write_text("enabled: false\n", encoding="utf-8")
    try:
        (project / "data" / "config").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic links|escapes project root"):
        write_mcp_config({"enabled": True})

    assert marker.read_text(encoding="utf-8") == "enabled: false\n"


def test_default_mcp_config_rejects_internal_symlink_alias(tmp_path, monkeypatch):
    project = tmp_path / "project"
    alias_target = project / "alternate-config"
    (project / "data").mkdir(parents=True)
    alias_target.mkdir()
    try:
        (project / "data/config").symlink_to(alias_target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic links"):
        write_mcp_config({"enabled": True})

    assert list(alias_target.iterdir()) == []


def test_bound_absolute_mcp_path_is_revalidated_before_write(tmp_path, monkeypatch):
    project = tmp_path / "project"
    config_dir = project / "data/config"
    external = tmp_path / "external"
    config_dir.mkdir(parents=True)
    external.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    bound_path = resolve_mcp_config_path()
    config_dir.rmdir()
    try:
        config_dir.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        write_mcp_config({"enabled": True}, bound_path)

    assert list(external.iterdir()) == []


def test_bound_mcp_path_is_revalidated_before_open(tmp_path, monkeypatch):
    project = tmp_path / "project"
    config_dir = project / "data/config"
    external = tmp_path / "external"
    config_dir.mkdir(parents=True)
    external.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    bound_path = resolve_mcp_config_path()
    config_dir.rmdir()
    try:
        config_dir.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        require_openable_mcp_config_path(bound_path)


def test_mcp_stdio_working_directory_is_bound_to_project_root_after_cwd_changes(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    working = project / "servers/demo"
    unrelated = tmp_path / "unrelated"
    working.mkdir(parents=True)
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert resolve_mcp_stdio_working_directory(
        "servers/demo",
        project_root=project,
    ) == working
    assert resolve_mcp_stdio_working_directory(
        project_root=project,
    ) == project


@pytest.mark.parametrize(
    "value",
    (
        "./servers/demo",
        "servers//demo",
        "servers/../demo",
    ),
)
def test_mcp_stdio_working_directory_rejects_lexical_aliases(tmp_path, value):
    project = tmp_path / "project"
    (project / "servers/demo").mkdir(parents=True)

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        resolve_mcp_stdio_working_directory(
            value,
            project_root=project,
        )


def test_mcp_stdio_working_directory_rejects_linked_alias(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    try:
        (project / "server").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(
        PermissionError,
        match="symbolic link|escapes project root",
    ):
        resolve_mcp_stdio_working_directory(
            "server",
            project_root=project,
        )
