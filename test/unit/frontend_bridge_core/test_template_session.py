from __future__ import annotations

import json

import pytest

from frontend_bridge_core import template_session


def _paths(tmp_path):
    project = tmp_path / "project"
    templates = project / "data" / "character_templates"
    templates.mkdir(parents=True)
    return project, templates


def test_template_session_storage_ignores_process_cwd(tmp_path, monkeypatch):
    project, templates = _paths(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    template_session.save_template_session(
        templates,
        {"history_file": "data/chat_history/session"},
        project_root=project,
    )

    path = template_session.template_session_file(
        templates,
        project_root=project,
    )
    assert path == project / "data" / "config" / "template_tab_last_launch.json"
    assert not (unrelated / "data").exists()
    assert template_session.load_template_session(
        templates,
        project_root=project,
    )["history_file"] == "data/chat_history/session"


def test_template_session_stored_reference_is_authoritative(tmp_path):
    project, templates = _paths(tmp_path)
    path = template_session.template_session_file(
        templates,
        project_root=project,
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "history_file": "data/chat_history/must-not-be-used",
                "path_refs": {
                    "history_file": {
                        "scope": "project",
                        "path": "../outside",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = template_session.load_template_session(
        templates,
        project_root=project,
    )

    assert loaded is not None
    assert loaded["history_file"] == ""


def test_template_session_canonicalizes_known_stored_reference_prefixes(tmp_path):
    project, templates = _paths(tmp_path)
    path = template_session.template_session_file(
        templates,
        project_root=project,
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "path_refs": {
                    "history_file": {
                        "scope": "project",
                        "path": r"DATA\CHAT_HISTORY\Mio\Session.json",
                    },
                    "workflow_path": {
                        "scope": "resource",
                        "path": r"ASSETS\SYSTEM\WORKFLOW\Default.yaml",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = template_session.load_template_session(
        templates,
        project_root=project,
    )

    assert loaded is not None
    assert loaded["history_file"] == "data/chat_history/Mio/Session.json"
    assert loaded["workflow_path"] == "assets/system/workflow/Default.yaml"
    assert loaded["path_refs"] == {
        "history_file": {
            "scope": "project",
            "path": "data/chat_history/Mio/Session.json",
        },
        "workflow_path": {
            "scope": "resource",
            "path": "assets/system/workflow/Default.yaml",
        },
    }


def test_template_session_migrates_legacy_absolute_paths_once(tmp_path):
    project, templates = _paths(tmp_path)
    path = template_session.template_session_file(
        templates,
        project_root=project,
    )
    path.parent.mkdir(parents=True)
    stale = (
        tmp_path
        / "removed-project"
        / "data"
        / "chat_history"
        / "chapter.json"
    )
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "history_file": stale.as_posix(),
            }
        ),
        encoding="utf-8",
    )

    loaded = template_session.load_template_session(
        templates,
        project_root=project,
    )

    assert loaded is not None
    assert loaded["history_file"] == "data/chat_history/chapter.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["path_contract_version"] == 1
    assert persisted["path_refs"]["history_file"] == {
        "scope": "project",
        "path": "data/chat_history/chapter.json",
    }


def test_versioned_template_session_preserves_missing_external_identity(tmp_path):
    project, templates = _paths(tmp_path)
    path = template_session.template_session_file(
        templates,
        project_root=project,
    )
    path.parent.mkdir(parents=True)
    external = (
        tmp_path
        / "offline-drive"
        / "data"
        / "chat_history"
        / "chapter.json"
    )
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "path_contract_version": 1,
                "history_file": external.as_posix(),
            }
        ),
        encoding="utf-8",
    )

    loaded = template_session.load_template_session(
        templates,
        project_root=project,
    )

    assert loaded is not None
    assert loaded["history_file"] == external.as_posix()
    assert loaded["path_refs"]["history_file"] == {
        "scope": "external",
        "path": external.as_posix(),
    }


def test_template_session_rejects_linked_config_storage(tmp_path):
    project, templates = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    config = project / "data" / "config"
    try:
        config.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        template_session.save_template_session(
            templates,
            {"history_file": ""},
            project_root=project,
        )

    assert list(external.iterdir()) == []


def test_template_session_rejects_replaced_parent_before_write(
    tmp_path,
    monkeypatch,
):
    project, templates = _paths(tmp_path)
    config = project / "data" / "config"
    preserved = project / "data" / "config-preserved"
    config.mkdir()
    real_write = template_session.atomic_write_text

    def replace_parent(*args, **kwargs):
        config.rename(preserved)
        config.mkdir()
        (config / "template_tab_last_launch.json").write_text(
            "peer",
            encoding="utf-8",
        )
        return real_write(*args, **kwargs)

    monkeypatch.setattr(
        template_session,
        "atomic_write_text",
        replace_parent,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        template_session.save_template_session(
            templates,
            {"history_file": ""},
            project_root=project,
        )

    assert (config / "template_tab_last_launch.json").read_text(
        encoding="utf-8"
    ) == "peer"
    assert list(preserved.iterdir()) == []
