from __future__ import annotations

import base64
import stat
import sys
from pathlib import Path

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter, _output_path


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, list[str]]:
        return {"images": [base64.b64encode(b"png").decode("ascii")]}


def test_default_t2i_output_uses_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", lambda *_args, **_kwargs: _Response())

    output = StableDiffusionAdapter().generate_image("landscape")

    assert output == (project / "data/generated/temp_t2i_sd.png").as_posix()
    assert (project / "data/generated/temp_t2i_sd.png").read_bytes() == b"png"
    assert not (unrelated / "temp_t2i_sd.png").exists()


def test_relative_t2i_output_is_anchored_to_project_root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", lambda *_args, **_kwargs: _Response())

    output = StableDiffusionAdapter().generate_image("landscape", "output/image.png")

    assert output == (project / "output/image.png").as_posix()
    assert (project / "output/image.png").is_file()
    assert not (unrelated / "output").exists()


def test_explicit_empty_t2i_output_does_not_select_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", tmp_path.as_posix())

    with pytest.raises(ValueError, match="path is empty"):
        _output_path("", "data/generated/default.png")

    assert not (tmp_path / "data/generated/default.png").exists()


def test_relative_comfyui_inputs_use_project_root_after_cwd_changes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    workflow = project / "data/workflows/default.json"
    work_dir = project / "tools/ComfyUI"
    workflow.parent.mkdir(parents=True)
    work_dir.mkdir(parents=True)
    unrelated.mkdir()
    workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)

    adapter = ComfyUIT2IAdapter(
        work_path="tools/ComfyUI",
        workflow_path="data/workflows/default.json",
    )

    assert adapter.work_path == work_dir.as_posix()
    assert adapter.workflow_path == workflow.as_posix()
    assert adapter.workflow_template == {}


def test_builtin_comfyui_workflow_uses_application_resource_not_project_shadow(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    project = tmp_path / "project"
    source_workflow = source / "assets/system/workflow/comfy.json"
    project_workflow = project / "assets/system/workflow/comfy.json"
    source_workflow.parent.mkdir(parents=True)
    project_workflow.parent.mkdir(parents=True)
    source_workflow.write_text('{"owner": "resource"}', encoding="utf-8")
    project_workflow.write_text('{"owner": "project"}', encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)

    adapter = ComfyUIT2IAdapter(
        workflow_path="assets/system/workflow/comfy.json",
    )

    assert adapter.workflow_path == source_workflow.as_posix()
    assert adapter.workflow_template == {"owner": "resource"}


@pytest.mark.parametrize("linked_field", ("workflow_path", "work_path"))
def test_comfyui_rejects_linked_local_inputs_before_startup(
    tmp_path,
    monkeypatch,
    linked_field,
):
    project = tmp_path / "project"
    external = tmp_path / "external"
    workflow = project / "data/workflows/default.json"
    work_dir = project / "tools/ComfyUI"
    workflow.parent.mkdir(parents=True)
    work_dir.parent.mkdir(parents=True)
    external.mkdir()
    workflow.write_text("{}", encoding="utf-8")
    work_dir.mkdir()
    if linked_field == "workflow_path":
        linked_target = external / "workflow.json"
        linked_target.write_text("{}", encoding="utf-8")
        alias = project / "data/workflows/linked.json"
        kwargs = {
            "workflow_path": "data/workflows/linked.json",
            "work_path": "tools/ComfyUI",
        }
    else:
        linked_target = external / "ComfyUI"
        linked_target.mkdir()
        alias = project / "tools/LinkedComfyUI"
        kwargs = {
            "workflow_path": "data/workflows/default.json",
            "work_path": "tools/LinkedComfyUI",
        }
    try:
        alias.symlink_to(
            linked_target,
            target_is_directory=linked_target.is_dir(),
        )
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)

    with pytest.raises(PermissionError, match="symbolic link"):
        ComfyUIT2IAdapter(**kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_path", " data/workflows/default.json"),
        ("work_path", "tools/ComfyUI "),
    ],
)
def test_comfyui_rejects_paths_with_ambiguous_outer_whitespace(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    project = tmp_path / "project"
    project.mkdir()
    workflow = project / "data/workflows/default.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)
    kwargs = {
        "workflow_path": "data/workflows/default.json",
        "work_path": "",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match="surrounding whitespace"):
        ComfyUIT2IAdapter(**kwargs)


def test_comfyui_workflow_switch_is_resolved_and_transactional(tmp_path, monkeypatch):
    project = tmp_path / "project"
    first = project / "data/workflows/first.json"
    second = project / "data/workflows/second.json"
    first.parent.mkdir(parents=True)
    first.write_text('{"workflow": 1}', encoding="utf-8")
    second.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda self: None)
    adapter = ComfyUIT2IAdapter(workflow_path="data/workflows/first.json")

    adapter.switch_model({"workflow_path": "data/workflows/second.json"})

    assert adapter.workflow_path == first.as_posix()
    assert adapter.workflow_template == {"workflow": 1}


