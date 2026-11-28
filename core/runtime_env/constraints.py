"""Host core runtime version constraints for secondary pip installations."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile

from core.runtime_env.pip_index import strip_inline_requirement_comment
from core.runtime_env.requirements import canonical_distribution_name

try:
    from packaging.requirements import InvalidRequirement, Requirement
except Exception:  # pragma: no cover - fallback for minimal embedded runtimes.
    InvalidRequirement = ValueError  # type: ignore[assignment]
    Requirement = None  # type: ignore[assignment]

CORE_REQUIREMENTS_FILENAME = "requirements-runtime-core.txt"
HOST_REQUIREMENTS_FILENAMES = frozenset(
    {CORE_REQUIREMENTS_FILENAME, "requirements.txt"}
)
_TORCH_PACKAGES = frozenset({"torch", "torchvision", "torchaudio"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_host_roots() -> tuple[Path, ...]:
    candidates: list[Path] = [_repo_root()]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve(strict=False).parent)
    resolved: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        norm = root.resolve(strict=False)
        if norm not in seen:
            seen.add(norm)
            resolved.append(norm)
    return tuple(resolved)


def host_core_requirements_path(project_root: Path | None = None) -> Path | None:
    """Return the host ``requirements-runtime-core.txt`` if present."""
    search_roots = (
        (project_root.resolve(strict=False), *_default_host_roots())
        if project_root is not None
        else _default_host_roots()
    )
    for root in search_roots:
        candidate = root / CORE_REQUIREMENTS_FILENAME
        if candidate.is_file():
            return candidate
    return None


def is_host_requirements_file(
    req_path: Path,
    project_root: Path | None = None,
) -> bool:
    """Return ``True`` only for root host requirement manifests, never plugin manifests."""
    resolved = req_path.resolve(strict=False)
    if resolved.name.lower() not in HOST_REQUIREMENTS_FILENAMES:
        return False
    roots: list[Path] = (
        [project_root.resolve(strict=False)]
        if project_root is not None
        else list(_default_host_roots())
    )
    if project_root is None:
        core_path = host_core_requirements_path()
        if core_path is not None:
            roots.append(core_path.resolve(strict=False).parent)
    return resolved.parent in roots


def core_runtime_constraint_lines(
    project_root: Path | None = None,
    *,
    exclude_names: Iterable[str] = (),
) -> list[str]:
    """Build pip ``-c`` constraint lines from ``requirements-runtime-core.txt``."""
    core_path = host_core_requirements_path(project_root)
    if core_path is None or Requirement is None:
        return []
    try:
        raw_lines = core_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    excluded = _TORCH_PACKAGES | {
        canonical_distribution_name(name) for name in exclude_names if name
    }
    constraints: list[str] = []
    seen: set[str] = set()
    for raw_line in raw_lines:
        cleaned = strip_inline_requirement_comment(raw_line).strip()
        if not cleaned or cleaned.startswith("-"):
            continue
        try:
            req = Requirement(cleaned)
        except InvalidRequirement:
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        if canonical_distribution_name(req.name) in excluded:
            continue
        if not req.specifier:
            continue
        constraint = f"{req.name}{req.specifier}"
        if constraint not in seen:
            seen.add(constraint)
            constraints.append(constraint)
    return constraints


@contextmanager
def temporary_core_constraints_file(
    project_root: Path | None = None,
    *,
    exclude_names: Iterable[str] = (),
) -> Iterator[Path | None]:
    """Yield a temporary pip ``-c`` constraints file when core pins exist."""
    lines = core_runtime_constraint_lines(
        project_root,
        exclude_names=exclude_names,
    )
    if not lines:
        yield None
        return

    fd, temp_path_str = tempfile.mkstemp(
        prefix="shinsekai_core_constraints_",
        suffix=".txt",
    )
    path = Path(temp_path_str)
    try:
        os.close(fd)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yield path
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
