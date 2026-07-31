from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from core.file_transactions import rename_path_without_overwrite
from core.sprite.chat_branch_storage import ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME
from application.chat.runtime_process import (
    _chat_history_path,
    _current_chat_history_download_file,
)
from application.chat.history_paths import (
    _import_slug,
    history_storage_exists,
    import_external_history,
    prepare_history_reference_for_launch,
    project_history_value,
    resolve_history_path_for_project,
    resolve_history_reference,
)
from application.chat.templates import _load_template_session_payload
from frontend_bridge_core.template_session import template_session_file


def _state(project_root):
    history_root = project_root / "data" / "chat_history"
    history_root.mkdir(parents=True)
    return SimpleNamespace(
        config_manager=SimpleNamespace(get_character_by_name=lambda _name: None),
        history_dir=history_root.as_posix(),
        project_root_dir=project_root.as_posix(),
    )


def test_live_relative_history_stays_inside_the_configured_collection(tmp_path):
    state = _state(tmp_path / "project")

    assert resolve_history_path_for_project(
        state,
        "session.json",
    ) == tmp_path / "project" / "data" / "chat_history" / "session.json"
    with pytest.raises(PermissionError, match="history directory"):
        resolve_history_path_for_project(state, "data/config/session.json")


def test_current_history_download_does_not_trim_stored_path_identity(tmp_path):
    state = _state(tmp_path / "project")
    history = tmp_path / "external" / "session.json"
    history.parent.mkdir()
    history.write_text("[]", encoding="utf-8")
    state.chat_session = {"historyPath": f" {history} "}

    with pytest.raises(ValueError, match="whitespace"):
        _current_chat_history_download_file(state)


