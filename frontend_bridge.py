"""Lightweight HTTP bridge for the React frontend.

The React layer talks to this process through ``shared/platform``. The bridge
keeps YAML, filesystem, plugin, and chat-launch behavior in Python where the
current project already owns it.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import re
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path


def _configure_stdio_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _restart_debug_log_path() -> Path:
    if raw_path := os.environ.get("SHINSEKAI_RESTART_LOG"):
        return Path(raw_path)
    return Path(tempfile.gettempdir()) / "shinsekai-restart-debug.log"


def _restart_debug_log(message: str) -> None:
    line = f"ts={time.time():.3f} pid={os.getpid()} component=bridge {message}\n"
    print(f"[restart-debug] {line}", end="")
    try:
        with _restart_debug_log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def _configure_runtime_context(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    app_root: str | None = None,
) -> tuple[Path, str, str]:
    repo_root = _repo_root()
    resolved_frontend_dist = ""
    resolved_app_root = ""
    if frontend_dist:
        dist_path = Path(frontend_dist).expanduser()
        if not dist_path.is_absolute():
            dist_path = repo_root / dist_path
        resolved_frontend_dist = str(dist_path.resolve())

    raw_app_root = app_root or os.environ.get("SHINSEKAI_APP_ROOT")
    if raw_app_root:
        app_root_path = Path(raw_app_root).expanduser().resolve(strict=False)
        if app_root_path.exists() and app_root_path.is_dir():
            resolved_app_root = str(app_root_path)
            os.environ["SHINSEKAI_APP_ROOT"] = resolved_app_root
    if not resolved_app_root:
        resolved_app_root = str(repo_root)
        os.environ.setdefault("SHINSEKAI_APP_ROOT", resolved_app_root)

    if project_root:
        root = Path(project_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.environ["EASYAI_PROJECT_ROOT"] = str(root)
        os.chdir(root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root, resolved_frontend_dist, resolved_app_root


def run(
    host: str,
    port: int,
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    open_browser: bool = False,
    parent_pid: int | None = None,
    app_root: str | None = None,
) -> None:
    _restart_debug_log(
        f"run start host={host} port={port} project_root={project_root or ''} app_root={app_root or ''} frontend_dist={frontend_dist or ''} parent_pid={parent_pid or 0}"
    )
    _start_parent_watchdog(parent_pid)
    _repo_root_value, resolved_frontend_dist, resolved_app_root = _configure_runtime_context(
        project_root,
        frontend_dist,
        app_root,
    )

    from config.background_manager import BackgroundManager
    from config.character_manager import CharacterManager
    from config.config_manager import ConfigManager
    from i18n import init_i18n
    from llm.template_generator import TemplateGenerator

    from frontend_bridge_core.handler import FrontendBridgeHandler
    from frontend_bridge_core.state import BridgeState
    from frontend_bridge_core.static import _schedule_browser_open

    config_manager = ConfigManager()
    init_i18n(config_manager.config.system_config.ui_language)

    state = BridgeState(
        config_manager=config_manager,
        character_manager=CharacterManager(),
        background_manager=BackgroundManager(),
        template_generator=TemplateGenerator(),
        frontend_dist_dir=resolved_frontend_dist,
        app_root_dir=resolved_app_root,
    )
    try:
        from core.plugins.plugin_host import ensure_plugins_loaded

        ensure_plugins_loaded(state.config_manager)
    except Exception as exc:
        print(f"Plugin load failed: {exc}")
    server = ThreadingHTTPServer((host, port), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    _restart_debug_log(f"server listening host={host} port={port} frontend_dist={resolved_frontend_dist}")
    print(f"Shinsekai frontend bridge listening on http://{host}:{port}")
    frontend_index = Path(resolved_frontend_dist) / "index.html" if resolved_frontend_dist else None
    if frontend_index and frontend_index.is_file():
        print(f"Serving built frontend from {frontend_index.parent}")
        if open_browser:
            _schedule_browser_open(f"http://{host}:{port}/#/settings/api")
    elif resolved_frontend_dist:
        print(f"Built frontend not found at {resolved_frontend_dist}; API bridge only.")
    _restart_debug_log("serve_forever enter")
    server.serve_forever()


def _start_parent_watchdog(parent_pid: int | None) -> None:
    if not parent_pid or parent_pid <= 0:
        _restart_debug_log("parent watchdog disabled")
        return

    _restart_debug_log(f"parent watchdog start parent_pid={parent_pid}")

    def watch_parent() -> None:
        if sys.platform == "win32":
            _watch_windows_parent(parent_pid)
            return
        _watch_posix_parent(parent_pid)

    thread = threading.Thread(target=watch_parent, name="shinsekai-parent-watchdog", daemon=True)
    thread.start()


def _watch_posix_parent(parent_pid: int) -> None:
    while True:
        time.sleep(0.25)
        if os.getppid() != parent_pid:
            _restart_debug_log(
                f"parent watchdog exit reason=ppid_changed expected={parent_pid} actual={os.getppid()}"
            )
            os._exit(0)
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            _restart_debug_log(f"parent watchdog exit reason=parent_missing parent_pid={parent_pid}")
            os._exit(0)
        except PermissionError:
            continue


def _watch_windows_parent(parent_pid: int) -> None:
    import ctypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        _restart_debug_log(f"parent watchdog exit reason=open_process_failed parent_pid={parent_pid}")
        os._exit(0)
    try:
        while True:
            time.sleep(0.25)
            if kernel32.WaitForSingleObject(handle, 0) != wait_timeout:
                _restart_debug_log(f"parent watchdog exit reason=parent_signaled parent_pid={parent_pid}")
                os._exit(0)
    finally:
        kernel32.CloseHandle(handle)


def check_runtime(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    requirements_file: str | None = "requirements.txt",
    app_root: str | None = None,
) -> None:
    repo_root, _resolved_frontend_dist, _resolved_app_root = _configure_runtime_context(
        project_root,
        frontend_dist,
        app_root,
    )
    if requirements_file:
        requirements_path = Path(requirements_file).expanduser()
        if not requirements_path.is_absolute():
            requirements_path = repo_root / requirements_path
        _check_required_distributions(requirements_path)

    from config.background_manager import BackgroundManager
    from config.character_manager import CharacterManager
    from config.config_manager import ConfigManager
    from i18n import init_i18n
    from llm.template_generator import TemplateGenerator

    from frontend_bridge_core.handler import FrontendBridgeHandler  # noqa: F401
    from frontend_bridge_core.state import BridgeState  # noqa: F401
    from frontend_bridge_core.static import _frontend_dist_root  # noqa: F401

    config_manager = ConfigManager()
    init_i18n(config_manager.config.system_config.ui_language)
    CharacterManager()
    BackgroundManager()
    TemplateGenerator()


def _check_required_distributions(requirements_path: Path) -> None:
    if not requirements_path.is_file():
        raise FileNotFoundError(f"requirements file not found: {requirements_path}")

    missing: list[str] = []
    for requirement in _iter_requirement_names(requirements_path):
        try:
            importlib.metadata.version(requirement)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement)

    if missing:
        joined = ", ".join(sorted(set(missing)))
        raise RuntimeError(f"missing Python runtime distributions: {joined}")


def _iter_requirement_names(requirements_path: Path):
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "http://", "https://")):
            continue

        requirement, marker = _split_requirement_marker(line)
        if marker and not _marker_applies(marker):
            continue

        name = re.split(r"\s*(?:===|==|~=|!=|<=|>=|<|>)\s*", requirement, maxsplit=1)[0]
        name = name.split("[", 1)[0].strip()
        if name:
            yield name


def _split_requirement_marker(line: str) -> tuple[str, str]:
    requirement, separator, marker = line.partition(";")
    if not separator:
        return requirement.strip(), ""
    return requirement.strip(), marker.strip()


def _marker_applies(marker: str) -> bool:
    groups = re.split(r"\s+or\s+", marker)
    return any(_marker_and_group_applies(group) for group in groups)


def _marker_and_group_applies(group: str) -> bool:
    clauses = re.split(r"\s+and\s+", group)
    return all(_marker_clause_applies(clause) for clause in clauses)


def _marker_clause_applies(clause: str) -> bool:
    match = re.fullmatch(
        r'\s*(sys_platform|platform_machine)\s*(==|!=)\s*["\']([^"\']+)["\']\s*',
        clause,
    )
    if not match:
        return True
    name, operator, expected = match.groups()
    actual = sys.platform if name == "sys_platform" else platform.machine()
    if operator == "==":
        return actual == expected
    return actual != expected


def main() -> None:
    _configure_stdio_encoding()
    parser = argparse.ArgumentParser(description="Run the Shinsekai React frontend HTTP bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--project-root",
        default="",
        help="Project/data root to use for relative data/config paths. Defaults to the current directory.",
    )
    parser.add_argument(
        "--app-root",
        default="",
        help="Application install directory used by the file browser Shinsekai location.",
    )
    parser.add_argument(
        "--frontend-dist",
        default="frontend/dist",
        help="Built frontend directory to serve. Relative paths resolve from the repository root.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the built React settings UI in the default browser after startup.",
    )
    parser.add_argument(
        "--parent-pid",
        default=0,
        type=int,
        help="Desktop shell process PID. The bridge exits automatically when this parent exits.",
    )
    parser.add_argument(
        "--check-runtime",
        action="store_true",
        help="Validate the Python runtime and exit without starting the HTTP bridge.",
    )
    parser.add_argument(
        "--requirements-file",
        default="requirements.txt",
        help="Requirements file used by --check-runtime. Relative paths resolve from the repository root.",
    )
    args = parser.parse_args()
    if args.check_runtime:
        check_runtime(
            args.project_root or None,
            args.frontend_dist or None,
            args.requirements_file or None,
            args.app_root or None,
        )
        print("Shinsekai Python runtime check completed.")
        return

    run(
        host=args.host,
        port=args.port,
        project_root=args.project_root or None,
        frontend_dist=args.frontend_dist or None,
        open_browser=args.open_browser,
        parent_pid=args.parent_pid or None,
        app_root=args.app_root or None,
    )


if __name__ == "__main__":
    main()
