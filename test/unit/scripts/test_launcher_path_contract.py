from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
WINDOWS_LAUNCHERS = (
    "start-react.bat",
    "start.bat",
    "start-tauri.bat",
)
WINDOWS_SOURCE_LAUNCHERS = (
    "start-react.bat",
    "start.bat",
)
WINDOWS_COMMAND_LAUNCHERS = (*WINDOWS_LAUNCHERS, "install.bat")
UNIX_LAUNCHERS = (
    "start-react.sh",
    "start-react.command",
    "start.command",
    "install.command",
    "scripts/start.command",
    "scripts/install.command",
    "scripts/start.sh",
    "scripts/install.sh",
)


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_repository_root_contains_no_literal_windows_separator_artifacts():
    offenders = sorted(entry.name for entry in REPO_ROOT.iterdir() if "\\" in entry.name)
    assert offenders == []


def test_windows_launchers_anchor_to_their_own_directory_and_allow_unicode_paths():
    for launcher in WINDOWS_LAUNCHERS:
        content = _text(launcher)
        assert 'set "PROJECT_ROOT=%~dp0"' in content
        assert 'cd /d "%~dp0"' not in content
        assert r"[^\x20-\x7E]" not in content
        assert "Path contains non-ASCII" not in content
        assert "only English letters" not in content


def test_windows_source_launchers_do_not_require_a_local_drive_working_directory():
    for launcher in WINDOWS_SOURCE_LAUNCHERS:
        content = _text(launcher)
        expected_entry = "webui_react.py"
        assert f'"%PROJECT_ROOT%{expected_entry}"' in content
        assert 'if exist "%PROJECT_ROOT%runtime\\python.exe"' in content
        assert f"%PYTHON_CMD% {expected_entry}" not in content
        assert "%PYTHON_CMD%" not in content
        assert ":run_python" in content
        assert ":run_conda" in content
        assert ":resolve_conda_python" in content
        assert (
            '"%CONDA_CMD%" run --cwd "%PROJECT_ROOT%" -n "%CONDA_ENV_NAME%" '
            '"%SHINSEKAI_CONDA_PYTHON%"'
        ) in content
        assert '"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python' not in content
        assert "__SHINSEKAI_CONDA_PREFIX__=" in content
        assert '--cwd "%SystemRoot%\\System32"' in content
        assert "if defined CONDA_PREFIX if /i" in content
        assert ":paths_are_non_reparse" in content
        assert "[IO.FileAttributes]::ReparsePoint" in content
        assert "while($null -ne $item)" in content
        assert "$driveAbsolute=" in content
        assert "$uncAbsolute=" in content
        assert "CONDA_EXE must be an absolute" in content
        assert "CONDA_PREFIX must be an absolute" in content
        assert 'set "PYTHON_EXE=python"' not in content
        assert 'set "CONDA_CMD=conda"' not in content

    installer = _text("install.bat")
    assert '"%PROJECT_ROOT%requirements.txt"' in installer
    assert "%PYTHON_CMD%" not in installer
    assert ":install_with_python" in installer
    assert ":install_with_conda" in installer
    assert ":resolve_conda_python" in installer
    assert (
        '"%CONDA_CMD%" run --cwd "%PROJECT_ROOT%" -n "%CONDA_ENV_NAME%" '
        '"%SHINSEKAI_CONDA_PYTHON%"'
    ) in installer
    assert '"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python' not in installer
    assert ":paths_are_non_reparse" in installer
    assert "[IO.FileAttributes]::ReparsePoint" in installer
    assert "if defined CONDA_PREFIX if /i" in installer
    assert "while($null -ne $item)" in installer
    assert "$driveAbsolute=" in installer
    assert "$uncAbsolute=" in installer
    assert "CONDA_EXE must be an absolute" in installer
    assert "CONDA_PREFIX must be an absolute" in installer
    assert 'set "PYTHON_EXE=python"' not in installer
    assert 'set "CONDA_CMD=conda"' not in installer
    tauri = _text("start-tauri.bat")
    assert 'pushd "%PROJECT_ROOT%frontend"' in tauri
    assert 'set "EXE_PATH=%PROJECT_ROOT%frontend\\src-tauri\\target\\release\\shinsekai.exe"' in tauri
    assert ":paths_are_non_reparse" in tauri
    assert "[IO.FileAttributes]::ReparsePoint" in tauri
    assert "while($null -ne $item)" in tauri
    assert "$driveAbsolute=" in tauri
    assert "$uncAbsolute=" in tauri
    assert "if defined USERPROFILE if exist" in tauri
    assert "USERPROFILE or the rustup cargo path is not an absolute" in tauri


