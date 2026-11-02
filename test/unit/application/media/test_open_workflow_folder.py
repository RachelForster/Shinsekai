from pathlib import Path

import pytest

from application.media import open_workflow_folder as workflows


def test_opens_bundled_workflows_from_the_active_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "installed app"
    folder = project_root / "ai" / "t2i" / "workflows"
    folder.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    opened = []

    def open_path(path):
        opened.append(path)
        return {"opened": path}

    monkeypatch.setattr(workflows, "open_local_path", open_path)
    assert workflows.open_t2i_workflow_folder(project_root) == {
        "path": folder.resolve().as_posix()
    }
    assert opened == [str(folder.resolve())]


def test_missing_workflow_folder_is_reported_without_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(
        workflows,
        "open_local_path",
        lambda *_: pytest.fail("must not open missing folder"),
    )
    with pytest.raises(FileNotFoundError, match="工作流文件夹不存在"):
        workflows.open_t2i_workflow_folder(tmp_path)


def test_file_manager_failure_is_reported_with_the_folder_path(tmp_path, monkeypatch):
    folder = tmp_path / "ai" / "t2i" / "workflows"
    folder.mkdir(parents=True)
    monkeypatch.setattr(
        workflows, "open_local_path", lambda *_: {"error": "no file manager"}
    )
    with pytest.raises(RuntimeError, match="no file manager") as failure:
        workflows.open_t2i_workflow_folder(tmp_path)
    assert str(folder.resolve()) in str(failure.value)
