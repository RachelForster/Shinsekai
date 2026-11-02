"""Shared path policy for application-owned media resource operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from sdk.path_utils import safe_child_path, safe_existing_file_path, safe_filename, safe_project_path


class MediaResourcePaths:
    def __init__(self, project_root: Path, *, file_access_roots: Iterable[Path] = ()):
        self.project_root = project_root.resolve(strict=False)
        roots = [Path(root).resolve(strict=False) for root in file_access_roots]
        roots.append(self.project_root)
        self.file_access_roots = tuple(dict.fromkeys(roots))

    def input_file(self, raw_path: Any, *, field: str) -> Path:
        return safe_existing_file_path(
            str(raw_path or "").strip(),
            roots=self.file_access_roots,
            field=field,
        )

    def input_files(self, raw_paths: Any, *, field: str) -> list[Path]:
        if not isinstance(raw_paths, list):
            raise ValueError("paths must be a list")
        paths = [
            self.input_file(item, field=field)
            for item in raw_paths
            if str(item or "").strip()
        ]
        if not paths:
            raise ValueError("at least one path is required")
        return paths

    def export_target(self, name: str, suffix: str) -> tuple[Path, str]:
        output_root = safe_project_path("output", root=self.project_root)
        output_root.mkdir(parents=True, exist_ok=True)
        output = safe_child_path(output_root, safe_filename(f"{name}{suffix}"))
        return output, output.relative_to(self.project_root).as_posix()