def test_windows_launchers_bind_path_commands_to_checked_absolute_executables():
    for launcher in WINDOWS_COMMAND_LAUNCHERS:
        content = _text(launcher)
        assert ":resolve_command" in content
        assert r"%PROJECT_ROOT%tools\launcher\resolve-command.ps1" in content
        assert (
            r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
            in content
        )
        assert "\npowershell.exe " not in content
        assert "\nwhere " not in content
        assert "where.exe" not in content
        assert 'set "SHINSEKAI_RESOLVED_COMMAND=%%I"' in content
        assert (
            'call :paths_are_non_reparse "%SHINSEKAI_RESOLVED_COMMAND%"'
            in content
        )

    tauri = _text("start-tauri.bat")
    assert 'set "PNPM_CMD=%SHINSEKAI_RESOLVED_COMMAND%"' in tauri
    assert 'set "CARGO_CMD=%SHINSEKAI_RESOLVED_COMMAND%"' in tauri
    assert 'set "CARGO=%CARGO_CMD%"' in tauri
    assert 'call "%PNPM_CMD%" tauri build --no-bundle' in tauri
    assert "call pnpm " not in tauri

    resolver = _text("tools/launcher/resolve-command.ps1")
    assert '$env:PATH.Split(";")' in resolver
    assert "Test-PortableComponent" in resolver
    assert "Test-ExactAbsolutePath" in resolver
    assert "Test-NoReparseComponents" in resolver
    assert (
        r"CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]"
        in resolver
    )
    assert "[Text.Encoding]::UTF8.GetByteCount($Value) -gt 255" in resolver
    assert "$codePoint -ge 0xD800 -and $codePoint -le 0xDFFF" in resolver
    assert r'\A\.[A-Za-z0-9]+\z' in resolver
    assert "Test-PortableComponent $candidateName" in resolver
    assert "$Name.Length -gt 128" not in resolver
    assert '.Split("/", 3)' not in resolver
    assert "[Console]::Out.WriteLine($item.FullName)" in resolver
    assert "Get-Command" not in resolver


def test_non_pyqt_windows_launchers_reject_nonportable_conda_environment_names():
    for launcher in ("start-react.bat", "start.bat", "install.bat"):
        content = _text(launcher)
        assert "$value.EndsWith('.')" in content
        assert (
            r"CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]"
            in content
        )


@pytest.mark.parametrize(
    ("name", "accepted"),
    [
        ("shinsekai", True),
        ("project-env_2", True),
        ("COM10", True),
        ("CON", False),
        ("con.txt", False),
        ("LPT1.env", False),
        ("environment.", False),
        ("bad/name", False),
    ],
)
def test_posix_path_contract_validates_portable_conda_environment_names(
    name,
    accepted,
):
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; shinsekai_portable_environment_name "$2"',
            "path-contract-test",
            str(REPO_ROOT / "tools" / "launcher" / "shell-path-contract.sh"),
            name,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert (result.returncode == 0) is accepted


def test_tauri_launcher_starts_only_the_declared_application_binary():
    content = _text("start-tauri.bat")

    assert r"frontend\src-tauri\target\release\shinsekai.exe" in content
    assert r'target\release\*.exe' not in content
    assert "dir /b /s" not in content


def test_installers_do_not_persist_install_location_specific_qt_paths():
    content = _text("install.bat")

    assert "setx PATH" not in content
    assert r"PyQt5\Qt5\qml" not in content
    assert "QML_PATH" not in content


def test_unix_installer_anchors_relative_resources_to_repository_root():
    content = _text("scripts/install.sh")

    assert 'PROJECT_ROOT="$(CDPATH= cd -P -- "$SCRIPT_DIR/.." && pwd)"' in content
    assert 'cd "$PROJECT_ROOT"' in content
    assert '"$PROJECT_ROOT/requirements.txt"' in content


def test_unix_launchers_follow_script_symlinks_and_never_depend_on_calling_cwd():
    for launcher in UNIX_LAUNCHERS:
        content = _text(launcher)
        assert "set -euo pipefail" in content
        assert "resolve_script_directory()" in content
        assert 'source_path="${BASH_SOURCE[0]}"' in content
        assert 'while [[ -L "$source_path" ]]' in content
        assert "local link_hops=0" in content
        assert "((link_hops > 64))" in content
        assert "too many symbolic-link hops" in content
        assert 'source_path="$(/usr/bin/readlink "$source_path")"' in content
        assert '/usr/bin/dirname "$source_path"' in content
        assert 'source_path="$(readlink ' not in content
        assert 'cd "$PROJECT_ROOT"' in content
        assert "$PWD/" not in content
        assert "${PWD" not in content


