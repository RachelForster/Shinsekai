from __future__ import annotations

from core.paths import project_root


def test_project_root_prefers_shinsekai_override_to_legacy_easyai(tmp_path, monkeypatch):
    shinsekai_root = tmp_path / "D drive" / "项目 データ"
    easyai_root = tmp_path / "legacy root"
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(shinsekai_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert project_root() == shinsekai_root.resolve()


def test_project_root_keeps_legacy_easyai_and_cwd_fallbacks(tmp_path, monkeypatch):
    easyai_root = tmp_path / "legacy root"
    cwd_root = tmp_path / "current working root"
    cwd_root.mkdir()
    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert project_root() == easyai_root.resolve()

    monkeypatch.delenv("EASYAI_PROJECT_ROOT")
    monkeypatch.chdir(cwd_root)
    assert project_root() == cwd_root.resolve()
