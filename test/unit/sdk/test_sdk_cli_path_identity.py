from __future__ import annotations

from pathlib import Path

import pytest

from sdk.cli.__main__ import _resolve_create_root, main
from sdk.cli.registry_ops import exact_registry_entry, normalize_repo_slug, run_git_commit
from sdk.cli.scaffold import validate_package_name, write_plugin_project


def test_plugin_package_name_is_not_silently_trimmed():
    assert validate_package_name("demo_plugin") == "demo_plugin"
    with pytest.raises(ValueError, match="snake_case"):
        validate_package_name(" demo_plugin")


def test_registry_entry_is_not_silently_trimmed():
    assert exact_registry_entry("plugins.demo.plugin:DemoPlugin") == (
        "plugins.demo.plugin:DemoPlugin"
    )
    with pytest.raises(ValueError, match="surrounding whitespace"):
        exact_registry_entry(" plugins.demo.plugin:DemoPlugin")


@pytest.mark.parametrize(
    "raw",
    (
        " owner/demo",
        "owner/demo ",
        "/owner/demo",
        "owner/demo/",
        "owner//demo",
        "owner/./demo",
        "owner/team/demo",
    ),
)
def test_registry_repo_slug_is_not_silently_canonicalized(raw):
    with pytest.raises(ValueError, match="exact owner/name"):
        normalize_repo_slug(raw)


def test_registry_repo_slug_preserves_exact_display_identity():
    assert normalize_repo_slug("Owner/Demo_Plugin") == "Owner/Demo_Plugin"


def test_registry_commit_uses_one_portable_relative_path_identity(tmp_path, monkeypatch):
    calls: list[tuple[list[str], str]] = []

    def fake_run(command, *, cwd, check):
        assert check is True
        calls.append((command, cwd))

    monkeypatch.setattr("sdk.cli.registry_ops.subprocess.run", fake_run)

    run_git_commit(
        tmp_path,
        "registry: update",
        file_path=r"nested\plugins.json",
    )

    git_path = calls[0][0][0]
    assert calls == [
        (
            [git_path, "add", "--", "nested/plugins.json"],
            str(tmp_path),
        ),
        (
            [git_path, "commit", "-m", "registry: update"],
            str(tmp_path),
        ),
    ]
    assert Path(git_path).is_absolute()


@pytest.mark.parametrize(
    "raw",
    (
        "../plugins.json",
        "nested/../plugins.json",
        "./plugins.json",
        "nested//plugins.json",
    ),
)
def test_registry_commit_rejects_aliased_relative_file_path(
    tmp_path,
    monkeypatch,
    raw,
):
    calls = []
    monkeypatch.setattr(
        "sdk.cli.registry_ops.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        run_git_commit(tmp_path, "registry: update", file_path=raw)

    assert calls == []


@pytest.mark.parametrize("raw", ("./plugins", "plugins//nested", "plugins/../other"))
def test_plugin_scaffold_root_rejects_lexical_aliases(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))

    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        _resolve_create_root(raw)

    assert list(tmp_path.iterdir()) == []


def test_plugin_scaffold_writer_rejects_relative_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        write_plugin_project(
            root=Path("relative-root"),
            package="demo_plugin",
            plugin_id="com.example.demo_plugin",
            display_name="Demo",
            include_settings_ui=False,
        )

    assert list(tmp_path.iterdir()) == []


def test_plugin_scaffold_writer_rejects_symlinked_root(tmp_path):
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        write_plugin_project(
            root=alias,
            package="demo_plugin",
            plugin_id="com.example.demo_plugin",
            display_name="Demo",
            include_settings_ui=False,
        )

    assert list(external.iterdir()) == []


def test_registry_file_must_remain_inside_selected_clone(tmp_path, monkeypatch):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    outside = tmp_path / "outside.json"
    project.mkdir()
    registry.mkdir()
    outside.write_text("[]\n", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="outside project root"):
        main(
            [
                "registry-append",
                "--registry",
                registry.as_posix(),
                "--file",
                outside.as_posix(),
                "--name",
                "Demo",
                "--author",
                "Tester",
                "--repo",
                "owner/demo",
                "--description",
                "demo",
                "--entry",
                "demo.plugin:DemoPlugin",
            ]
        )

    assert outside.read_text(encoding="utf-8") == "[]\n"


def test_registry_root_must_not_be_a_symlinked_clone(tmp_path, monkeypatch):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    alias = tmp_path / "registry-alias"
    project.mkdir()
    registry.mkdir()
    (registry / "plugins.json").write_text("[]\n", encoding="utf-8")
    try:
        alias.symlink_to(registry, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        main(
            [
                "registry-append",
                "--registry",
                alias.as_posix(),
                "--name",
                "Demo",
                "--author",
                "Tester",
                "--repo",
                "owner/demo",
                "--description",
                "demo",
                "--entry",
                "demo.plugin:DemoPlugin",
            ]
        )

    assert (registry / "plugins.json").read_text(encoding="utf-8") == "[]\n"
