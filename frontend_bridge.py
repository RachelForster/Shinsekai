"""Lightweight HTTP bridge for the React frontend.

The React layer talks to this process through ``shared/platform``. The bridge
keeps YAML, filesystem, plugin, and chat-launch behavior in Python where the
current project already owns it.
"""

from __future__ import annotations

import argparse
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path


def run(
    host: str,
    port: int,
    project_root: str | None = None,
    frontend_dist: str | None = "frontend/dist",
    open_browser: bool = False,
) -> None:
    repo_root = Path(__file__).resolve().parent
    resolved_frontend_dist = ""
    if frontend_dist:
        dist_path = Path(frontend_dist).expanduser()
        if not dist_path.is_absolute():
            dist_path = repo_root / dist_path
        resolved_frontend_dist = str(dist_path.resolve())

    if project_root:
        root = Path(project_root).expanduser().resolve()
        os.environ["EASYAI_PROJECT_ROOT"] = str(root)
        os.chdir(root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

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
    args = parser.parse_args()
    run(
        args.host,
        args.port,
        args.project_root or None,
        args.frontend_dist or None,
        args.open_browser,
    )


if __name__ == "__main__":
    main()
