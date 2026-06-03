#!/usr/bin/env python3
"""Launch the built React frontend through the Shinsekai HTTP bridge."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure the repository root is on sys.path so that `frontend_bridge` and
# its dependencies are importable regardless of the launching directory.
_repo_root = Path(__file__).resolve().parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from frontend_bridge import run as run_frontend_bridge


class FrontendMigrationNeeded(RuntimeError):
    """Raised when a source checkout cannot launch the built frontend."""


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent


def _resolve_frontend_dist(repo_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _frontend_sources_are_newer(frontend_dir: Path, index_path: Path) -> bool:
    if not index_path.is_file():
        return True
    try:
        index_mtime = index_path.stat().st_mtime
    except OSError:
        return True
    source_roots = [
        frontend_dir / "index.html",
        frontend_dir / "package.json",
        frontend_dir / "pnpm-lock.yaml",
        frontend_dir / "src",
        frontend_dir / "tsconfig.app.json",
        frontend_dir / "tsconfig.json",
        frontend_dir / "tsconfig.node.json",
        frontend_dir / "vite.config.ts",
    ]
    for root in source_roots:
        if not root.exists():
            continue
        paths = root.rglob("*") if root.is_dir() else (root,)
        for path in paths:
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime > index_mtime + 0.001:
                    return True
            except OSError:
                continue
    return False


def _build_frontend(repo_root: Path, frontend_dist: Path, reason: str) -> None:
    frontend_dir = repo_root / "frontend"
    default_dist = (frontend_dir / "dist").resolve()
    index_path = frontend_dist / "index.html"
    if frontend_dist != default_dist:
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}: {index_path}\n"
            "Automatic rebuild is only supported for the default `frontend/dist` output."
        )
    if not frontend_dir.is_dir():
        raise FrontendMigrationNeeded(f"Frontend source directory not found: {frontend_dir}")
    if not (frontend_dir / "node_modules").is_dir():
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}, but frontend dependencies are not installed.\n"
            "Run `cd frontend && pnpm install` first."
        )

    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}, but `pnpm` is not available in PATH.\n"
            "Run `cd frontend && pnpm build` first."
        )

    print(f"Built frontend {reason}; running `pnpm build`...")
    completed = subprocess.run([pnpm, "build"], cwd=frontend_dir)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not index_path.is_file():
        raise SystemExit(f"Frontend build finished but `{index_path}` was not created.")


def _ensure_frontend_dist(
    repo_root: Path,
    frontend_dist: Path,
    *,
    build_if_missing: bool,
    build_if_stale: bool,
) -> None:
    index_path = frontend_dist / "index.html"
    if index_path.is_file():
        frontend_dir = repo_root / "frontend"
        if build_if_stale and _frontend_sources_are_newer(frontend_dir, index_path):
            try:
                _build_frontend(repo_root, frontend_dist, "is older than the source tree")
            except FrontendMigrationNeeded as exc:
                print(
                    f"{exc}\n"
                    "Serving the existing built frontend. Install frontend dependencies and run "
                    "`cd frontend && pnpm build` to rebuild locally.",
                    file=sys.stderr,
                )
        return
    if not build_if_missing:
        raise SystemExit(
            f"Built frontend not found: {index_path}\n"
            "Run `cd frontend && pnpm install && pnpm build` first."
        )

    _build_frontend(repo_root, frontend_dist, "not found")


def _show_frontend_migration_dialog(message: str) -> None:
    print(message, file=sys.stderr)
    print("Opening the Shinsekai Frontend migration helper...", file=sys.stderr)
    try:
        from ui.migrate_helper.dialog import MigrationRoleDialog
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"Could not open migration helper dialog: {exc}", file=sys.stderr)
        print(
            "Developers: install pnpm/Corepack and run `cd frontend && pnpm install && pnpm build`.\n"
            "Users: download the latest release package from "
            "https://github.com/RachelForster/Shinsekai/releases",
            file=sys.stderr,
        )
        return

    app = QApplication.instance() or QApplication([])
    dialog = MigrationRoleDialog()
    dialog.exec()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the built Shinsekai React settings UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument(
        "--project-root",
        default="",
        help="Project/data root used by the Python bridge. Defaults to the repository root.",
    )
    parser.add_argument(
        "--frontend-dist",
        default="frontend/dist",
        help="Built frontend directory to serve. Relative paths resolve from the repository root.",
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Start the bridge without opening the browser automatically.",
    )
    parser.add_argument(
        "--no-build-if-missing",
        action="store_true",
        help="Fail instead of running `pnpm build` when the built frontend is missing.",
    )
    parser.add_argument(
        "--no-build-if-stale",
        action="store_true",
        help="Serve an existing build even when React source files are newer.",
    )
    args = parser.parse_args()

    repo_root = _default_repo_root()
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else repo_root
    frontend_dist = _resolve_frontend_dist(repo_root, args.frontend_dist)
    try:
        _ensure_frontend_dist(
            repo_root,
            frontend_dist,
            build_if_missing=not args.no_build_if_missing,
            build_if_stale=not args.no_build_if_stale,
        )
    except FrontendMigrationNeeded as exc:
        _show_frontend_migration_dialog(str(exc))
        raise SystemExit(1) from exc

    run_frontend_bridge(
        args.host,
        args.port,
        str(project_root),
        str(frontend_dist),
        not args.no_open_browser,
    )


if __name__ == "__main__":
    main()
