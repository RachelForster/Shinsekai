"""Lightweight HTTP bridge for the React frontend.

The React layer talks to this process through ``shared/platform``. The bridge
keeps YAML, filesystem, plugin, and chat-launch behavior in Python where the
current project already owns it.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import signal
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


_bridge_state_lock = threading.Lock()
_bridge_state = None


def _set_bridge_state(state) -> None:
    global _bridge_state
    with _bridge_state_lock:
        _bridge_state = state


def _shutdown_bridge_runtime(reason: str) -> None:
    _restart_debug_log(f"bridge runtime shutdown begin reason={reason}")
    try:
        from frontend_bridge_core.chat import shutdown_active_chat_process

        shutdown_active_chat_process(wait_timeout=1.5)
    except Exception as exc:
        _restart_debug_log(f"bridge runtime chat shutdown failed reason={reason} error={exc}")

    with _bridge_state_lock:
        state = _bridge_state
    chat_stream = getattr(state, "chat_stream", None) if state is not None else None
    if chat_stream is not None:
        try:
            chat_stream.stop()
        except Exception as exc:
            _restart_debug_log(f"bridge runtime chat stream stop failed reason={reason} error={exc}")
    _restart_debug_log(f"bridge runtime shutdown completed reason={reason}")


def _install_bridge_signal_handlers() -> None:
    def handle_signal(signum, _frame) -> None:
        _restart_debug_log(f"bridge signal received signum={signum}")
        _shutdown_bridge_runtime(f"signal {signum}")
        os._exit(0)

    for signum in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if signum is None:
            continue
        with contextlib.suppress(ValueError):
            signal.signal(signum, handle_signal)


def _configure_runtime_context(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    app_root: str | None = None,
) -> tuple[Path, str, str]:
    repo_root = _repo_root()
    os.environ["SHINSEKAI_SOURCE_ROOT"] = str(repo_root)
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


def _start_plugin_loader(state, logger) -> None:
    from frontend_bridge_core.state import set_plugin_load_status

    def load_plugins() -> None:
        time.sleep(0.05)
        set_plugin_load_status(state, "loading")
        _restart_debug_log("plugin load background start")
        try:
            from core.plugins.plugin_host import ensure_plugins_loaded

            ensure_plugins_loaded(state.config_manager)
        except Exception as exc:
            set_plugin_load_status(state, "error", error=str(exc))
            _restart_debug_log(f"plugin load background failed error={exc}")
            logger.exception("Plugin load failed", extra={"event": "plugin.load.failed"})
            return
        set_plugin_load_status(state, "ready")
        _restart_debug_log("plugin load background completed")
        logger.info("Plugin load completed", extra={"event": "plugin.load.completed"})

    thread = threading.Thread(
        target=load_plugins,
        name="shinsekai-plugin-loader",
        daemon=True,
    )
    thread.start()


def run(
    host: str,
    port: int,
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    open_browser: bool = False,
    parent_pid: int | None = None,
    app_root: str | None = None,
    auth_token: str | None = None,
) -> None:
    _restart_debug_log(
        f"run start host={host} port={port} project_root={project_root or ''} app_root={app_root or ''} frontend_dist={frontend_dist or ''} parent_pid={parent_pid or 0}"
    )
    _install_bridge_signal_handlers()
    _start_parent_watchdog(parent_pid)
    _repo_root_value, resolved_frontend_dist, resolved_app_root = _configure_runtime_context(
        project_root,
        frontend_dist,
        app_root,
    )
    from sdk.logging import configure_logging, get_logger

    configure_logging("frontend-bridge", project_root=Path.cwd())
    logger = get_logger(__name__)
    from config.mirror_env import apply_mirror_environment_from_system_config

    apply_mirror_environment_from_system_config()

    from config.background_manager import BackgroundManager
    from config.character_manager import CharacterManager
    from config.config_manager import ConfigManager
    from i18n import init_i18n
    from llm.template_generator import TemplateGenerator

    from frontend_bridge_core.chat_stream import ChatStreamService
    from frontend_bridge_core.handler import FrontendBridgeHandler
    from frontend_bridge_core.state import BridgeState
    from frontend_bridge_core.static import _schedule_browser_open

    config_manager = ConfigManager()
    init_i18n(config_manager.config.system_config.ui_language)
    bridge_auth_token = (
        str(auth_token or "").strip()
        or os.environ.get("SHINSEKAI_BRIDGE_AUTH_TOKEN", "").strip()
        or secrets.token_urlsafe(32)
    )

    state = BridgeState(
        config_manager=config_manager,
        character_manager=CharacterManager(),
        background_manager=BackgroundManager(),
        template_generator=TemplateGenerator(),
        frontend_dist_dir=resolved_frontend_dist,
        app_root_dir=resolved_app_root,
        auth_token=bridge_auth_token,
    )
    _set_bridge_state(state)
    state.chat_stream = ChatStreamService(host=host, bridge_port=port, auth_token=bridge_auth_token)
    state.chat_stream.start()
    server = ThreadingHTTPServer((host, port), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    _restart_debug_log(f"server listening host={host} port={port} frontend_dist={resolved_frontend_dist}")
    _start_plugin_loader(state, logger)
    logger.info(
        "Frontend bridge listening",
        extra={
            "event": "http.server.started",
            "host": host,
            "port": port,
        },
    )
    frontend_index = Path(resolved_frontend_dist) / "index.html" if resolved_frontend_dist else None
    if frontend_index and frontend_index.is_file():
        logger.info(
            "Serving built frontend",
            extra={
                "event": "frontend.static.ready",
                "frontend_dist": str(frontend_index.parent),
            },
        )
        if open_browser:
            _schedule_browser_open(
                f"http://{host}:{port}/?shinsekai_bridge_token={bridge_auth_token}#/settings/api"
            )
    elif resolved_frontend_dist:
        logger.warning(
            "Built frontend not found; API bridge only",
            extra={
                "event": "frontend.static.missing",
                "frontend_dist": resolved_frontend_dist,
            },
        )
    _restart_debug_log("serve_forever enter")
    try:
        server.serve_forever()
    finally:
        _restart_debug_log("serve_forever exit")
        with contextlib.suppress(Exception):
            server.server_close()
        _shutdown_bridge_runtime("server exit")
        _set_bridge_state(None)


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
            _exit_bridge_after_parent_loss(
                f"ppid_changed expected={parent_pid} actual={os.getppid()}"
            )
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            _exit_bridge_after_parent_loss(f"parent_missing parent_pid={parent_pid}")
        except PermissionError:
            continue


def _exit_bridge_after_parent_loss(detail: str) -> None:
    _restart_debug_log(f"parent watchdog exit reason={detail}")
    _shutdown_bridge_runtime(f"parent watchdog {detail}")
    os._exit(0)


def _watch_windows_parent(parent_pid: int) -> None:
    import ctypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        _exit_bridge_after_parent_loss(f"open_process_failed parent_pid={parent_pid}")
    try:
        while True:
            time.sleep(0.25)
            if kernel32.WaitForSingleObject(handle, 0) != wait_timeout:
                _exit_bridge_after_parent_loss(f"parent_signaled parent_pid={parent_pid}")
    finally:
        kernel32.CloseHandle(handle)


def check_runtime(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    requirements_file: str | None = None,
    app_root: str | None = None,
    profile: str = "desktop-core",
) -> None:
    repo_root, _resolved_frontend_dist, _resolved_app_root = _configure_runtime_context(
        project_root,
        frontend_dist,
        app_root,
    )
    from sdk.logging import configure_logging

    configure_logging("frontend-bridge", project_root=Path.cwd())
    from config.mirror_env import apply_mirror_environment_from_system_config

    apply_mirror_environment_from_system_config()
    requirements_file = requirements_file or _default_runtime_requirements_file(repo_root, profile)
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


def runtime_check_report(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    requirements_file: str | None = None,
    app_root: str | None = None,
    profile: str = "desktop-core",
) -> dict[str, object]:
    try:
        check_runtime(project_root, frontend_dist, requirements_file, app_root, profile)
    except Exception as exc:
        message = str(exc)
        return {
            "ok": False,
            "profile": profile,
            "message": message,
            "missingDistributions": _missing_distributions_from_message(message),
        }
    return {
        "ok": True,
        "profile": profile,
        "message": "Shinsekai Python runtime check completed.",
        "missingDistributions": [],
    }


def _default_runtime_requirements_file(repo_root: Path, profile: str) -> str:
    if profile == "desktop-core":
        core = repo_root / "requirements-runtime-core.txt"
        if core.is_file():
            return str(core)
    return str(repo_root / "requirements.txt")


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


def _missing_distributions_from_message(message: str) -> list[str]:
    prefix = "missing Python runtime distributions:"
    if prefix not in message:
        return []
    return [
        item.strip()
        for item in message.split(prefix, 1)[1].split(",", maxsplit=128)
        if item.strip()
    ]


def _iter_requirement_names(requirements_path: Path, seen: set[Path] | None = None):
    requirements_path = requirements_path.resolve()
    seen = seen or set()
    if requirements_path in seen:
        return
    seen.add(requirements_path)
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        included_path = _included_requirements_path(requirements_path, line)
        if included_path is not None:
            yield from _iter_requirement_names(included_path, seen)
            continue

        if line.startswith(("-", "http://", "https://")):
            continue

        requirement, marker = _split_requirement_marker(line)
        if marker and not _marker_applies(marker):
            continue

        name = re.split(r"\s*(?:===|==|~=|!=|<=|>=|<|>)\s*", requirement, maxsplit=1)[0]
        name = name.split("[", 1)[0].strip()
        if name:
            yield name


def _included_requirements_path(requirements_path: Path, line: str) -> Path | None:
    tokens = line.split()
    if not tokens:
        return None
    if tokens[0] in {"-r", "--requirement"} and len(tokens) >= 2:
        included = Path(tokens[1]).expanduser()
    elif tokens[0].startswith("--requirement="):
        included = Path(tokens[0].split("=", 1)[1]).expanduser()
    else:
        return None
    if not included.is_absolute():
        included = requirements_path.parent / included
    return included


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
        "--auth-token",
        default="",
        help="Shared token required by frontend HTTP write requests and chat WebSocket connections.",
    )
    parser.add_argument(
        "--check-runtime",
        action="store_true",
        help="Validate the Python runtime and exit without starting the HTTP bridge.",
    )
    parser.add_argument(
        "--requirements-file",
        default="",
        help="Requirements file used by --check-runtime. Relative paths resolve from the repository root.",
    )
    parser.add_argument(
        "--profile",
        default="desktop-core",
        help="Runtime requirements profile used by --check-runtime.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a structured runtime check report as JSON.",
    )
    args = parser.parse_args()
    if args.check_runtime:
        if args.json:
            with contextlib.redirect_stdout(sys.stderr):
                report = runtime_check_report(
                    args.project_root or None,
                    args.frontend_dist or None,
                    args.requirements_file or None,
                    args.app_root or None,
                    args.profile,
                )
            print(json.dumps(report, ensure_ascii=True))
            if not report["ok"]:
                raise SystemExit(1)
        else:
            check_runtime(
                args.project_root or None,
                args.frontend_dist or None,
                args.requirements_file or None,
                args.app_root or None,
                args.profile,
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
        auth_token=args.auth_token or None,
    )


if __name__ == "__main__":
    main()
