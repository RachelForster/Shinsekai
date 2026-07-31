from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.paths as core_paths
from core.paths import (
    _metadata_is_link_or_reparse_point,
    activate_project_root,
    app_root,
    managed_child_path,
    managed_project_directory,
    managed_project_file,
    path_is_link_or_reparse_point,
    portable_path_component_prefix,
    portable_project_path,
    project_root,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_path,
    resolve_project_read_path,
    resolve_executable_file,
    resolve_runtime_asset_path,
    resolve_runtime_asset_read_path,
    require_directory_without_links,
    require_regular_file_without_links,
    safe_path_component,
    safe_path_component_with_suffix,
    source_root,
    truncate_utf8_bytes,
    user_home_directory,
    validate_exact_path_text,
)


def test_link_metadata_recognizes_windows_reparse_points():
    metadata = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400),
    )

    assert _metadata_is_link_or_reparse_point(metadata)


def test_path_link_check_recognizes_windows_reparse_point_metadata(
    tmp_path,
    monkeypatch,
):
    candidate = tmp_path / "junction"
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path == candidate:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x00000400,
                ),
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    assert path_is_link_or_reparse_point(candidate) is True
    assert path_is_link_or_reparse_point(tmp_path / "missing") is False


def test_project_root_prefers_shinsekai_override_to_legacy_easyai(tmp_path, monkeypatch):
    shinsekai_root = tmp_path / "D drive" / "项目 データ"
    easyai_root = tmp_path / "legacy root"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(shinsekai_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert project_root() == shinsekai_root.resolve()


def test_runtime_roots_reject_environment_symlink_aliases(tmp_path, monkeypatch):
    real_root = tmp_path / "real-root"
    alias = tmp_path / "root-alias"
    real_root.mkdir()
    try:
        alias.symlink_to(real_root, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    for name, getter in (
        ("SHINSEKAI_SOURCE_ROOT", source_root),
        ("SHINSEKAI_APP_ROOT", app_root),
        ("SHINSEKAI_PROJECT_ROOT", project_root),
    ):
        monkeypatch.setenv(name, alias.as_posix())
        with pytest.raises(PermissionError, match="symbolic link"):
            getter()
        monkeypatch.delenv(name)


def test_user_home_directory_rejects_nonportable_identity(tmp_path, monkeypatch):
    invalid = Path(f"{tmp_path / 'home'} ")
    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda _cls: invalid),
    )

    with pytest.raises(ValueError, match="user home directory"):
        user_home_directory()


@pytest.mark.parametrize(
    "raw",
    [
        r"\\.\C:\device",
        r"\??\C:\native-device",
        r"\\?\GLOBALROOT\Device\HarddiskVolume1",
    ],
)
def test_exact_path_text_rejects_windows_non_filesystem_namespaces(raw):
    with pytest.raises(ValueError, match="Windows .*namespace"):
        validate_exact_path_text(
            raw,
            field="test path",
            allow_non_native_absolute=True,
        )


@pytest.mark.parametrize(
    "component",
    ["CON", "NUL.txt", "trailing.", "trailing ", "alternate:stream"],
)
def test_exact_absolute_paths_reject_nonportable_components(tmp_path, component):
    with pytest.raises(ValueError):
        validate_exact_path_text(tmp_path / component, field="test path")


@pytest.mark.skipif(os.name == "nt", reason="backslash is a native separator on Windows")
def test_posix_absolute_paths_reject_backslash_identity_split(tmp_path):
    raw = f"{tmp_path.as_posix()}/literal\\child"

    with pytest.raises(ValueError, match="non-portable"):
        validate_exact_path_text(raw, field="test path")
    with pytest.raises(ValueError, match="non-portable"):
        resolve_project_path(raw, root=tmp_path)
    with pytest.raises(ValueError, match="non-portable"):
        resolve_project_output_path(raw, root=tmp_path)


