import os
import time

import pytest

from webui_react import (
    FrontendMigrationNeeded,
    _ensure_frontend_dist,
    _resolve_frontend_dist,
    _resolve_project_root,
)


def test_existing_stale_dist_is_served_when_build_environment_is_missing(tmp_path, capsys):
    frontend_dir = tmp_path / "frontend"
    source_path = frontend_dir / "src" / "main.tsx"
    index_path = frontend_dir / "dist" / "index.html"
    source_path.parent.mkdir(parents=True)
    index_path.parent.mkdir(parents=True)
    source_path.write_text("source", encoding="utf-8")
    index_path.write_text("built", encoding="utf-8")
    now = time.time()
    os.utime(index_path, (now - 120, now - 120))
    os.utime(source_path, (now, now))

    _ensure_frontend_dist(
        tmp_path,
        frontend_dir / "dist",
        build_if_missing=True,
        build_if_stale=True,
    )

    assert "Serving the existing built frontend" in capsys.readouterr().err


def test_missing_dist_requests_migration_when_build_environment_is_missing(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()

    with pytest.raises(FrontendMigrationNeeded, match="frontend dependencies are not installed"):
        _ensure_frontend_dist(
            tmp_path,
            frontend_dir / "dist",
            build_if_missing=True,
            build_if_stale=True,
        )


def test_relative_frontend_dist_cannot_escape_repository_root(tmp_path):
    with pytest.raises(ValueError, match="escapes repository root"):
        _resolve_frontend_dist(tmp_path / "repo", "../outside")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_frontend_dist_cannot_be_a_linked_directory(tmp_path):
    repo_root = tmp_path / "repo"
    external_dist = tmp_path / "external-dist"
    (repo_root / "frontend").mkdir(parents=True)
    external_dist.mkdir()
    (repo_root / "frontend" / "dist").symlink_to(
        external_dist,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="linked component"):
        _resolve_frontend_dist(repo_root, "frontend/dist")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_frontend_dist_cannot_use_a_linked_index(tmp_path):
    frontend_dir = tmp_path / "frontend"
    dist = frontend_dir / "dist"
    external_index = tmp_path / "external-index.html"
    dist.mkdir(parents=True)
    external_index.write_text("external", encoding="utf-8")
    (dist / "index.html").symlink_to(external_index)

    with pytest.raises(PermissionError, match="symbolic link"):
        _ensure_frontend_dist(
            tmp_path,
            dist,
            build_if_missing=True,
            build_if_stale=True,
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_frontend_build_cannot_use_a_linked_source_file(tmp_path):
    frontend_dir = tmp_path / "frontend"
    dist = frontend_dir / "dist"
    external_package = tmp_path / "package.json"
    dist.mkdir(parents=True)
    external_package.write_text('{"scripts":{"build":"true"}}', encoding="utf-8")
    (frontend_dir / "package.json").symlink_to(external_package)
    (dist / "index.html").write_text("built", encoding="utf-8")

    with pytest.raises(PermissionError, match="symbolic link"):
        _ensure_frontend_dist(
            tmp_path,
            dist,
            build_if_missing=True,
            build_if_stale=True,
        )


def test_explicit_project_root_must_be_absolute(tmp_path, monkeypatch):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    with pytest.raises(ValueError, match="--project-root must be an absolute path"):
        _resolve_project_root(tmp_path / "repo", "relative-project")

    selected = tmp_path / "selected"
    assert _resolve_project_root(tmp_path / "repo", str(selected)) == selected.resolve()


def test_project_root_distinguishes_absent_from_explicit_empty(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("EASYAI_PROJECT_ROOT", raising=False)

    assert _resolve_project_root(repo_root, None) == repo_root.resolve()
    with pytest.raises(ValueError, match="--project-root must not be empty"):
        _resolve_project_root(repo_root, "")


def test_project_root_uses_current_environment_before_legacy(tmp_path, monkeypatch):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(current))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(legacy))

    assert _resolve_project_root(tmp_path / "repo", None) == current.resolve()

    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT")
    assert _resolve_project_root(tmp_path / "repo", None) == legacy.resolve()


def test_project_root_rejects_present_empty_environment_without_legacy_fallback(
    tmp_path,
    monkeypatch,
):
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", "")
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(legacy))

    with pytest.raises(ValueError, match="SHINSEKAI_PROJECT_ROOT must not be empty"):
        _resolve_project_root(tmp_path / "repo", None)
