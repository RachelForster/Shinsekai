import ntpath
import os
from types import SimpleNamespace

import pytest

from frontend_bridge_core.path_utils import (
    common_path_is_within,
    make_path_reference,
    normalize_project_relative_path,
    path_reference_value,
    relative_path_if_within,
    resolve_from_root,
    strip_windows_verbatim_prefix,
    state_project_root,
)


def test_strip_drops_long_path_prefix():
    assert strip_windows_verbatim_prefix("\\\\?\\D:\\tts_bundles\\gpt") == "D:\\tts_bundles\\gpt"
    assert strip_windows_verbatim_prefix("//?/D:/tts_bundles/gpt") == "D:/tts_bundles/gpt"


def test_strip_keeps_unc_root():
    assert strip_windows_verbatim_prefix(r"\\?\UNC\server\share\tts") == r"\\server\share\tts"
    assert strip_windows_verbatim_prefix("//?/UNC/server/share/tts") == "//server/share/tts"


def test_strip_leaves_plain_path_untouched():
    assert strip_windows_verbatim_prefix("D:/tts_bundles/gpt") == "D:/tts_bundles/gpt"


def test_strip_preserves_device_and_non_filesystem_namespaces():
    assert strip_windows_verbatim_prefix(r"\\.\C:\device") == r"\\.\C:\device"
    assert (
        strip_windows_verbatim_prefix(r"\\?\GLOBALROOT\Device\HarddiskVolume1")
        == r"\\?\GLOBALROOT\Device\HarddiskVolume1"
    )


def test_path_reference_rejects_windows_device_namespace(tmp_path):
    with pytest.raises(ValueError, match="device namespace"):
        make_path_reference(r"\\.\C:\device", tmp_path)
    with pytest.raises(ValueError, match="device namespace"):
        make_path_reference(r"\??\C:\native-device", tmp_path)
    with pytest.raises(ValueError, match="unsupported Windows verbatim namespace"):
        make_path_reference(r"\\?\GLOBALROOT\Device\HarddiskVolume1", tmp_path)


def test_windows_cross_drive_containment_is_false_instead_of_raising():
    assert common_path_is_within("C:/Shinsekai", "C:/Shinsekai/data/chat.json", path_module=ntpath)
    assert not common_path_is_within("C:/Shinsekai", "D:/history/chat.json", path_module=ntpath)


def test_windows_unc_containment_respects_share_boundaries():
    assert common_path_is_within(
        r"\\server\share\Shinsekai",
        r"\\server\share\Shinsekai\data\chat.json",
        path_module=ntpath,
    )
    assert not common_path_is_within(
        r"\\server\share\Shinsekai",
        r"\\server\other\chat.json",
        path_module=ntpath,
    )


def test_windows_verbatim_prefix_is_ignored_for_identity_comparison():
    assert common_path_is_within(
        r"D:\Shinsekai",
        r"\\?\D:\Shinsekai\data\chat_history\session.json",
        path_module=ntpath,
    )
    assert common_path_is_within(
        r"\\server\share\Shinsekai",
        r"\\?\UNC\server\share\Shinsekai\data\session.json",
        path_module=ntpath,
    )


def test_windows_verbatim_path_can_be_serialized_relative_to_plain_root():
    assert relative_path_if_within(
        r"D:\Shinsekai",
        r"\\?\D:\Shinsekai\data\chat_history\session.json",
        path_module=ntpath,
    ) == "data/chat_history/session.json"
    assert relative_path_if_within(
        r"C:\Shinsekai",
        r"D:\history\session.json",
        path_module=ntpath,
    ) is None


def test_path_reference_recovers_stale_windows_project_history(tmp_path):
    reference = make_path_reference(
        r"D:\old-install\DATA\CHAT_HISTORY\session.json",
        tmp_path,
        legacy_project_prefixes=(("data", "chat_history"),),
    )

    assert reference == {"scope": "project", "path": "data/chat_history/session.json"}