@pytest.mark.parametrize(
    "raw",
    [
        "//server/../asset",
        "//server/share/../asset",
        "//server/CON/asset",
    ],
)
def test_non_native_unc_roots_reject_aliases_and_device_components(raw):
    with pytest.raises(ValueError):
        validate_exact_path_text(
            raw,
            field="test path",
            allow_non_native_absolute=True,
        )


def test_exact_paths_reject_other_user_home_aliases_consistently():
    with pytest.raises(ValueError, match="current user-home alias"):
        validate_exact_path_text("~another-user/data/file.txt", field="test path")

    with pytest.raises(ValueError, match="exact absolute path"):
        resolve_project_path("data/file.txt", root="~another-user/project")


@pytest.mark.parametrize(
    ("environment_name", "resolver"),
    [
        ("SHINSEKAI_PROJECT_ROOT", project_root),
        ("SHINSEKAI_APP_ROOT", app_root),
        ("SHINSEKAI_SOURCE_ROOT", source_root),
    ],
)
def test_authoritative_environment_roots_reject_user_home_aliases(
    tmp_path,
    monkeypatch,
    environment_name,
    resolver,
):
    monkeypatch.setenv("HOME", tmp_path.as_posix())
    monkeypatch.setenv(environment_name, "~/shinsekai")

    with pytest.raises(ValueError, match="exact absolute path"):
        resolver()


def test_project_root_keeps_legacy_easyai_and_uses_stable_app_fallback(tmp_path, monkeypatch):
    easyai_root = tmp_path / "legacy root"
    app_fallback = tmp_path / "application root"
    cwd_root = tmp_path / "unrelated working root"
    app_fallback.mkdir()
    cwd_root.mkdir()
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert project_root() == easyai_root.resolve()

    monkeypatch.delenv("EASYAI_PROJECT_ROOT")
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", str(app_fallback))
    monkeypatch.chdir(cwd_root)
    assert project_root() == app_fallback.resolve()


def test_project_root_rejects_relative_environment_instead_of_rebasing_on_cwd(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "relative-project")

    with pytest.raises(ValueError, match="absolute"):
        project_root()


def test_project_root_rejects_filesystem_root(monkeypatch):
    filesystem_root = Path(Path.cwd().anchor)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(filesystem_root))

    with pytest.raises(ValueError, match="filesystem root"):
        project_root()
    with pytest.raises(ValueError, match="filesystem root"):
        resolve_project_path("data/config/api.yaml", root=filesystem_root)


def test_project_root_rejects_whitespace_override_without_falling_through(
    tmp_path,
    monkeypatch,
):
    fallback = tmp_path / "must-not-be-selected"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "   ")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", fallback.as_posix())

    with pytest.raises(ValueError, match="non-portable"):
        project_root()


def test_project_root_rejects_empty_current_override_without_using_legacy(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "must-not-be-selected"))

    with pytest.raises(ValueError, match="non-portable"):
        project_root()


def test_project_root_rejects_control_characters(monkeypatch, tmp_path):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", f"{tmp_path}/bad\nroot")

    with pytest.raises(ValueError, match="non-portable"):
        project_root()


def test_project_root_rejects_non_utf8_surrogate_text(monkeypatch, tmp_path):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", f"{tmp_path}/bad\udcffroot")

    with pytest.raises(ValueError, match="non-portable"):
        project_root()


def test_activate_project_root_syncs_environment_and_cwd(tmp_path, monkeypatch):
    selected = tmp_path / "selected project"
    legacy = tmp_path / "legacy project"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(selected))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(legacy))
    # Register cwd restoration with pytest before the production helper
    # intentionally switches to the selected root.
    monkeypatch.chdir(tmp_path)

    resolved = activate_project_root(tmp_path / "default")

    assert resolved == selected.resolve()
    assert Path.cwd() == selected.resolve()
    assert (selected / "data").is_dir()
    assert Path(project_root()) == selected.resolve()
    assert Path(os.environ["EASYAI_PROJECT_ROOT"]) == selected.resolve()


