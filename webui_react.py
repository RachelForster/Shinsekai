#!/usr/bin/env python3
"""Launch the built React frontend through the Shinsekai HTTP bridge."""

from __future__ import annotations

import argparse
import os
import stat
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


def _path_text_is_portable(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and not any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
    )


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent


def _resolve_frontend_dist(repo_root: Path, raw_path: str) -> Path:
    if not _path_text_is_portable(raw_path):
        raise ValueError("frontend distribution path contains non-portable characters")
    from sdk.path_contract import resolve_project_read_path

    try:
        return resolve_project_read_path(raw_path, root=repo_root)
    except PermissionError as exc:
        raise ValueError(
            "frontend distribution path contains a linked component or "
            "escapes repository root"
        ) from exc


def _resolve_project_root(repo_root: Path, raw_path: str | None) -> Path:
    source = "--project-root"
    if raw_path is None:
        for environment_name in (
            "SHINSEKAI_PROJECT_ROOT",
            "EASYAI_PROJECT_ROOT",
        ):
            if environment_name in os.environ:
                raw_path = os.environ[environment_name]
                source = environment_name
                break
        else:
            raw_path = str(repo_root)
            source = "repository root"
    if raw_path == "":
        raise ValueError(f"{source} must not be empty")
    if not _path_text_is_portable(raw_path):
        raise ValueError(f"{source} contains non-portable characters")
    from sdk.path_contract import resolve_project_path

    try:
        return resolve_project_path(".", root=raw_path)
    except ValueError as exc:
        if "must be an absolute path" in str(exc):
            raise ValueError(f"{source} must be an absolute path") from exc
        raise


def _frontend_source_roots(frontend_dir: Path) -> tuple[Path, ...]:
    return (
        frontend_dir / "index.html",
        frontend_dir / "package.json",
        frontend_dir / "pnpm-lock.yaml",
        frontend_dir / "src",
        frontend_dir / "tsconfig.app.json",
        frontend_dir / "tsconfig.json",
        frontend_dir / "tsconfig.node.json",
        frontend_dir / "vite.config.ts",
    )


