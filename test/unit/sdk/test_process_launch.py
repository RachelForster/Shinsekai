from __future__ import annotations

import os

import pytest

from sdk import process_launch
from sdk.process_launch import (
    capture_command_executable,
    capture_launch_directory,
    capture_launch_file,
    open_url_with_default_application,
    open_with_default_application,
    popen_with_stable_paths,
    require_launch_file,
    run_shell_with_stable_paths,
    run_with_stable_paths,
    terminate_invalid_launch,
)


class _Process:
    def __init__(self) -> None:
        self.stopped = False

    def terminate(self) -> None:
        self.stopped = True

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.stopped = True


def _executable(path):
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_popen_with_stable_paths_uses_captured_command_and_cwd(tmp_path):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    work = tmp_path / "work"
    work.mkdir()
    cwd = capture_launch_directory(work, field="runtime directory")
    captured = {}
    process = _Process()

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    assert (
        popen_with_stable_paths(
            [executable.path, "--ready"],
            cwd=cwd,
            executable=executable,
            env={"MODE": "test"},
            popen_factory=fake_popen,
        )
        is process
    )
    assert captured["command"] == [str(executable.path), "--ready"]
    assert captured["cwd"] == str(work)
    assert captured["env"] == {"MODE": "test"}
    assert process.stopped is False


def test_popen_with_stable_paths_stops_child_after_required_file_replacement(
    tmp_path,
):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    script_path = tmp_path / "server.py"
    script_path.write_text("print('approved')", encoding="utf-8")
    script = capture_launch_file(script_path, field="runtime script")
    work = tmp_path / "work"
    work.mkdir()
    cwd = capture_launch_directory(work, field="runtime directory")
    process = _Process()

    def replace_during_spawn(*_args, **_kwargs):
        script_path.write_text("print('replacement-is-longer')", encoding="utf-8")
        return process

    with pytest.raises(PermissionError, match="identity changed"):
        popen_with_stable_paths(
            [executable.path, script.path],
            cwd=cwd,
            executable=executable,
            required_files=(script,),
            popen_factory=replace_during_spawn,
        )

    assert process.stopped is True


def test_popen_with_stable_paths_stops_child_after_cwd_replacement(tmp_path):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    work = tmp_path / "work"
    preserved = tmp_path / "work-preserved"
    work.mkdir()
    cwd = capture_launch_directory(work, field="runtime directory")
    process = _Process()

    def replace_during_spawn(*_args, **_kwargs):
        work.rename(preserved)
        work.mkdir()
        return process

    with pytest.raises(PermissionError, match="identity changed"):
        popen_with_stable_paths(
            [executable.path],
            cwd=cwd,
            executable=executable,
            popen_factory=replace_during_spawn,
        )

    assert process.stopped is True


def test_run_with_stable_paths_rejects_required_file_changed_by_command(tmp_path):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    source_path = tmp_path / "source.txt"
    source_path.write_text("approved", encoding="utf-8")
    source = capture_launch_file(source_path, field="command input")
    work = tmp_path / "work"
    work.mkdir()
    cwd = capture_launch_directory(work, field="runtime directory")

    def mutate_input(*_args, **_kwargs):
        source_path.write_text("replacement-is-longer", encoding="utf-8")
        return object()

    with pytest.raises(PermissionError, match="identity changed"):
        run_with_stable_paths(
            [executable.path],
            cwd=cwd,
            executable=executable,
            required_files=(source,),
            run_factory=mutate_input,
        )