def test_path_reference_can_preserve_missing_external_path_after_migration(tmp_path):
    reference = make_path_reference(
        r"D:\offline-disk\data\chat_history\session.json",
        tmp_path,
        legacy_project_prefixes=(("data", "chat_history"),),
        recover_legacy_absolute=False,
    )

    assert reference == {
        "scope": "external",
        "path": "D:/offline-disk/data/chat_history/session.json",
    }


def test_path_reference_keeps_application_resources_out_of_project_scope(tmp_path):
    reference = make_path_reference(
        r"ASSETS\SYSTEM\WORKFLOW\default.yaml",
        tmp_path,
        resource_prefixes=(("assets", "system", "workflow"),),
    )

    assert reference == {
        "scope": "resource",
        "path": "assets/system/workflow/default.yaml",
    }
    assert path_reference_value(reference) == "assets/system/workflow/default.yaml"


def test_path_reference_does_not_collapse_distinct_same_named_application_resources(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    source = tmp_path / "source"
    app = tmp_path / "application"
    relative = "assets/system/workflow/default.yaml"
    source_asset = source / relative
    app_asset = app / relative
    project.mkdir()
    source_asset.parent.mkdir(parents=True)
    app_asset.parent.mkdir(parents=True)
    source_asset.write_text("source", encoding="utf-8")
    app_asset.write_text("application", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", app.as_posix())

    assert make_path_reference(
        source_asset,
        project,
        resource_prefixes=(("assets", "system", "workflow"),),
    ) == {"scope": "resource", "path": relative}
    assert make_path_reference(
        app_asset,
        project,
        resource_prefixes=(("assets", "system", "workflow"),),
    ) == {"scope": "external", "path": app_asset.as_posix()}


def test_path_reference_recovers_stale_install_resource_without_reclassifying_it(
    tmp_path,
):
    reference = make_path_reference(
        r"D:\old-install\ASSETS\SYSTEM\WORKFLOW\default.yaml",
        tmp_path,
        resource_prefixes=(("assets", "system", "workflow"),),
    )

    assert reference == {
        "scope": "resource",
        "path": "assets/system/workflow/default.yaml",
    }


def test_existing_external_resource_suffix_keeps_external_scope(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external/assets/system/workflow/default.yaml"
    project.mkdir()
    external.parent.mkdir(parents=True)
    external.write_text("nodes: []\n", encoding="utf-8")

    reference = make_path_reference(
        external,
        project,
        resource_prefixes=(("assets", "system", "workflow"),),
    )

    assert reference == {"scope": "external", "path": external.as_posix()}


def test_existing_external_legacy_suffix_is_never_reclassified(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external/data/chat_history/session.json"
    current = project / "data/chat_history/session.json"
    external.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    external.write_text("external", encoding="utf-8")
    current.write_text("managed", encoding="utf-8")

    reference = make_path_reference(
        external,
        project,
        legacy_project_prefixes=(("data", "chat_history"),),
    )

    assert reference == {"scope": "external", "path": external.as_posix()}


def test_absolute_project_path_is_serialized_relative_without_following_aliases(tmp_path):
    project = tmp_path / "project"
    managed = project / "data" / "sprite" / "mio.png"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"png")

    assert make_path_reference(managed, project) == {
        "scope": "project",
        "path": "data/sprite/mio.png",
    }


def test_internal_absolute_alias_escape_is_rejected(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    try:
        (project / "data" / "alias").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        make_path_reference(project / "data" / "alias" / "asset.png", project)


def test_external_alias_back_into_project_keeps_external_scope(tmp_path):
    project = tmp_path / "project"
    managed = project / "data" / "sprite" / "mio.png"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"png")
    alias = tmp_path / "external-alias.png"
    try:
        alias.symlink_to(managed)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    assert make_path_reference(alias, project) == {
        "scope": "external",
        "path": alias.as_posix(),
    }


def test_project_relative_normalization_preserves_dotfiles():
    assert normalize_project_relative_path("data/.history/session.json") == "data/.history/session.json"


def test_project_relative_normalization_rejects_windows_drive_relative_paths():
    assert normalize_project_relative_path("D:session.json") is None


def test_project_relative_normalization_rejects_user_home_expansion():
    assert normalize_project_relative_path("~/outside.txt") is None
    assert normalize_project_relative_path("~root/outside.txt") is None


@pytest.mark.parametrize("raw", [" data/history.json", "data/history.json "])
def test_project_relative_normalization_rejects_surrounding_whitespace(raw):
    assert normalize_project_relative_path(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "data/./history.json",
        "data/cache/../history.json",
        "data//history.json",
        "data/history.json/",
        "./data/history.json",
        ".",
    ],
)
def test_project_relative_normalization_rejects_lexical_aliases(raw):
    assert normalize_project_relative_path(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "data/CON/history.json",
        "data/NUL.txt",
        "data/history.",
        "data/history ",
        "data/alternate:stream",
        "data/question?.json",
        "data/lone-\ud800.json",
    ],
)
def test_project_relative_normalization_rejects_nonportable_components(raw):
    assert normalize_project_relative_path(raw) is None


def test_project_relative_normalization_only_portabilizes_windows_separators():
    assert normalize_project_relative_path(r"data\.history\session.json") == (
        "data/.history/session.json"
    )


def test_path_reference_rejects_lexical_alias_instead_of_retargeting(tmp_path):
    with pytest.raises(ValueError, match="project path"):
        make_path_reference("data/cache/../history.json", tmp_path)

    assert path_reference_value(
        {"scope": "project", "path": "data/cache/../history.json"}
    ) is None


def test_path_reference_rejects_surrounding_whitespace(tmp_path):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        make_path_reference(" data/history.json", tmp_path)


def test_path_reference_rejects_absolute_lexical_alias(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    raw = f"{project.as_posix()}/data/./history.json"

    with pytest.raises(ValueError, match="lexical path aliases"):
        make_path_reference(raw, project)

    assert path_reference_value(
        {"scope": "external", "path": raw}
    ) is None


def test_home_path_reference_is_external_instead_of_project_relative(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", home.as_posix())

    reference = make_path_reference("~/outside.txt", project)

    assert reference == {
        "scope": "external",
        "path": (home / "outside.txt").as_posix(),
    }


def test_non_native_windows_absolute_path_is_never_anchored_to_project(tmp_path):
    if os.name == "nt":
        pytest.skip("Windows drive syntax is native on this host")

    with pytest.raises(ValueError, match="non-native absolute"):
        resolve_from_root(r"D:\external\asset.png", tmp_path)


def test_resolve_from_root_rejects_relative_traversal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(PermissionError, match="escapes project root"):
        resolve_from_root("../external/asset.png", project)


def test_resolve_from_root_normalizes_portable_backslash_separators(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    assert resolve_from_root(r"data\sprite\mika.png", project) == (
        project / "data/sprite/mika.png"
    )


@pytest.mark.parametrize(
    "raw",
    ["", "   ", " leading.txt", "trailing.txt ", "D:relative.txt", "bad\x00name"],
)
def test_resolve_from_root_rejects_ambiguous_or_empty_paths(tmp_path, raw):
    with pytest.raises(ValueError):
        resolve_from_root(raw, tmp_path)


def test_resolve_from_root_allows_explicit_absolute_external_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external" / "asset.png"

    assert resolve_from_root(external, project) == external.resolve()


def test_invalid_authoritative_state_root_never_falls_back_to_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())
    state = SimpleNamespace(project_root_dir="invalid\x00root")

    with pytest.raises(ValueError, match="state.project_root_dir"):
        state_project_root(state)


def test_relative_authoritative_state_root_never_depends_on_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = SimpleNamespace(project_root_dir="relative-project")

    with pytest.raises(ValueError, match="state.project_root_dir"):
        state_project_root(state)


def test_empty_authoritative_state_root_never_falls_back_to_environment(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())
    state = SimpleNamespace(project_root_dir="")

    with pytest.raises(ValueError, match="state.project_root_dir"):
        state_project_root(state)


def test_empty_current_environment_root_never_falls_back_to_legacy(
    tmp_path,
    monkeypatch,
):
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", legacy.as_posix())
    state = SimpleNamespace()

    with pytest.raises(ValueError, match="SHINSEKAI_PROJECT_ROOT"):
        state_project_root(state)