def _metadata_snapshot(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _validate_frontend_build_inputs(
    frontend_dir: Path,
) -> tuple[tuple[str, str, tuple[int, int, int, int, int, int]], ...]:
    """Return one identity-bound snapshot of every ``pnpm build`` input."""

    from sdk.file_transactions import (
        capture_directory_identity,
        file_snapshot_is_stable,
        inspect_portable_directory_tree_with_metadata,
        open_binary_read_without_links,
        require_directory_identity,
    )
    from sdk.path_contract import (
        _metadata_is_link_or_reparse_point,
        require_symlink_free_absolute_path,
    )

    frontend_dir = require_symlink_free_absolute_path(
        frontend_dir,
        field="frontend source directory",
    )
    try:
        frontend_dir, frontend_identity = capture_directory_identity(
            frontend_dir,
            field="frontend source directory",
        )
    except (FileNotFoundError, NotADirectoryError):
        raise FrontendMigrationNeeded(
            f"Frontend source directory not found: {frontend_dir}"
        ) from None
    snapshot: list[
        tuple[str, str, tuple[int, int, int, int, int, int]]
    ] = []
    for source in _frontend_source_roots(frontend_dir):
        try:
            source_metadata = source.lstat()
        except FileNotFoundError:
            continue
        relative_source = source.relative_to(frontend_dir)
        if _metadata_is_link_or_reparse_point(source_metadata):
            raise PermissionError(
                "frontend build input must not be a symbolic link or reparse "
                f"point: {source}"
            )
        if stat.S_ISDIR(source_metadata.st_mode):
            (
                tree_identity,
                directories,
                files,
            ) = inspect_portable_directory_tree_with_metadata(source)
            if not os.path.samestat(source_metadata, tree_identity):
                raise PermissionError(
                    f"frontend build input identity changed: {source}"
                )
            snapshot.append(
                (
                    "directory",
                    relative_source.as_posix(),
                    _metadata_snapshot(tree_identity),
                )
            )
            snapshot.extend(
                (
                    "directory",
                    (relative_source / relative).as_posix(),
                    _metadata_snapshot(metadata),
                )
                for relative, metadata in directories
            )
            snapshot.extend(
                (
                    "file",
                    (relative_source / relative).as_posix(),
                    _metadata_snapshot(metadata),
                )
                for relative, metadata in files
            )
        elif stat.S_ISREG(source_metadata.st_mode):
            with open_binary_read_without_links(
                source,
                expected_identity=source_metadata,
            ) as source_file:
                opened_metadata = os.fstat(source_file.fileno())
                final_metadata = os.fstat(source_file.fileno())
            if not file_snapshot_is_stable(
                source_metadata,
                opened_metadata,
            ) or not file_snapshot_is_stable(
                opened_metadata,
                final_metadata,
            ):
                raise PermissionError(
                    f"frontend build input identity changed: {source}"
                )
            snapshot.append(
                (
                    "file",
                    relative_source.as_posix(),
                    _metadata_snapshot(opened_metadata),
                )
            )
        else:
            raise PermissionError(
                f"frontend build input is not a regular file or directory: {source}"
            )
    require_directory_identity(
        frontend_dir,
        frontend_identity,
        field="frontend source directory",
    )
    return tuple(sorted(snapshot))


def _frontend_sources_are_newer(frontend_dir: Path, index_path: Path) -> bool:
    from sdk.file_transactions import read_bytes_snapshot_without_links
    from sdk.path_contract import (
        require_symlink_free_absolute_path,
    )

    index_path = require_symlink_free_absolute_path(
        index_path,
        field="frontend distribution index",
    )
    try:
        _content, index_identity = read_bytes_snapshot_without_links(
            index_path,
        )
    except FileNotFoundError:
        return True
    except PermissionError:
        raise
    except OSError:
        return True
    source_snapshot = _validate_frontend_build_inputs(frontend_dir)
    return any(
        kind == "file"
        and metadata[4] > index_identity.st_mtime_ns + 1_000_000
        for kind, _relative, metadata in source_snapshot
    )


def _build_frontend(repo_root: Path, frontend_dist: Path, reason: str) -> None:
    from sdk.file_transactions import (
        capture_directory_identity,
        require_directory_identity,
    )
    from sdk.process_launch import (
        capture_command_executable,
        capture_launch_directory,
        run_with_stable_paths,
    )
    from sdk.path_contract import require_symlink_free_absolute_path

    frontend_dir = require_symlink_free_absolute_path(
        repo_root / "frontend",
        field="frontend source directory",
    )
    default_dist = _resolve_frontend_dist(repo_root, "frontend/dist")
    index_path = require_symlink_free_absolute_path(
        frontend_dist / "index.html",
        field="frontend distribution index",
    )
    if frontend_dist != default_dist:
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}: {index_path}\n"
            "Automatic rebuild is only supported for the default `frontend/dist` output."
        )
    try:
        frontend_dir, frontend_identity = capture_directory_identity(
            frontend_dir,
            field="frontend source directory",
        )
    except (FileNotFoundError, NotADirectoryError):
        raise FrontendMigrationNeeded(f"Frontend source directory not found: {frontend_dir}")
    source_snapshot = _validate_frontend_build_inputs(frontend_dir)
    node_modules = require_symlink_free_absolute_path(
        frontend_dir / "node_modules",
        field="frontend dependency directory",
    )
    try:
        node_modules, node_modules_identity = capture_directory_identity(
            node_modules,
            field="frontend dependency directory",
        )
    except (FileNotFoundError, NotADirectoryError):
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}, but frontend dependencies are not installed.\n"
            "Run `cd frontend && pnpm install` first."
        ) from None

    try:
        pnpm_snapshot = capture_command_executable(
            "pnpm",
            field="pnpm executable",
        )
    except (OSError, PermissionError, RuntimeError, ValueError):
        raise FrontendMigrationNeeded(
            f"Built frontend {reason}, but `pnpm` is not available in PATH.\n"
            "Run `cd frontend && pnpm build` first."
        ) from None
    frontend_launch_snapshot = capture_launch_directory(
        frontend_dir,
        field="frontend source directory",
    )
    node_modules_launch_snapshot = capture_launch_directory(
        node_modules,
        field="frontend dependency directory",
    )
    if not os.path.samestat(
        frontend_identity,
        frontend_launch_snapshot.identity,
    ) or not os.path.samestat(
        node_modules_identity,
        node_modules_launch_snapshot.identity,
    ):
        raise FrontendMigrationNeeded(
            "Frontend build directories changed before the automatic build started."
        )

    print(f"Built frontend {reason}; running `pnpm build`...")
    require_directory_identity(
        frontend_dir,
        frontend_identity,
        field="frontend source directory",
    )
    require_directory_identity(
        node_modules,
        node_modules_identity,
        field="frontend dependency directory",
    )
    completed = run_with_stable_paths(
        [pnpm_snapshot.path, "build"],
        cwd=frontend_launch_snapshot,
        executable=pnpm_snapshot,
        required_directories=(node_modules_launch_snapshot,),
        run_factory=subprocess.run,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    require_directory_identity(
        frontend_dir,
        frontend_identity,
        field="frontend source directory",
    )
    require_directory_identity(
        node_modules,
        node_modules_identity,
        field="frontend dependency directory",
    )
    if _validate_frontend_build_inputs(frontend_dir) != source_snapshot:
        raise FrontendMigrationNeeded(
            "Frontend source files changed while the automatic build was running; "
            "rerun the build from a stable checkout."
        )
    index_path = require_symlink_free_absolute_path(
        frontend_dist / "index.html",
        field="frontend distribution index",
    )
    if not index_path.is_file():
        raise SystemExit(f"Frontend build finished but `{index_path}` was not created.")


def _ensure_frontend_dist(
    repo_root: Path,
    frontend_dist: Path,
    *,
    build_if_missing: bool,
    build_if_stale: bool,
) -> None:
    from sdk.path_contract import require_symlink_free_absolute_path

    frontend_dist = require_symlink_free_absolute_path(
        frontend_dist,
        field="frontend distribution directory",
    )
    index_path = require_symlink_free_absolute_path(
        frontend_dist / "index.html",
        field="frontend distribution index",
    )
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
        from tools.migrate_helper.dialog import MigrationRoleDialog
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"Could not open migration helper dialog: {exc}", file=sys.stderr)
        print(
            "Developers: install pnpm/Corepack and run "
            "`cd frontend && pnpm install && pnpm build`.\n"
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
        default=None,
        help=(
            "Project/data root used by the Python bridge. Defaults to "
            "SHINSEKAI_PROJECT_ROOT, then EASYAI_PROJECT_ROOT, then the repository root."
        ),
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
    parser.add_argument(
        "--show-migration-helper",
        action="store_true",
        help="Open the frontend migration helper dialog and exit.",
    )
    args = parser.parse_args()

    if args.show_migration_helper:
        _show_frontend_migration_dialog(
            "Opening the Shinsekai Frontend migration helper for testing."
        )
        return

    repo_root = _default_repo_root()
    project_root = _resolve_project_root(repo_root, args.project_root)
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
