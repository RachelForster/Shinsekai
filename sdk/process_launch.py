"""Stable identity-bound primitives for subprocess launch boundaries.

External runtimes only accept path strings.  Capture every selected file and
directory before composing the command, then validate the same objects
immediately before and after process creation.  If a public pathname is
replaced during ``Popen``, terminate the child instead of letting discovery
and execution silently refer to different filesystem objects.
"""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sdk.file_transactions import (
    capture_directory_identity,
    file_snapshot_is_stable,
    open_binary_read_without_links,
    require_directory_identity,
)
from sdk.path_contract import (
    path_is_link_or_reparse_point,
    require_regular_file_without_links,
    resolve_executable_file,
    safe_path_component,
    validate_exact_path_text,
)

_PYTHON_LOCATION_ENVIRONMENT_NAMES = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUSERBASE",
    "PYTHONPYCACHEPREFIX",
    "PYTHONEXECUTABLE",
    "__PYVENV_LAUNCHER__",
)


@dataclass(frozen=True)
class LaunchDirectorySnapshot:
    path: Path
    identity: os.stat_result
    field: str


@dataclass(frozen=True)
class LaunchFileSnapshot:
    path: Path
    identity: os.stat_result
    parent: LaunchDirectorySnapshot
    field: str


def isolated_python_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child environment that cannot inherit another Python tree."""

    environment = dict(os.environ if source is None else source)
    for name in _PYTHON_LOCATION_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def capture_launch_directory(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> LaunchDirectorySnapshot:
    path, identity = capture_directory_identity(value, field=field)
    return LaunchDirectorySnapshot(path=path, identity=identity, field=field)


def capture_launch_file(
    value: str | os.PathLike[str],
    *,
    field: str,
    executable: bool = False,
) -> LaunchFileSnapshot:
    path = (
        resolve_executable_file(value, field=field)
        if executable
        else require_regular_file_without_links(value, field=field)
    )
    parent = capture_launch_directory(
        path.parent,
        field=f"{field} parent",
    )
    with open_binary_read_without_links(
        path,
        expected_parent_identity=parent.identity,
    ) as handle:
        before = os.fstat(handle.fileno())
        after = os.fstat(handle.fileno())
    if not file_snapshot_is_stable(before, after):
        raise PermissionError(f"{field} changed while its identity was captured: {path}")
    require_launch_directory(parent)
    return LaunchFileSnapshot(
        path=path,
        identity=after,
        parent=parent,
        field=field,
    )


def capture_command_executable(
    value: str | os.PathLike[str],
    *,
    field: str,
    search_path: str | None = None,
    path_extensions: str | None = None,
) -> LaunchFileSnapshot:
    raw = os.fspath(value)
    if (
        not raw
        or raw != raw.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        raise ValueError(f"{field} is empty or contains non-portable characters")
    candidate = Path(raw)
    if candidate.is_absolute():
        return capture_launch_file(
            candidate,
            field=field,
            executable=True,
        )
    elif "/" in raw or "\\" in raw:
        raise ValueError(f"{field} path must be absolute")
    safe_path_component(raw, field=field)

    configured_path = os.environ.get("PATH") if search_path is None else search_path
    if configured_path is None:
        raise FileNotFoundError(f"{field} cannot be resolved because PATH is absent")
    last_error: BaseException | None = None
    for directory_value in configured_path.split(os.pathsep):
        if not directory_value:
            continue
        try:
            validate_exact_path_text(
                directory_value,
                field=f"{field} PATH directory",
            )
            directory = Path(directory_value)
        except (OSError, PermissionError, RuntimeError, ValueError) as exc:
            last_error = exc
            continue
        if not directory.is_absolute():
            continue
        for name in _executable_candidate_names(raw, path_extensions):
            try:
                return capture_launch_file(
                    directory / name,
                    field=field,
                    executable=True,
                )
            except (OSError, PermissionError, RuntimeError, ValueError) as exc:
                last_error = exc
    detail = f": {last_error}" if last_error is not None else ""
    raise FileNotFoundError(
        f"{field} was not found in deterministic absolute PATH entries: {raw}{detail}"
    )


def _executable_candidate_names(
    command: str,
    path_extensions: str | None,
) -> tuple[str, ...]:
    if os.name != "nt" or Path(command).suffix:
        return (command,)
    return _portable_windows_executable_candidate_names(
        command,
        path_extensions,
    )


def _portable_windows_executable_candidate_names(
    command: str,
    path_extensions: str | None,
) -> tuple[str, ...]:
    """Append only PATHEXT suffixes whose final component stays portable."""

    configured = (
        os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        if path_extensions is None
        else path_extensions
    )
    extensions = [
        extension
        for extension in configured.split(";")
        if _portable_windows_path_extension(extension)
    ]
    candidates: list[str] = []
    for extension in extensions:
        candidate = f"{command}{extension}"
        try:
            safe_path_component(
                candidate,
                field="Windows executable candidate",
            )
        except ValueError:
            continue
        candidates.append(candidate)
    return tuple(candidates)


def _portable_windows_path_extension(value: str) -> bool:
    return (
        len(value) > 1
        and value.startswith(".")
        and all(
            character.isascii() and character.isalnum()
            for character in value[1:]
        )
    )


def require_launch_directory(snapshot: LaunchDirectorySnapshot) -> None:
    require_directory_identity(
        snapshot.path,
        snapshot.identity,
        field=snapshot.field,
    )


def require_launch_file(snapshot: LaunchFileSnapshot) -> None:
    require_launch_directory(snapshot.parent)
    with open_binary_read_without_links(
        snapshot.path,
        expected_identity=snapshot.identity,
        expected_parent_identity=snapshot.parent.identity,
    ) as handle:
        before = os.fstat(handle.fileno())
        after = os.fstat(handle.fileno())
    if not file_snapshot_is_stable(before, after):
        raise PermissionError(
            f"{snapshot.field} changed while its identity was checked: {snapshot.path}"
        )
    require_launch_directory(snapshot.parent)


def require_launch_snapshots(
    *,
    directories: Iterable[LaunchDirectorySnapshot] = (),
    files: Iterable[LaunchFileSnapshot] = (),
) -> None:
    for directory in directories:
        require_launch_directory(directory)
    for file in files:
        require_launch_file(file)


def terminate_invalid_launch(process: Any) -> None:
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def popen_with_stable_paths(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: LaunchDirectorySnapshot,
    executable: LaunchFileSnapshot,
    required_directories: Sequence[LaunchDirectorySnapshot] = (),
    required_files: Sequence[LaunchFileSnapshot] = (),
    env: Mapping[str, str] | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    **popen_kwargs: Any,
) -> Any:
    if not argv:
        raise ValueError("process command is empty")
    command = [os.fspath(item) for item in argv]
    if os.path.normcase(os.path.normpath(command[0])) != os.path.normcase(
        os.path.normpath(os.fspath(executable.path))
    ):
        raise ValueError("process executable does not match its captured path")
    directories = (cwd, *required_directories)
    files = (executable, *required_files)
    require_launch_snapshots(directories=directories, files=files)
    launch_kwargs = {
        **popen_kwargs,
        "cwd": os.fspath(cwd.path),
    }
    if env is not None:
        launch_kwargs["env"] = dict(env)
    process = popen_factory(command, **launch_kwargs)
    try:
        require_launch_snapshots(directories=directories, files=files)
    except BaseException:
        terminate_invalid_launch(process)
        raise
    return process


def run_with_stable_paths(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: LaunchDirectorySnapshot,
    executable: LaunchFileSnapshot,
    required_directories: Sequence[LaunchDirectorySnapshot] = (),
    required_files: Sequence[LaunchFileSnapshot] = (),
    env: Mapping[str, str] | None = None,
    run_factory: Callable[..., Any] = subprocess.run,
    **run_kwargs: Any,
) -> Any:
    if not argv:
        raise ValueError("process command is empty")
    command = [os.fspath(item) for item in argv]
    if os.path.normcase(os.path.normpath(command[0])) != os.path.normcase(
        os.path.normpath(os.fspath(executable.path))
    ):
        raise ValueError("process executable does not match its captured path")
    directories = (cwd, *required_directories)
    files = (executable, *required_files)
    require_launch_snapshots(directories=directories, files=files)
    launch_kwargs = {
        **run_kwargs,
        "cwd": os.fspath(cwd.path),
    }
    if env is not None:
        launch_kwargs["env"] = dict(env)
    result = run_factory(command, **launch_kwargs)
    require_launch_snapshots(directories=directories, files=files)
    return result


def run_shell_with_stable_paths(
    command: str,
    *,
    cwd: LaunchDirectorySnapshot,
    required_directories: Sequence[LaunchDirectorySnapshot] = (),
    required_files: Sequence[LaunchFileSnapshot] = (),
    env: Mapping[str, str] | None = None,
    run_factory: Callable[..., Any] = subprocess.run,
    **run_kwargs: Any,
) -> Any:
    shell = capture_command_executable(
        os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "sh",
        field="command shell executable",
    )
    directories = (cwd, *required_directories)
    files = (shell, *required_files)
    require_launch_snapshots(directories=directories, files=files)
    launch_kwargs = {
        **run_kwargs,
        "cwd": os.fspath(cwd.path),
        "executable": os.fspath(shell.path),
        "shell": True,
    }
    if env is not None:
        launch_kwargs["env"] = dict(env)
    result = run_factory(command, **launch_kwargs)
    require_launch_snapshots(directories=directories, files=files)
    return result


def open_with_default_application(
    value: str | os.PathLike[str],
    *,
    wait: bool = False,
    check: bool = False,
    system_name: str | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    run_factory: Callable[..., Any] = subprocess.run,
    startfile_factory: Callable[[str], Any] | None = None,
) -> Any:
    path = Path(value)
    if path_is_link_or_reparse_point(path):
        raise PermissionError(
            f"default application target must not be a symbolic link: {path}"
        )
    try:
        file_snapshot = capture_launch_file(
            path,
            field="default application target",
        )
    except (FileNotFoundError, IsADirectoryError):
        file_snapshot = None
        directory_snapshot = capture_launch_directory(
            path,
            field="default application target",
        )
        cwd = directory_snapshot
    else:
        directory_snapshot = None
        cwd = file_snapshot.parent

    selected_system = (system_name or platform.system()).lower()
    if selected_system == "windows":
        startfile = startfile_factory or getattr(os, "startfile", None)
        if startfile is None:
            raise NotImplementedError("the platform does not provide os.startfile")
        result = startfile(os.fspath(path))
        require_launch_snapshots(
            directories=(
                (directory_snapshot,) if directory_snapshot is not None else ()
            ),
            files=((file_snapshot,) if file_snapshot is not None else ()),
        )
        return result

    command_name = "open" if selected_system == "darwin" else "xdg-open"
    if selected_system not in {"darwin", "linux"}:
        raise NotImplementedError(
            f"default application launch is unsupported on {selected_system}"
        )
    opener = capture_command_executable(
        command_name,
        field="default application launcher",
    )
    required_directories = (
        (directory_snapshot,) if directory_snapshot is not None else ()
    )
    required_files = (file_snapshot,) if file_snapshot is not None else ()
    command = [opener.path, path]
    if wait:
        return run_with_stable_paths(
            command,
            cwd=cwd,
            executable=opener,
            required_directories=required_directories,
            required_files=required_files,
            run_factory=run_factory,
            check=check,
        )
    return popen_with_stable_paths(
        command,
        cwd=cwd,
        executable=opener,
        required_directories=required_directories,
        required_files=required_files,
        popen_factory=popen_factory,
    )


def open_url_with_default_application(
    value: str,
    *,
    system_name: str | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    startfile_factory: Callable[[str], Any] | None = None,
) -> Any:
    url = str(value)
    if (
        not url
        or url != url.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise ValueError("browser URL is empty or contains non-portable characters")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("browser URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("browser URL must not contain embedded credentials")

    selected_system = (system_name or platform.system()).lower()
    if selected_system == "windows":
        startfile = startfile_factory or getattr(os, "startfile", None)
        if startfile is None:
            raise NotImplementedError("the platform does not provide os.startfile")
        return startfile(url)

    command_name = "open" if selected_system == "darwin" else "xdg-open"
    if selected_system not in {"darwin", "linux"}:
        raise NotImplementedError(
            f"default URL launch is unsupported on {selected_system}"
        )
    opener = capture_command_executable(
        command_name,
        field="default URL launcher",
    )
    return popen_with_stable_paths(
        [opener.path, url],
        cwd=opener.parent,
        executable=opener,
        popen_factory=popen_factory,
    )


__all__ = [
    "LaunchDirectorySnapshot",
    "LaunchFileSnapshot",
    "capture_launch_directory",
    "capture_launch_file",
    "capture_command_executable",
    "isolated_python_environment",
    "popen_with_stable_paths",
    "open_with_default_application",
    "open_url_with_default_application",
    "require_launch_directory",
    "require_launch_file",
    "require_launch_snapshots",
    "run_shell_with_stable_paths",
    "run_with_stable_paths",
    "terminate_invalid_launch",
]
