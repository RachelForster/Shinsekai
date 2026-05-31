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
from http.server import ThreadingHTTPServer
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _configure_runtime_context(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
) -> tuple[Path, str]:
    repo_root = _repo_root()
    resolved_frontend_dist = ""
    if frontend_dist:
        dist_path = Path(frontend_dist).expanduser()
        if not dist_path.is_absolute():
            dist_path = repo_root / dist_path
        resolved_frontend_dist = str(dist_path.resolve())

    if project_root:
        root = Path(project_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.environ["EASYAI_PROJECT_ROOT"] = str(root)
        os.chdir(root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root, resolved_frontend_dist


def run(
    host: str,
    port: int,
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    open_browser: bool = False,
) -> None:
    _repo_root_value, resolved_frontend_dist = _configure_runtime_context(
        project_root,
        frontend_dist,
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
    )
    try:
        from core.plugins.plugin_host import ensure_plugins_loaded

        ensure_plugins_loaded(state.config_manager)
    except Exception as exc:
        print(f"Plugin load failed: {exc}")
    server = ThreadingHTTPServer((host, port), FrontendBridgeHandler)
    server.state = state  # type: ignore[attr-defined]
    print(f"Shinsekai frontend bridge listening on http://{host}:{port}")
    frontend_index = Path(resolved_frontend_dist) / "index.html" if resolved_frontend_dist else None
    if frontend_index and frontend_index.is_file():
        print(f"Serving built frontend from {frontend_index.parent}")
        if open_browser:
            _schedule_browser_open(f"http://{host}:{port}/#/settings/api")
    elif resolved_frontend_dist:
        print(f"Built frontend not found at {resolved_frontend_dist}; API bridge only.")
    server.serve_forever()


def check_runtime(
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    requirements_file: str | None = "requirements.txt",
) -> None:
    repo_root, _resolved_frontend_dist = _configure_runtime_context(project_root, frontend_dist)
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
    parser = argparse.ArgumentParser(description="Run the Shinsekai React frontend HTTP bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--project-root",
        default="",
        help="Project/data root to use for relative data/config paths. Defaults to the current directory.",
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
        )
        print("Shinsekai Python runtime check completed.")
        return

    run(
        args.host,
        args.port,
        args.project_root or None,
        args.frontend_dist or None,
        args.open_browser,
    )


if __name__ == "__main__":
    main()