def test_activate_project_root_rejects_replaced_root_before_chdir(
    tmp_path,
    monkeypatch,
):
    launch_root = tmp_path / "launch"
    selected = tmp_path / "selected"
    preserved = tmp_path / "selected-preserved"
    launch_root.mkdir()
    monkeypatch.chdir(launch_root)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", selected.as_posix())
    real_change = core_paths._change_working_directory_to_identity
    replaced = False

    def replace_before_chdir(root, expected_identity, *, field):
        nonlocal replaced
        if not replaced:
            replaced = True
            root.rename(preserved)
            (root / "data").mkdir(parents=True)
            (root / "peer.txt").write_text("peer", encoding="utf-8")
        return real_change(root, expected_identity, field=field)

    monkeypatch.setattr(
        core_paths,
        "_change_working_directory_to_identity",
        replace_before_chdir,
    )

    with pytest.raises(RuntimeError, match="identity changed"):
        activate_project_root(tmp_path / "default")

    assert Path.cwd() == launch_root.resolve()
    assert (selected / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved / "data").is_dir()


def test_activate_project_root_rejects_relative_authoritative_environment(tmp_path, monkeypatch):
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.chdir(fallback)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "relative-project")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "must-not-be-used"))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT"):
        activate_project_root(tmp_path / "default")

    assert Path.cwd() == fallback


def test_activate_project_root_rejects_empty_current_environment_without_legacy_fallback(
    tmp_path,
    monkeypatch,
):
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.chdir(fallback)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "must-not-be-used"))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT"):
        activate_project_root(tmp_path / "default")

    assert Path.cwd() == fallback
    assert not (tmp_path / "must-not-be-used").exists()


def test_frozen_runtime_requires_an_explicit_project_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("EASYAI_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    with pytest.raises(RuntimeError, match="explicit SHINSEKAI_PROJECT_ROOT"):
        activate_project_root(tmp_path / "install-root")
    with pytest.raises(RuntimeError, match="explicit SHINSEKAI_PROJECT_ROOT"):
        project_root()

    assert not (tmp_path / "install-root" / "data").exists()


def test_activate_project_root_rejects_relative_default_instead_of_using_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("EASYAI_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="default project root"):
        activate_project_root("relative-default")

    assert not (tmp_path / "relative-default").exists()


def test_activate_project_root_rejects_a_file_without_falling_back(tmp_path, monkeypatch):
    invalid = tmp_path / "not-a-directory"
    invalid.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(invalid))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "must-not-be-used"))

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT"):
        activate_project_root(tmp_path / "default")


def test_activate_project_root_rejects_symlinked_data_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external-data"
    project.mkdir()
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (project / "data").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(RuntimeError, match="SHINSEKAI_PROJECT_ROOT"):
        activate_project_root(tmp_path / "default")

    assert marker.read_text(encoding="utf-8") == "keep"


def test_activate_project_root_rejects_symlinked_root(tmp_path, monkeypatch):
    external = tmp_path / "external-project"
    alias = tmp_path / "project-alias"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", alias.as_posix())

    with pytest.raises(RuntimeError, match="symbolic link"):
        activate_project_root(tmp_path / "default")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (external / "data").exists()


def test_activate_project_root_rejects_contained_data_alias(tmp_path, monkeypatch):
    project = tmp_path / "project"
    storage = project / "storage"
    project.mkdir()
    storage.mkdir()
    try:
        (project / "data").symlink_to(storage, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())

    with pytest.raises(RuntimeError, match="symbolic link"):
        activate_project_root(tmp_path / "default")

    assert list(storage.iterdir()) == []