def test_unix_launchers_validate_project_identity_before_running():
    react_launchers = ("start-react.sh", "scripts/start.sh", "scripts/install.sh")

    for launcher in react_launchers:
        content = _text(launcher)
        assert '"webui_react.py"' in content
        assert '"requirements.txt"' in content
        assert "CONDA_EXE must be an absolute executable path" in content
        assert "CONDA_PREFIX must be an absolute path" in content
        assert "HOME must be an absolute path when set" in content
        assert '${HOME:-}' in content


def test_unix_launchers_use_the_shared_link_free_path_contract():
    launchers = (
        "start-react.sh",
        "scripts/start.sh",
        "scripts/install.sh",
    )
    for launcher in launchers:
        content = _text(launcher)
        assert 'PATH_CONTRACT="$PROJECT_ROOT/tools/launcher/shell-path-contract.sh"' in content
        assert 'source "$PATH_CONTRACT"' in content
        assert "shinsekai_project_file_is_real" in content

    assert "shinsekai_find_embedded_python" in _text("start-react.sh")
    assert "shinsekai_find_embedded_python" in _text("scripts/start.sh")
    assert "shinsekai_find_embedded_python" in _text("scripts/install.sh")
    assert "shinsekai_absolute_path_has_no_links" in _text(
        "tools/launcher/shell-path-contract.sh"
    )
    assert "shinsekai_resolve_executable" in _text(
        "tools/launcher/shell-path-contract.sh"
    )
    for launcher in ("start-react.sh", "scripts/start.sh", "scripts/install.sh"):
        content = _text(launcher)
        assert (
            'SYSTEM_PYTHON="$(shinsekai_resolve_executable python3)"'
            in content
        )
        assert "PYTHON_CMD=(python3)" not in content
        assert "command -v conda" not in content
        assert "shinsekai_resolve_conda_python" in content
        assert 'run --cwd / -n "$CONDA_ENV_NAME" "$CONDA_PYTHON"' in content
        assert 'run -n "$CONDA_ENV_NAME" python' not in content
    shell_contract = _text("tools/launcher/shell-path-contract.sh")
    assert 'IFS=":" read -r -a search_directories' in shell_contract
    assert "command -v --" not in shell_contract
    assert "__SHINSEKAI_CONDA_PREFIX__=" in shell_contract


def test_macos_command_wrappers_delegate_with_absolute_repository_paths():
    expected = {
        "start-react.command": "start-react.sh",
        "start.command": "scripts/start.sh",
        "install.command": "scripts/install.sh",
        "scripts/start.command": "scripts/start.sh",
        "scripts/install.command": "scripts/install.sh",
    }
    for launcher, delegated_script in expected.items():
        content = _text(launcher)
        assert f'DELEGATED_SCRIPT="$PROJECT_ROOT/{delegated_script}"' in content
        assert 'exec /bin/bash "$DELEGATED_SCRIPT" "$@"' in content
        assert '-L "$DELEGATED_SCRIPT"' in content
        assert f"exec bash {delegated_script}" not in content


