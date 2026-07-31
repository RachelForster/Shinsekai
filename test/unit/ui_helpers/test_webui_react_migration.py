from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import webui_react


def _frontend_root(tmp_path: Path) -> Path:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    return frontend


def test_build_frontend_requests_migration_when_dependencies_are_missing(tmp_path: Path) -> None:
    frontend = _frontend_root(tmp_path)

    with pytest.raises(webui_react.FrontendMigrationNeeded, match="dependencies"):
        webui_react._build_frontend(tmp_path, frontend / "dist", "not found")


def test_build_frontend_requests_migration_when_pnpm_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from core import process_launch

    frontend = _frontend_root(tmp_path)
    (frontend / "node_modules").mkdir()

    def missing_pnpm(*_args, **_kwargs):
        raise FileNotFoundError("pnpm")

    monkeypatch.setattr(
        process_launch,
        "capture_command_executable",
        missing_pnpm,
    )

    with pytest.raises(webui_react.FrontendMigrationNeeded, match="pnpm"):
        webui_react._build_frontend(tmp_path, frontend / "dist", "not found")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_build_frontend_rejects_linked_dependency_root(
    tmp_path: Path,
) -> None:
    frontend = _frontend_root(tmp_path)
    external_modules = tmp_path / "external-modules"
    external_modules.mkdir()
    (frontend / "node_modules").symlink_to(
        external_modules,
        target_is_directory=True,
    )

    with pytest.raises(PermissionError, match="symbolic link"):
        webui_react._build_frontend(tmp_path, frontend / "dist", "not found")


def test_build_frontend_rejects_source_changed_during_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from core import process_launch

    frontend = _frontend_root(tmp_path)
    package = frontend / "package.json"
    package.write_text('{"name":"before"}', encoding="utf-8")
    (frontend / "node_modules").mkdir()

    def python_executable(*_args, **_kwargs):
        return process_launch.capture_launch_file(
            sys.executable,
            field="test Python executable",
            executable=True,
        )

    monkeypatch.setattr(
        process_launch,
        "capture_command_executable",
        python_executable,
    )

    def change_source_during_build(*_args, **_kwargs):
        package.write_text(
            '{"name":"replacement-is-longer"}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        webui_react.subprocess,
        "run",
        change_source_during_build,
    )

    with pytest.raises(
        webui_react.FrontendMigrationNeeded,
        match="changed while",
    ):
        webui_react._build_frontend(
            tmp_path,
            frontend / "dist",
            "not found",
        )


def test_main_opens_migration_dialog_for_missing_frontend_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _frontend_root(tmp_path)
    shown: list[str] = []

    monkeypatch.setattr(webui_react, "_default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(webui_react, "_show_frontend_migration_dialog", shown.append)
    monkeypatch.setattr(webui_react.sys, "argv", ["webui_react.py", "--no-open-browser"])

    with pytest.raises(SystemExit) as exc:
        webui_react.main()

    assert exc.value.code == 1
    assert shown
    assert "frontend dependencies are not installed" in shown[0]


def test_main_can_force_show_migration_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(webui_react, "_show_frontend_migration_dialog", shown.append)
    monkeypatch.setattr(
        webui_react,
        "run_frontend_bridge",
        lambda *args, **kwargs: pytest.fail("bridge should not start"),
    )
    monkeypatch.setattr(webui_react.sys, "argv", ["webui_react.py", "--show-migration-helper"])

    webui_react.main()

    assert shown == ["Opening the Shinsekai Frontend migration helper for testing."]
