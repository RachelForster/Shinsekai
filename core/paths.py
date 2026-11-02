from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def source_root() -> Path:
    raw = os.environ.get("SHINSEKAI_SOURCE_ROOT", "").strip()
    if raw:
        return _resolve(Path(raw))
    return _resolve(Path(__file__).parent.parent)


def project_root() -> Path:
    raw = (
        os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip()
        or os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
    )
    if raw:
        return _resolve(Path(raw))
    return _resolve(Path.cwd())


def app_root() -> Path:
    raw = os.environ.get("SHINSEKAI_APP_ROOT", "").strip()
    if raw:
        path = _resolve(Path(raw))
        if path.exists() and path.is_dir():
            return path
    if getattr(sys, "frozen", False):
        return _resolve(Path(sys.executable).parent.parent)
    return source_root()


def resource_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return _resolve(candidate)

    for root in (source_root(), app_root(), project_root()):
        resolved = _resolve(root / candidate)
        if resolved.exists():
            return resolved
    return _resolve(source_root() / candidate)