def test_managed_project_file_rebases_stale_windows_asset_path(tmp_path):
    expected = tmp_path / "data" / "sprite" / "mika" / "smile.png"

    resolved = managed_project_file(
        r"D:\old-install\data\sprite\mika\smile.png",
        "data/sprite",
        root=tmp_path,
    )

    assert resolved == expected


def test_managed_project_file_rejects_external_and_drive_relative_paths(tmp_path):
    assert managed_project_file(tmp_path.parent / "outside.png", "data/sprite", root=tmp_path) is None
    assert managed_project_file("D:relative.png", "data/sprite", root=tmp_path) is None


def test_managed_project_file_never_rebases_an_existing_external_suffix_collision(tmp_path):
    project = tmp_path / "project"
    managed = project / "data/sprite/mika/smile.png"
    external = tmp_path / "external/data/sprite/mika/smile.png"
    managed.parent.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    managed.write_text("managed", encoding="utf-8")
    external.write_text("external", encoding="utf-8")

    assert managed_project_file(external, "data/sprite", root=project) is None
    assert managed.read_text(encoding="utf-8") == "managed"
    assert external.read_text(encoding="utf-8") == "external"


def test_managed_storage_rejects_symlinked_subdirectory_even_inside_project(tmp_path):
    project = tmp_path / "project"
    alias_target = project / "other-storage"
    data = project / "data"
    data.mkdir(parents=True)
    alias_target.mkdir()
    try:
        (data / "sprite").symlink_to(alias_target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        managed_project_directory("data/sprite", "character", root=project)

    with pytest.raises(PermissionError, match="symbolic links"):
        managed_project_file("data/sprite/character/a.png", "data/sprite", root=project)


def test_managed_child_rejects_link_hidden_in_base_ancestor(tmp_path):
    external = tmp_path / "external"
    external_base = external / "nested"
    alias = tmp_path / "alias"
    external_base.mkdir(parents=True)
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        managed_child_path(alias / "nested", "output.txt")

    assert not (external_base / "output.txt").exists()


def test_regular_file_contract_rejects_linked_leaf_and_parent(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "main.py"
    target.write_text("print('safe')", encoding="utf-8")
    linked_file = tmp_path / "linked-main.py"
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_file.symlink_to(target)
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    assert require_regular_file_without_links(target) == target
    with pytest.raises(PermissionError, match="symbolic link"):
        require_regular_file_without_links(linked_file)
    with pytest.raises(PermissionError, match="symbolic link"):
        require_regular_file_without_links(linked_parent / "main.py")


def test_directory_contract_rejects_files_and_linked_directories(tmp_path):
    directory = tmp_path / "runtime"
    file = tmp_path / "runtime.txt"
    linked = tmp_path / "runtime-link"
    directory.mkdir()
    file.write_text("not a directory", encoding="utf-8")
    try:
        linked.symlink_to(directory, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are unavailable")

    assert require_directory_without_links(directory) == directory
    with pytest.raises(NotADirectoryError):
        require_directory_without_links(file)
    with pytest.raises(PermissionError, match="symbolic link"):
        require_directory_without_links(linked)


def test_executable_contract_allows_only_a_leaf_alias(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "python"
    non_executable = real_parent / "not-python"
    target.write_text("", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    non_executable.write_text("", encoding="utf-8")
    linked_file = tmp_path / "venv-python"
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_file.symlink_to(target)
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    assert resolve_executable_file(target) == target
    assert resolve_executable_file(linked_file) == target
    if os.name != "nt":
        with pytest.raises(PermissionError, match="not executable"):
            resolve_executable_file(non_executable)
    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_executable_file(linked_parent / "python")


def test_managed_project_file_rejects_alias_below_storage_root(tmp_path):
    project = tmp_path / "project"
    real = project / "data" / "sprite" / "real"
    real.mkdir(parents=True)
    asset = real / "smile.png"
    asset.write_text("keep", encoding="utf-8")
    try:
        (real.parent / "alias").symlink_to(real, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    assert (
        managed_project_file(
            "data/sprite/alias/smile.png",
            "data/sprite",
            root=project,
        )
        is None
    )
    assert asset.read_text(encoding="utf-8") == "keep"


def test_managed_project_file_rejects_external_alias_back_into_project(tmp_path):
    project = tmp_path / "project"
    managed = project / "data" / "sprite" / "mika" / "smile.png"
    managed.parent.mkdir(parents=True)
    managed.write_text("keep", encoding="utf-8")
    external_alias = tmp_path / "external-alias.png"
    try:
        external_alias.symlink_to(managed)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    assert managed_project_file(external_alias, "data/sprite", root=project) is None
    assert managed.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "name",
    [
        "..",
        "nested/path",
        r"nested\path",
        "CON",
        "CLOCK$",
        "CONIN$.txt",
        "COM¹.log",
        "LPT³",
        "bad?.png",
        " leading",
        "trailing ",
        "bad\x7fname",
        "bad\udcffname",
        "a" * 256,
        "界" * 86,
    ],
)
def test_safe_path_component_rejects_nonportable_names(name):
    with pytest.raises(ValueError):
        safe_path_component(name)


def test_safe_path_component_accepts_the_portable_utf8_byte_boundary():
    assert safe_path_component("界" * 85) == "界" * 85


def test_truncate_utf8_bytes_never_splits_a_unicode_character():
    assert truncate_utf8_bytes("界" * 86, 255) == "界" * 85


def test_safe_path_component_with_suffix_reserves_bytes_for_suffix():
    candidate = safe_path_component_with_suffix("界" * 85, "_1.png")

    assert candidate == ("界" * 83) + "_1.png"
    assert len(candidate.encode("utf-8")) == 255
    assert safe_path_component(candidate) == candidate


def test_safe_path_component_with_suffix_rejects_an_unfittable_suffix():
    with pytest.raises(ValueError, match="suffix is too long"):
        safe_path_component_with_suffix("file", "x" * 255)


def test_portable_path_component_prefix_reserves_creator_bytes():
    prefix = portable_path_component_prefix(
        f".{'界' * 85}.",
        reserved_suffix_bytes=20,
    )
    eventual_name = f"{prefix}{'x' * 20}"

    assert len(eventual_name.encode("utf-8")) <= 255
    assert safe_path_component(eventual_name) == eventual_name


def test_explicit_helper_root_cannot_be_relative_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="project root must be an absolute path"):
        resolve_project_path("data/file.txt", root="relative-project")


def test_explicit_root_rejects_symlink_before_canonical_target_validation(tmp_path):
    target = tmp_path / "target:with-colon"
    target.mkdir()
    alias = tmp_path / "portable-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_project_path(".", root=alias)


def test_relative_project_path_cannot_escape_explicit_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(PermissionError, match="escapes project root"):
        resolve_project_path("../outside.txt", root=project)


def test_relative_project_path_normalizes_portable_backslash_separators(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    assert resolve_project_path(r"data\sprite\mika.png", root=project) == (
        project / "data/sprite/mika.png"
    )


@pytest.mark.parametrize(
    "resolver",
    [resolve_project_path, resolve_project_output_path],
)
@pytest.mark.parametrize("value", [" data/file.txt", "data/file.txt "])
def test_project_path_resolvers_reject_surrounding_whitespace(
    tmp_path,
    resolver,
    value,
):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="surrounding whitespace"):
        resolver(value, root=project)


@pytest.mark.parametrize(
    "value",
    [
        "data/./file.txt",
        "data//file.txt",
        "data/file.txt/",
        "./data/file.txt",
    ],
)
def test_managed_project_path_rejects_lexical_aliases_before_path_normalization(
    tmp_path,
    value,
):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="exact relative components"):
        resolve_managed_project_path(value, root=project)
    with pytest.raises(ValueError, match="exact relative components"):
        resolve_project_output_path(value, root=project)


def test_managed_project_path_still_accepts_portable_windows_separators(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    assert resolve_managed_project_path(
        r"data\sprite\mika.png",
        root=project,
    ) == project / "data/sprite/mika.png"


def test_managed_absolute_path_rejects_lexical_alias_text(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    raw = f"{project.as_posix()}/data/./file.txt"

    with pytest.raises(ValueError, match="lexical path aliases"):
        resolve_managed_project_path(raw, root=project)


def test_relative_project_path_cannot_escape_through_symlink(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    try:
        (project / "linked").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="escapes project root"):
        resolve_project_path("linked/file.txt", root=project)


def test_project_output_rejects_internal_symlink_alias_for_relative_and_absolute_paths(
    tmp_path,
):
    project = tmp_path / "project"
    storage = project / "storage"
    data = project / "data"
    storage.mkdir(parents=True)
    data.mkdir()
    alias = data / "cache"
    try:
        alias.symlink_to(storage, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_project_output_path("data/cache/result.bin", root=project)
    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_project_output_path(alias / "result.bin", root=project)


def test_managed_project_path_rejects_windows_reparse_point_metadata(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    junction = project / "data" / "cache"
    junction.mkdir(parents=True)
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path == junction:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x00000400,
                ),
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    with pytest.raises(PermissionError, match="reparse points"):
        resolve_managed_project_path("data/cache/result.bin", root=project)


def test_project_output_preserves_explicit_external_absolute_path_semantics(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external" / "result.bin"

    assert resolve_project_output_path(external, root=project) == external.resolve()

    external.parent.mkdir()
    target = external.parent / "target.bin"
    target.write_bytes(b"keep")
    try:
        external.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    assert resolve_project_output_path(external, root=project) == target.resolve()


def test_explicit_absolute_project_path_may_reference_external_storage(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external" / "asset.bin"
    project.mkdir()

    assert resolve_project_path(external, root=project) == external.resolve()


def test_project_read_path_keeps_exact_external_identity_without_following_links(
    tmp_path,
):
    project = tmp_path / "project"
    external = tmp_path / "external" / "asset.bin"
    project.mkdir()
    external.parent.mkdir()
    external.write_bytes(b"asset")

    assert resolve_project_read_path(external, root=project) == external

    alias = tmp_path / "asset-alias.bin"
    try:
        alias.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_project_read_path(alias, root=project)


def test_project_read_path_rejects_project_internal_link_component(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    try:
        (project / "data/alias").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_project_read_path("data/alias/asset.bin", root=project)


def test_runtime_asset_path_keeps_resource_project_and_external_roots_distinct(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    external = tmp_path / "external" / "sprite.png"
    resource = source / "assets" / "sprite.png"
    managed = project / "data" / "sprite" / "mio.png"
    resource.parent.mkdir(parents=True)
    managed.parent.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    resource.write_bytes(b"resource")
    managed.write_bytes(b"managed")
    external.write_bytes(b"external")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())

    assert resolve_runtime_asset_path("assets/sprite.png", root=project) == resource
    assert resolve_runtime_asset_path("data/sprite/mio.png", root=project) == managed
    assert resolve_runtime_asset_path(external.as_posix(), root=project) == external


def test_runtime_asset_paths_canonicalize_known_prefix_case_after_migration(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    resource = source / "assets/system/picture/Icon.png"
    resource.parent.mkdir(parents=True)
    project.mkdir()
    resource.write_bytes(b"resource")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())

    migrated = r"Assets\System\Picture\Icon.png"
    prefixes = (("assets", "system", "picture"),)

    assert (
        resolve_runtime_asset_path(
            migrated,
            root=project,
            resource_prefixes=prefixes,
        )
        == resource
    )
    assert (
        resolve_runtime_asset_read_path(
            migrated,
            root=project,
            resource_prefixes=prefixes,
        )
        == resource
    )


def test_runtime_asset_read_path_keeps_resource_project_and_external_roots_distinct(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    external = tmp_path / "external" / "sprite.png"
    resource = source / "assets" / "sprite.png"
    managed = project / "data" / "sprite" / "mio.png"
    resource.parent.mkdir(parents=True)
    managed.parent.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    resource.write_bytes(b"resource")
    managed.write_bytes(b"managed")
    external.write_bytes(b"external")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())

    assert (
        resolve_runtime_asset_read_path("assets/sprite.png", root=project)
        == resource
    )
    assert (
        resolve_runtime_asset_read_path("data/sprite/mio.png", root=project)
        == managed
    )
    assert resolve_runtime_asset_read_path(external, root=project) == external


@pytest.mark.parametrize("location", ("resource", "managed", "external"))
def test_runtime_asset_read_path_rejects_link_components(
    tmp_path,
    monkeypatch,
    location,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    external = tmp_path / "external"
    source.mkdir()
    project.mkdir()
    external.mkdir()
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())

    target = tmp_path / "target"
    target.mkdir()
    if location == "resource":
        alias = source / "assets"
        raw = "assets/sprite.png"
    elif location == "managed":
        (project / "data").mkdir()
        alias = project / "data" / "sprite"
        raw = "data/sprite/mio.png"
    else:
        alias = external / "sprite"
        raw = alias / "mio.png"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_runtime_asset_read_path(raw, root=project)


@pytest.mark.parametrize(
    "raw",
    (
        "./assets/sprite.png",
        "assets//sprite.png",
        "assets/./sprite.png",
        "data/sprite/../sprite.png",
    ),
)
def test_runtime_asset_path_rejects_lexical_aliases(tmp_path, raw):
    with pytest.raises((PermissionError, ValueError)):
        resolve_runtime_asset_path(raw, root=tmp_path)


def test_portable_project_path_rejects_internal_alias_and_keeps_external_alias_absolute(
    tmp_path,
):
    project = tmp_path / "project"
    managed = project / "data" / "sprite" / "mika.png"
    external = tmp_path / "external"
    managed.parent.mkdir(parents=True)
    external.mkdir()
    managed.write_bytes(b"png")
    internal_alias = project / "data" / "external-alias"
    external_alias = tmp_path / "managed-alias.png"
    try:
        internal_alias.symlink_to(external, target_is_directory=True)
        external_alias.symlink_to(managed)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        portable_project_path(internal_alias / "asset.png", root=project)
    assert portable_project_path(external_alias, root=project) == external_alias.as_posix()


@pytest.mark.parametrize("location", ("managed", "external"))
def test_portable_project_path_rejects_absolute_lexical_alias_text(
    tmp_path,
    location,
):
    project = tmp_path / "project"
    project.mkdir()
    base = project if location == "managed" else tmp_path / "external"
    raw = f"{base.as_posix()}/./asset.png"

    with pytest.raises(ValueError, match="lexical path aliases"):
        portable_project_path(raw, root=project)


@pytest.mark.parametrize(
    ("environment_name", "resolver"),
    [
        ("SHINSEKAI_SOURCE_ROOT", source_root),
        ("SHINSEKAI_APP_ROOT", app_root),
    ],
)
def test_runtime_code_roots_reject_relative_environment_values(
    tmp_path,
    monkeypatch,
    environment_name,
    resolver,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(environment_name, "relative-root")

    with pytest.raises(ValueError, match="absolute"):
        resolver()


@pytest.mark.parametrize(
    ("environment_name", "resolver"),
    [
        ("SHINSEKAI_SOURCE_ROOT", source_root),
        ("SHINSEKAI_APP_ROOT", app_root),
    ],
)
def test_runtime_code_roots_reject_present_but_empty_environment_values(
    monkeypatch,
    environment_name,
    resolver,
):
    monkeypatch.setenv(environment_name, "")

    with pytest.raises(ValueError, match="non-portable"):
        resolver()
