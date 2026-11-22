"""Model identifiers and shared defaults used by perception settings and runtime."""

from __future__ import annotations

import os
from pathlib import Path
import sys

DEFAULT_PERCEPTION_MODEL = "Qwen/Qwen3-VL-2B-Instruct"
GGUF_MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M"
DEFAULT_SALIENCE_THRESHOLD = 0.85


def _runtime_python_in_root(root: Path) -> Path | None:
    runtime_dir = root / "runtime"
    if os.name == "nt":
        rel_candidates = ("python.exe", "python3.exe", "Scripts/python.exe")
    else:
        rel_candidates = ("bin/python3", "bin/python", "python3", "python")
    for rel in rel_candidates:
        candidate = runtime_dir / rel
        if candidate.is_file():
            return candidate.resolve()
    return None


def shinsekai_runtime_python_path(
    project_root: str | Path | None = None,
    app_root: str | Path | None = None,
) -> str:
    """Resolve Shinsekai's bundled Python interpreter (`runtime/python.exe`) or active Python."""
    raw_roots: list[str | Path] = []
    if project_root:
        raw_roots.append(project_root)
    if app_root:
        raw_roots.append(app_root)
    for env_key in (
        "SHINSEKAI_APP_ROOT",
        "SHINSEKAI_PROJECT_ROOT",
        "EASYAI_PROJECT_ROOT",
        "SHINSEKAI_SOURCE_ROOT",
    ):
        val = os.environ.get(env_key, "").strip()
        if val:
            raw_roots.append(val)
    if getattr(sys, "frozen", False):
        try:
            raw_roots.append(Path(sys.executable).resolve().parent.parent)
        except OSError:
            pass
    raw_roots.append(Path(__file__).resolve().parents[1])
    raw_roots.append(Path.cwd())

    seen: set[str] = set()
    for raw in raw_roots:
        try:
            root = Path(raw).expanduser().resolve(strict=False)
            norm = os.path.normcase(str(root))
        except (OSError, RuntimeError, ValueError):
            continue
        if norm in seen:
            continue
        seen.add(norm)
        found = _runtime_python_in_root(root)
        if found is not None:
            return str(found)

    if not getattr(sys, "frozen", False) and sys.executable:
        try:
            exe = Path(sys.executable)
            if exe.is_file():
                return str(exe.resolve())
        except OSError:
            pass
    return ""


def default_perception_python_path(
    current_path: str | None = "",
    project_root: str | Path | None = None,
    app_root: str | Path | None = None,
) -> str:
    """Return explicit `current_path` when set, otherwise Shinsekai's own Python interpreter."""
    clean_path = str(current_path or "").strip()
    if clean_path:
        return clean_path
    return shinsekai_runtime_python_path(project_root=project_root, app_root=app_root)

