from __future__ import annotations

import json

from ui.chat_ui import theme_chrome


def test_chat_theme_paths_follow_runtime_project_root(tmp_path, monkeypatch):
    app_root = tmp_path / "Program Files" / "Shinsekai App"
    project_root = tmp_path / "D drive data" / "用户 データ"
    app_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", str(app_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))

    assert theme_chrome.project_root() == project_root.resolve()
    assert theme_chrome.resolve_theme_path("") == (
        project_root / "data" / "chat_ui_theme.json"
    )
    assert theme_chrome.resolve_theme_path("themes/Custom 主题.json") == (
        project_root / "themes" / "Custom 主题.json"
    )


def test_chat_theme_loader_reads_relative_unicode_path_from_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "Project Data 项目"
    relative_path = "themes/自定义 theme.json"
    theme_path = project_root / relative_path
    theme_path.parent.mkdir(parents=True)
    theme_path.write_text(
        json.dumps({"send_button": {"extra_qss": "color: #123456"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    theme_chrome.clear_chat_chrome_theme_cache()

    loaded = theme_chrome.get_chat_chrome_theme(relative_path)

    assert loaded.send_button_extra == "color: #123456"