def test_comfyui_clone_startup_uses_native_python_and_explicit_working_directory(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    workflow = project / "data/workflows/default.json"
    work_dir = project / "tools/ComfyUI"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    work_dir.mkdir(parents=True)
    main_script = work_dir / "main.py"
    main_script.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setenv("PYTHONHOME", "/stale/python")
    monkeypatch.setenv("PYTHONPATH", "/stale/project")
    monkeypatch.setattr(ComfyUIT2IAdapter, "_is_server_ready", lambda self: False)
    monkeypatch.setattr(ComfyUIT2IAdapter, "_wait_for_server_ready", lambda self: True)
    monkeypatch.setattr(
        "ai.t2i.t2i_adapter.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    ComfyUIT2IAdapter(
        work_path="tools/ComfyUI",
        workflow_path="data/workflows/default.json",
    )

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [Path(sys.executable).resolve().as_posix(), main_script.as_posix()]
    assert kwargs["cwd"] == work_dir.as_posix()
    assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONHOME" not in kwargs["env"]
    assert "PYTHONPATH" not in kwargs["env"]


def test_comfyui_startup_rejects_linked_script_at_launch_boundary(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    workflow = project / "data/workflows/default.json"
    work_dir = project / "tools/ComfyUI"
    external_script = tmp_path / "external-main.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    work_dir.mkdir(parents=True)
    external_script.write_text("", encoding="utf-8")
    try:
        (work_dir / "main.py").symlink_to(external_script)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_is_server_ready", lambda self: False)

    with pytest.raises(PermissionError, match="symbolic link"):
        ComfyUIT2IAdapter(
            work_path="tools/ComfyUI",
            workflow_path="data/workflows/default.json",
        )


def test_comfyui_startup_resolves_standard_venv_python_leaf_alias(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    workflow = project / "data/workflows/default.json"
    work_dir = project / "tools/ComfyUI"
    python_target = tmp_path / "python"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    (work_dir / ".venv/bin").mkdir(parents=True)
    main_script = work_dir / "main.py"
    main_script.write_text("", encoding="utf-8")
    python_target.write_text("", encoding="utf-8")
    python_target.chmod(python_target.stat().st_mode | stat.S_IXUSR)
    try:
        (work_dir / ".venv/bin/python").symlink_to(python_target)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    calls = []
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setattr(ComfyUIT2IAdapter, "_is_server_ready", lambda self: False)
    monkeypatch.setattr(ComfyUIT2IAdapter, "_wait_for_server_ready", lambda self: True)
    monkeypatch.setattr(
        "ai.t2i.t2i_adapter.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    ComfyUIT2IAdapter(
        work_path="tools/ComfyUI",
        workflow_path="data/workflows/default.json",
    )

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [python_target.as_posix(), main_script.as_posix()]
    assert kwargs["cwd"] == work_dir.as_posix()
    assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"