def test_external_legacy_json_is_copied_into_managed_history(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "session.json"
    source.parent.mkdir()
    source.write_text('[{"role":"user","content":"hello"}]', encoding="utf-8")

    resolved = resolve_history_reference(state, source.as_posix())

    assert resolved != source
    assert resolved.is_dir()
    assert (resolved / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert project_history_value(state, resolved).startswith("data/chat_history/imported-session-")
    assert source.is_file()


def test_prepare_history_launch_reference_creates_the_exact_managed_session(tmp_path):
    state = _state(tmp_path / "project")

    prepared = prepare_history_reference_for_launch(
        state,
        "data/chat_history/new-session",
    )

    assert prepared == tmp_path / "project" / "data" / "chat_history" / "new-session"
    assert prepared.is_dir()


def test_prepare_history_launch_reference_rejects_alias_at_launch_boundary(
    tmp_path,
    monkeypatch,
):
    state = _state(tmp_path / "project")
    external = tmp_path / "external-session"
    external.mkdir()
    alias = tmp_path / "project" / "data" / "chat_history" / "late-alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    monkeypatch.setattr(
        "application.chat.history_paths.resolve_history_reference",
        lambda _state, _raw: alias,
    )

    with pytest.raises(PermissionError, match="symbolic link"):
        prepare_history_reference_for_launch(state, "ignored")


def test_external_import_never_overwrites_an_unowned_name_collision(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "session.json"
    source.parent.mkdir()
    source.write_text('[{"role":"user","content":"external"}]', encoding="utf-8")
    collision = tmp_path / "project" / "data" / "chat_history" / _import_slug(source)
    collision.mkdir()
    (collision / ACTIVE_HISTORY_FILENAME).write_text(
        '[{"role":"user","content":"owned-by-user"}]',
        encoding="utf-8",
    )

    resolved = resolve_history_reference(state, source.as_posix())

    assert resolved != collision
    assert resolved.name == f"{collision.name}-1"
    assert "owned-by-user" in (collision / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8")
    assert "external" in (resolved / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8")


def test_reimporting_the_same_external_source_reuses_its_owned_snapshot(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "session.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")

    first = resolve_history_reference(state, source.as_posix())
    second = resolve_history_reference(state, source.as_posix())

    assert second == first
    assert list((tmp_path / "project" / "data" / "chat_history").glob("imported-session-*")) == [first]


def test_external_import_retries_a_cross_process_publication_collision(tmp_path, monkeypatch):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "session.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")
    real_rename = rename_path_without_overwrite
    raced = False

    def publish_peer_then_fail(staged, destination, *, expected_identity=None):
        nonlocal raced
        if not raced:
            raced = True
            destination.mkdir()
            (destination / ACTIVE_HISTORY_FILENAME).write_text(
                '[{"content":"peer"}]',
                encoding="utf-8",
            )
            raise FileExistsError(destination)
        return real_rename(
            staged,
            destination,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "application.chat.history_paths.rename_path_without_overwrite",
        publish_peer_then_fail,
    )

    resolved = resolve_history_reference(state, source.as_posix())

    collision = tmp_path / "project" / "data" / "chat_history" / _import_slug(source)
    assert resolved.name == f"{collision.name}-1"
    assert "peer" in (collision / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8")
    assert (resolved / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8") == "[]"


def test_external_import_rejects_source_replaced_after_identity_capture(
    tmp_path,
    monkeypatch,
):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "session.json"
    preserved = tmp_path / "external-drive" / "session-preserved.json"
    source.parent.mkdir()
    source.write_text("original", encoding="utf-8")
    from application.chat import history_paths

    real_copy = history_paths.copy_file_exclusive
    replaced = False

    def replace_before_copy(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            source.rename(preserved)
            source.write_text("peer", encoding="utf-8")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(
        history_paths,
        "copy_file_exclusive",
        replace_before_copy,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        import_external_history(state, source)

    assert source.read_text(encoding="utf-8") == "peer"
    assert preserved.read_text(encoding="utf-8") == "original"
    assert list((tmp_path / "project/data/chat_history").iterdir()) == []


def test_external_branch_directory_is_copied_as_one_session(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "chapter"
    source.mkdir(parents=True)
    (source / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
    (source / BRANCH_TREE_FILENAME).write_text('{"branches":{}}', encoding="utf-8")

    resolved = resolve_history_reference(state, (source / ACTIVE_HISTORY_FILENAME).as_posix())

    assert resolved.is_dir()
    assert history_storage_exists(resolved)
    assert (resolved / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8") == "[]"


def test_external_branch_directory_with_symlink_is_rejected(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive" / "chapter"
    source.mkdir(parents=True)
    (source / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
    external = tmp_path / "private.json"
    external.write_text('[{"secret":true}]', encoding="utf-8")
    link = source / "linked.json"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="符号链接"):
        resolve_history_reference(state, source.as_posix())

    assert external.read_text(encoding="utf-8") == '[{"secret":true}]'


def test_managed_session_with_symlinked_active_file_is_rejected(tmp_path):
    state = _state(tmp_path / "project")
    session = tmp_path / "project" / "data" / "chat_history" / "session"
    session.mkdir()
    external = tmp_path / "external.json"
    external.write_text("[]", encoding="utf-8")
    try:
        (session / ACTIVE_HISTORY_FILENAME).symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_history_reference(state, "data/chat_history/session")

    assert history_storage_exists(session) is False


def test_managed_session_directory_alias_cannot_redirect_to_another_session(tmp_path):
    state = _state(tmp_path / "project")
    history_root = tmp_path / "project" / "data" / "chat_history"
    real_session = history_root / "real-session"
    real_session.mkdir()
    (real_session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
    try:
        (history_root / "alias-session").symlink_to(real_session, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_history_reference(state, "data/chat_history/alias-session")

    assert (real_session / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8") == "[]"


def test_absolute_managed_history_alias_cannot_be_treated_as_external_import(tmp_path):
    state = _state(tmp_path / "project")
    history_root = tmp_path / "project" / "data" / "chat_history"
    external = tmp_path / "external-session"
    external.mkdir()
    (external / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
    alias = history_root / "linked-external"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_history_reference(state, alias.as_posix())

    assert list(history_root.glob("imported-*")) == []


def test_missing_history_from_old_project_root_is_not_guessed_at_runtime(tmp_path):
    project_root = tmp_path / "current"
    state = _state(project_root)
    stale = tmp_path / "removed-old-root" / "data" / "chat_history" / "chapter.json"

    with pytest.raises(FileNotFoundError, match="外部聊天历史不存在"):
        resolve_history_reference(state, stale.as_posix())


def test_explicit_legacy_history_migration_can_rebase_old_project_root(tmp_path):
    project_root = tmp_path / "current"
    state = _state(project_root)
    stale = tmp_path / "removed-old-root" / "data" / "chat_history" / "chapter.json"

    resolved = resolve_history_reference(
        state,
        stale.as_posix(),
        recover_legacy_absolute=True,
    )

    assert resolved == project_root / "data" / "chat_history" / "chapter"


def test_missing_unrelated_external_history_has_controlled_error(tmp_path):
    state = _state(tmp_path / "project")
    missing = tmp_path / "external-drive" / "missing.json"

    with pytest.raises(FileNotFoundError, match="外部聊天历史不存在"):
        resolve_history_reference(state, missing.as_posix())


def test_resolution_uses_state_root_even_if_cwd_changes(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    state = _state(project_root)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    resolved = resolve_history_reference(state, "data/chat_history/session.json")

    assert resolved == project_root / "data" / "chat_history" / "session"


@pytest.mark.parametrize("raw", [" session.json", "session.json "])
def test_history_reference_rejects_surrounding_whitespace(tmp_path, raw):
    state = _state(tmp_path / "project")

    with pytest.raises(ValueError, match="surrounding whitespace"):
        resolve_history_reference(state, raw)


def test_external_history_reference_rejects_absolute_lexical_alias(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive/session.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")
    alias = f"{source.parent.as_posix()}/./{source.name}"

    with pytest.raises(ValueError, match="lexical path aliases"):
        resolve_history_reference(state, alias)

    assert list((tmp_path / "project/data/chat_history").iterdir()) == []


def test_external_history_import_boundary_rejects_alias_before_copy(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive/session.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")
    alias = f"{source.parent.as_posix()}/./{source.name}"

    with pytest.raises(ValueError, match="lexical path aliases"):
        import_external_history(state, alias)

    assert list((tmp_path / "project/data/chat_history").iterdir()) == []


def test_external_history_import_boundary_rejects_relative_source(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    state = _state(project_root)
    source = project_root / "session.json"
    source.write_text("[]", encoding="utf-8")
    monkeypatch.chdir(project_root)

    with pytest.raises(ValueError, match="must be absolute"):
        import_external_history(state, "session.json")

    assert list((project_root / "data/chat_history").iterdir()) == []


def test_external_history_import_does_not_expand_user_home_alias(tmp_path):
    state = _state(tmp_path / "project")

    with pytest.raises(ValueError, match="must be absolute"):
        import_external_history(state, "~/session.json")

    assert list((tmp_path / "project/data/chat_history").iterdir()) == []


def test_external_history_symbolic_link_is_rejected_before_resolution(tmp_path):
    state = _state(tmp_path / "project")
    source = tmp_path / "external-drive/session.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")
    alias = tmp_path / "external-drive/session-alias.json"
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        resolve_history_reference(state, alias.as_posix())
    with pytest.raises(PermissionError, match="symbolic links"):
        import_external_history(state, alias)

    assert list((tmp_path / "project/data/chat_history").iterdir()) == []


def test_existing_relative_basename_is_imported_instead_of_silently_ignored(tmp_path):
    project_root = tmp_path / "project"
    state = _state(project_root)
    source = project_root / "session.json"
    source.write_text('[{"content":"relative source"}]', encoding="utf-8")

    resolved = resolve_history_reference(state, "session.json")

    assert resolved.is_dir()
    assert "relative source" in (resolved / ACTIVE_HISTORY_FILENAME).read_text(encoding="utf-8")
    assert source.is_file()


@pytest.mark.parametrize(
    "history_value",
    [
        "data/chat_history",
        "data/chat_history/active.json",
        "data/chat_history/branches.json",
        "data/chat_history/session/..",
        "active.json",
    ],
)
def test_history_collection_root_can_never_be_resolved_as_a_session(tmp_path, history_value):
    state = _state(tmp_path / "project")

    with pytest.raises(PermissionError, match="history root"):
        resolve_history_reference(state, history_value)


def test_project_history_value_rejects_project_files_outside_history_storage(tmp_path):
    project_root = tmp_path / "project"
    state = _state(project_root)

    with pytest.raises(PermissionError, match="history directory"):
        project_history_value(state, project_root / "config.json")


def test_history_directory_cannot_be_configured_as_the_project_root(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    state = SimpleNamespace(
        history_dir=project_root.as_posix(),
        project_root_dir=project_root.as_posix(),
    )

    with pytest.raises(PermissionError, match="outside project root"):
        resolve_history_reference(state, "session.json")


def test_pyqt_v1_snapshot_reaches_react_chat_after_cross_drive_root_move(tmp_path):
    project_root = tmp_path / "react-project"
    state = _state(project_root)
    template_dir = project_root / "data" / "character_templates"
    template_dir.mkdir(parents=True)
    state.template_dir_path = template_dir.as_posix()
    session_file = template_session_file(
        template_dir.as_posix(),
        project_root=project_root,
    )
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        json.dumps(
            {
                "version": 1,
                "history_file": r"D:\legacy-pyqt\data\chat_history\chapter.json",
                "scenario_text": "migrated scene",
                "system_template_text": "system",
            }
        ),
        encoding="utf-8",
    )

    frontend_session = _load_template_session_payload(state)
    resolved = _chat_history_path(
        state,
        {"historyPath": frontend_session["historyPath"]},
        frontend_session,
    )

    assert frontend_session["historyPath"] == "data/chat_history/chapter.json"
    assert resolved == project_root / "data" / "chat_history" / "chapter"
