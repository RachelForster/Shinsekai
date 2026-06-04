from __future__ import annotations

from pathlib import Path

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
    frontend = _frontend_root(tmp_path)
    (frontend / "node_modules").mkdir()
    monkeypatch.setattr(webui_react.shutil, "which", lambda name: None)

    with pytest.raises(webui_react.FrontendMigrationNeeded, match="pnpm"):
        webui_react._build_frontend(tmp_path, frontend / "dist", "not found")


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