def test_react_unix_launcher_resolves_a_symlink_from_an_unrelated_cwd(tmp_path):
    link_dir = tmp_path / "链接 launchers"
    unrelated = tmp_path / "unrelated cwd"
    link_dir.mkdir()
    unrelated.mkdir()
    launcher = link_dir / "start react"
    try:
        launcher.symlink_to(REPO_ROOT / "start-react.sh")
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    environment = os.environ.copy()
    environment["CONDA_DEFAULT_ENV"] = "path-contract-test"
    environment["SHINSEKAI_CONDA_ENV"] = "path-contract-test"
    environment["CONDA_PREFIX"] = sys.prefix
    environment.pop("HOME", None)
    completed = subprocess.run(
        ["bash", str(launcher), "--help"],
        cwd=unrelated,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Run the built Shinsekai React settings UI" in completed.stdout


def test_react_unix_launcher_rejects_relative_conda_prefix_before_launch(tmp_path):
    environment = os.environ.copy()
    environment["CONDA_DEFAULT_ENV"] = "path-contract-test"
    environment["SHINSEKAI_CONDA_ENV"] = "path-contract-test"
    environment["CONDA_PREFIX"] = "relative-env"
    environment.pop("CONDA_EXE", None)

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "start-react.sh"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "CONDA_PREFIX must be an absolute path" in completed.stderr


def _run_shell_contract(project_root: Path, body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; PROJECT_ROOT="$1"; source "$2"; shift 2; ' + body,
            "path-contract-test",
            str(project_root),
            str(REPO_ROOT / "tools" / "launcher" / "shell-path-contract.sh"),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_shell_path_contract_creates_only_real_project_directories(tmp_path):
    project_root = tmp_path / "project with spaces"
    project_root.mkdir()

    completed = _run_shell_contract(
        project_root,
        'shinsekai_ensure_project_directory "data/config"',
    )

    assert completed.returncode == 0, completed.stderr
    assert (project_root / "data" / "config").is_dir()
    assert not (project_root / "data").is_symlink()


def test_shell_executable_resolution_rejects_relative_path_entries(tmp_path):
    project_root = tmp_path / "project"
    relative_bin = project_root / "relative-bin"
    project_root.mkdir()
    relative_bin.mkdir()
    executable = relative_bin / "path-tool"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    relative = _run_shell_contract(
        project_root,
        'cd "$PROJECT_ROOT"; PATH=relative-bin; shinsekai_resolve_executable path-tool',
    )
    absolute = _run_shell_contract(
        project_root,
        'shinsekai_resolve_executable "$PROJECT_ROOT/relative-bin/path-tool"',
    )

    assert relative.returncode != 0
    assert absolute.returncode == 0
    assert absolute.stdout.strip() == str(executable)


def test_shell_executable_resolution_skips_relative_path_entries(tmp_path):
    project_root = tmp_path / "project"
    relative_bin = project_root / "relative-bin"
    absolute_bin = tmp_path / "absolute-bin"
    project_root.mkdir()
    relative_bin.mkdir()
    absolute_bin.mkdir()
    relative_executable = relative_bin / "path-tool"
    absolute_executable = absolute_bin / "path-tool"
    for executable in (relative_executable, absolute_executable):
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    completed = _run_shell_contract(
        project_root,
        (
            'cd "$PROJECT_ROOT"; '
            f'PATH="relative-bin:{absolute_bin}"; '
            "shinsekai_resolve_executable path-tool"
        ),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(absolute_executable)


def test_shell_executable_resolution_resolves_a_leaf_symlink(tmp_path):
    project_root = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    real_dir = tmp_path / "runtime" / "bin"
    project_root.mkdir()
    bin_dir.mkdir()
    real_dir.mkdir(parents=True)
    executable = real_dir / "path-tool"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    alias = bin_dir / "path-tool"
    try:
        alias.symlink_to(Path("..") / "runtime" / "bin" / "path-tool")
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    completed = _run_shell_contract(
        project_root,
        f'PATH="{bin_dir}"; shinsekai_resolve_executable path-tool',
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(executable)


def test_shell_executable_resolution_skips_a_linked_path_directory(tmp_path):
    project_root = tmp_path / "project"
    linked_target = tmp_path / "linked-target"
    safe_bin = tmp_path / "safe-bin"
    linked_bin = tmp_path / "linked-bin"
    project_root.mkdir()
    linked_target.mkdir()
    safe_bin.mkdir()
    for directory in (linked_target, safe_bin):
        executable = directory / "path-tool"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    try:
        linked_bin.symlink_to(linked_target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    completed = _run_shell_contract(
        project_root,
        (
            f'PATH="{linked_bin}:{safe_bin}"; '
            "shinsekai_resolve_executable path-tool"
        ),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(safe_bin / "path-tool")


def test_shell_executable_resolution_rejects_a_linked_parent_for_direct_path(
    tmp_path,
):
    project_root = tmp_path / "project"
    real_bin = tmp_path / "real-bin"
    linked_bin = tmp_path / "linked-bin"
    project_root.mkdir()
    real_bin.mkdir()
    executable = real_bin / "path-tool"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    try:
        linked_bin.symlink_to(real_bin, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    completed = _run_shell_contract(
        project_root,
        f'shinsekai_resolve_executable "{linked_bin}/path-tool"',
    )

    assert completed.returncode != 0


def test_shell_path_contract_rejects_linked_project_directory_without_external_write(tmp_path):
    project_root = tmp_path / "project"
    external = tmp_path / "external"
    project_root.mkdir()
    external.mkdir()
    try:
        (project_root / "data").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    completed = _run_shell_contract(
        project_root,
        'shinsekai_ensure_project_directory "data/config"',
    )

    assert completed.returncode != 0
    assert not (external / "config").exists()


def test_shell_path_contract_rejects_linked_project_file(tmp_path):
    project_root = tmp_path / "project"
    external = tmp_path / "external.py"
    project_root.mkdir()
    external.write_text("print('external')", encoding="utf-8")
    try:
        (project_root / "webui_react.py").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    completed = _run_shell_contract(
        project_root,
        'shinsekai_project_file_is_real "webui_react.py"',
    )

    assert completed.returncode != 0