def test_default_application_launch_stops_when_target_changes_during_spawn(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "document.txt"
    target.write_text("approved", encoding="utf-8")
    launcher_dir = tmp_path / "bin"
    launcher_dir.mkdir()
    _executable(launcher_dir / "xdg-open")
    process = _Process()
    monkeypatch.setenv("PATH", os.fspath(launcher_dir))

    def replace_during_spawn(*_args, **_kwargs):
        target.write_text("replacement-is-longer", encoding="utf-8")
        return process

    with pytest.raises(PermissionError, match="identity changed"):
        open_with_default_application(
            target,
            system_name="linux",
            popen_factory=replace_during_spawn,
        )

    assert process.stopped is True


def test_command_discovery_skips_cwd_dependent_path_entries(tmp_path):
    invalid = tmp_path / "invalid"
    valid = tmp_path / "valid"
    invalid.mkdir()
    valid.mkdir()
    executable_path = _executable(valid / "tool")

    snapshot = process_launch.capture_command_executable(
        "tool",
        field="test command",
        search_path=f".{os.pathsep}{valid}",
    )

    assert snapshot.path == executable_path


def test_command_discovery_rejects_only_relative_path_entries():
    with pytest.raises(FileNotFoundError, match="deterministic absolute PATH"):
        process_launch.capture_command_executable(
            "tool",
            field="test command",
            search_path=f".{os.pathsep}",
        )


def test_command_discovery_rejects_user_home_aliases():
    with pytest.raises(ValueError, match="must be absolute"):
        process_launch.capture_command_executable(
            "~/tool",
            field="test command",
            search_path="",
        )


@pytest.mark.parametrize("command", ("", " tool", "tool\n"))
def test_command_discovery_rejects_empty_or_ambiguous_names(command):
    with pytest.raises(ValueError, match="empty or contains non-portable"):
        capture_command_executable(command, field="test command", search_path="")


def test_command_discovery_handles_absolute_commands_and_absent_path(
    tmp_path,
    monkeypatch,
):
    executable_path = _executable(tmp_path / "tool")
    assert capture_command_executable(
        executable_path,
        field="test command",
    ).path == executable_path

    monkeypatch.delenv("PATH", raising=False)
    with pytest.raises(FileNotFoundError, match="PATH is absent"):
        capture_command_executable("tool", field="test command")


def test_command_discovery_reports_invalid_absolute_path_entries(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="deterministic absolute PATH") as exc:
        capture_command_executable(
            "tool",
            field="test command",
            search_path=f"{tmp_path.as_posix()}/./alias{os.pathsep}{missing}",
        )

    assert "test command" in str(exc.value)


def test_windows_path_extensions_are_single_portable_suffixes():
    assert process_launch._portable_windows_path_extension(".EXE")
    for extension in (".", "..EXE", ".EXE.", ".EX E", ".工具", " .EXE", ".EXE "):
        assert not process_launch._portable_windows_path_extension(extension)


def test_windows_path_extension_candidates_fit_final_component():
    assert process_launch._portable_windows_executable_candidate_names(
        "a" * 251,
        ".EXE;.工具",
    ) == (f"{'a' * 251}.EXE",)
    assert process_launch._portable_windows_executable_candidate_names(
        "a" * 252,
        ".EXE",
    ) == ()


def test_python_child_environment_cannot_inherit_another_python_tree():
    source = {
        "KEEP": "value",
        "PYTHONEXECUTABLE": "/old/python",
        "PYTHONHOME": "/old/runtime",
        "PYTHONNOUSERSITE": "0",
        "PYTHONPATH": "/old/project",
        "PYTHONPYCACHEPREFIX": "/old/cache",
        "PYTHONUSERBASE": "/old/user",
        "__PYVENV_LAUNCHER__": "/old/launcher",
    }

    environment = process_launch.isolated_python_environment(source)

    assert environment == {"KEEP": "value", "PYTHONNOUSERSITE": "1"}
    assert source["PYTHONHOME"] == "/old/runtime"


def test_launch_guards_reject_empty_or_mismatched_commands(tmp_path):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    work = tmp_path / "work"
    work.mkdir()
    cwd = capture_launch_directory(work, field="runtime directory")

    with pytest.raises(ValueError, match="command is empty"):
        popen_with_stable_paths([], cwd=cwd, executable=executable)
    with pytest.raises(ValueError, match="does not match"):
        popen_with_stable_paths(
            [tmp_path / "peer"],
            cwd=cwd,
            executable=executable,
        )
    with pytest.raises(ValueError, match="command is empty"):
        run_with_stable_paths([], cwd=cwd, executable=executable)
    with pytest.raises(ValueError, match="does not match"):
        run_with_stable_paths(
            [tmp_path / "peer"],
            cwd=cwd,
            executable=executable,
        )


def test_launch_file_rejects_an_unstable_open_snapshot(tmp_path, monkeypatch):
    executable = capture_launch_file(
        _executable(tmp_path / "runtime"),
        field="runtime executable",
        executable=True,
    )
    monkeypatch.setattr(process_launch, "file_snapshot_is_stable", lambda *_: False)

    with pytest.raises(PermissionError, match="changed while its identity was checked"):
        require_launch_file(executable)


def test_invalid_child_termination_falls_back_to_kill():
    class _TerminateFails(_Process):
        def terminate(self):
            raise OSError("terminate failed")

    process = _TerminateFails()
    terminate_invalid_launch(process)

    assert process.stopped is True


def test_shell_launch_uses_captured_shell_and_directory(tmp_path, monkeypatch):
    launcher_dir = tmp_path / "bin"
    launcher_dir.mkdir()
    shell = _executable(launcher_dir / "sh")
    work = tmp_path / "work"
    work.mkdir()
    cwd = capture_launch_directory(work, field="command directory")
    monkeypatch.setenv("PATH", os.fspath(launcher_dir))
    captured = {}
    result = object()

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return result

    assert (
        run_shell_with_stable_paths(
            "printf ready",
            cwd=cwd,
            env={"MODE": "test"},
            run_factory=fake_run,
        )
        is result
    )
    assert captured["command"] == "printf ready"
    assert captured["cwd"] == str(work)
    assert captured["executable"] == str(shell)
    assert captured["shell"] is True
    assert captured["env"] == {"MODE": "test"}


def test_default_application_directory_waits_for_captured_launcher(
    tmp_path,
    monkeypatch,
):
    launcher_dir = tmp_path / "bin"
    launcher_dir.mkdir()
    launcher = _executable(launcher_dir / "xdg-open")
    target = tmp_path / "documents"
    target.mkdir()
    monkeypatch.setenv("PATH", os.fspath(launcher_dir))
    captured = {}
    result = object()

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return result

    assert (
        open_with_default_application(
            target,
            wait=True,
            check=True,
            system_name="linux",
            run_factory=fake_run,
        )
        is result
    )
    assert captured["command"] == [str(launcher), str(target)]
    assert captured["cwd"] == str(target)
    assert captured["check"] is True


def test_default_application_windows_and_unsupported_platform_paths(tmp_path):
    target = tmp_path / "document.txt"
    target.write_text("document", encoding="utf-8")
    opened = []

    assert (
        open_with_default_application(
            target,
            system_name="windows",
            startfile_factory=lambda value: opened.append(value) or "opened",
        )
        == "opened"
    )
    assert opened == [str(target)]

    with pytest.raises(NotImplementedError, match="unsupported"):
        open_with_default_application(target, system_name="plan9")


def test_default_url_launcher_uses_captured_absolute_executable(
    tmp_path,
    monkeypatch,
):
    launcher_dir = tmp_path / "bin"
    launcher_dir.mkdir()
    launcher = _executable(launcher_dir / "xdg-open")
    monkeypatch.setenv("PATH", f".{os.pathsep}{launcher_dir}")
    captured = {}
    process = _Process()

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    assert (
        open_url_with_default_application(
            "http://127.0.0.1:8787/",
            system_name="linux",
            popen_factory=fake_popen,
        )
        is process
    )
    assert captured["command"] == [str(launcher), "http://127.0.0.1:8787/"]
    assert captured["cwd"] == str(launcher_dir)


@pytest.mark.parametrize(
    "url",
    (
        "file:///tmp/project",
        "relative/path",
        "https://user:secret@example.com/",
        " https://example.com/",
    ),
)
def test_default_url_launcher_rejects_non_http_or_ambiguous_values(url):
    with pytest.raises(ValueError):
        open_url_with_default_application(url, system_name="linux")


def test_default_url_launcher_supports_windows_and_rejects_unknown_platforms():
    opened = []
    url = "https://example.com/path"

    assert (
        open_url_with_default_application(
            url,
            system_name="windows",
            startfile_factory=lambda value: opened.append(value) or "opened",
        )
        == "opened"
    )
    assert opened == [url]

    with pytest.raises(NotImplementedError, match="unsupported"):
        open_url_with_default_application(url, system_name="plan9")
