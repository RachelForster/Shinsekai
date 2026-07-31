from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from plugin_system.host.service import (
    _plugin_manifest_path,
    append_plugin_manifest_entry_if_missing,
    managed_plugin_package_directory,
    read_plugin_manifest_items,
    remove_plugin_manifest_entry,
    set_plugin_manifest_enabled,
    write_plugin_manifest_items,
)


def test_plugin_manifest_path_rejects_outer_whitespace(tmp_path):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _plugin_manifest_path(Path(f" {tmp_path}/plugins.yaml"))


def test_plugin_manifest_path_rejects_absolute_lexical_alias(tmp_path):
    with pytest.raises(ValueError, match="lexical path aliases"):
        _plugin_manifest_path(
            f"{tmp_path.as_posix()}/./plugins.yaml",
        )


def test_plugin_manifest_path_rejects_symlinked_external_parent(tmp_path):
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _plugin_manifest_path(alias / "plugins.yaml")


def test_plugin_manifest_mutations_reject_whitespace_aliases(tmp_path):
    manifest = tmp_path / "plugins.yaml"
    write_plugin_manifest_items([{"entry": "plugins.demo:Plugin"}], manifest)

    with pytest.raises(ValueError, match="surrounding whitespace"):
        set_plugin_manifest_enabled(" plugins.demo:Plugin", False, manifest)
    with pytest.raises(ValueError, match="surrounding whitespace"):
        remove_plugin_manifest_entry("plugins.demo:Plugin ", manifest)
    with pytest.raises(ValueError, match="surrounding whitespace"):
        append_plugin_manifest_entry_if_missing(" demo.plugin:Plugin", path=manifest)

    assert read_plugin_manifest_items(manifest) == [
        {"entry": "plugins.demo:Plugin"}
    ]


def test_plugin_manifest_writer_rejects_invalid_entry_identity(tmp_path):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        write_plugin_manifest_items(
            [{"entry": " plugins.demo:Plugin"}],
            tmp_path / "plugins.yaml",
        )


def test_concurrent_manifest_appends_do_not_lose_entries(tmp_path):
    manifest = tmp_path / "plugins.yaml"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda index: append_plugin_manifest_entry_if_missing(
                    f"demo_{index}.plugin:Plugin",
                    path=manifest,
                ),
                range(20),
            )
        )

    assert results.count("added") == 20
    assert {item["entry"] for item in read_plugin_manifest_items(manifest)} == {
        f"plugins.demo_{index}.plugin:Plugin" for index in range(20)
    }


def test_manifest_publish_failure_preserves_previous_yaml(tmp_path, monkeypatch):
    manifest = tmp_path / "plugins.yaml"
    write_plugin_manifest_items([{"entry": "plugins.old:Plugin"}], manifest)
    previous = manifest.read_text(encoding="utf-8")

    def fail_replace(_source, _target, **_kwargs):
        raise OSError("publish failed")

    monkeypatch.setattr(
        "core.file_transactions.replace_file_transactionally",
        fail_replace,
    )

    with pytest.raises(OSError, match="publish failed"):
        write_plugin_manifest_items([{"entry": "plugins.new:Plugin"}], manifest)

    assert manifest.read_text(encoding="utf-8") == previous


def test_default_manifest_rejects_intermediate_symlink_escape(tmp_path, monkeypatch):
    project = tmp_path / "project"
    data = project / "data"
    external = tmp_path / "external-config"
    data.mkdir(parents=True)
    external.mkdir()
    try:
        (data / "config").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.delenv("EASYAI_PROJECT_ROOT", raising=False)

    with pytest.raises(PermissionError, match="escapes project root"):
        write_plugin_manifest_items([{"entry": "plugins.demo:Plugin"}])

    assert not (external / "plugins.yaml").exists()


def test_explicit_manifest_root_overrides_ambient_project_root(
    tmp_path,
    monkeypatch,
):
    ambient = tmp_path / "ambient"
    selected = tmp_path / "selected"
    ambient.mkdir()
    selected.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())

    write_plugin_manifest_items(
        [{"entry": "plugins.demo:Plugin"}],
        root=selected,
    )

    assert read_plugin_manifest_items(root=selected) == [
        {"entry": "plugins.demo:Plugin"}
    ]
    assert (selected / "data/config/plugins.yaml").is_file()
    assert not (ambient / "data/config/plugins.yaml").exists()


def test_strict_plugin_package_directory_rejects_exact_child_alias(tmp_path, monkeypatch):
    project = tmp_path / "project"
    plugins = project / "plugins"
    external = tmp_path / "external-plugin"
    plugins.mkdir(parents=True)
    external.mkdir()
    try:
        (plugins / "demo").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        managed_plugin_package_directory("plugins.demo.plugin:DemoPlugin")
