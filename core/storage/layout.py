"""Single source of truth for resolving project storage directories and files."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from sdk.path_utils import (
    is_portable_relative_path,
    reject_control_chars,
    resolve_regular_path,
    safe_child_path,
)


def _safe_relative_child(
    base: Path,
    relative_path: str | os.PathLike[str],
    *,
    field: str,
) -> Path:
    raw = reject_control_chars(os.fspath(relative_path), field=field)
    if not is_portable_relative_path(raw):
        raise PermissionError(f"{field} must be a portable relative path inside {base.name}")
    resolved = safe_child_path(base, raw)
    if resolved == safe_child_path(base, "."):
        raise ValueError(f"{field} must point to a child inside {base.name}")
    return resolved


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """Resolve all application storage directories under one explicit project root."""

    project_root: Path

    def __init__(self, project_root: str | os.PathLike[str]) -> None:
        normalized = resolve_regular_path(os.fspath(project_root))
        object.__setattr__(self, "project_root", normalized)

    @classmethod
    def from_env(
        cls,
        project_root: str | os.PathLike[str] | None = None,
    ) -> StorageLayout:
        raw = os.fspath(project_root).strip() if project_root is not None else ""
        if not raw:
            raw = (
                os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip()
                or os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
            )
        return cls(raw or Path.cwd())

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def chat_history_dir(self) -> Path:
        return self.data_dir / "chat_history"

    @property
    def legacy_backup_dir(self) -> Path:
        return self.config_dir / "legacy_backup"

    @property
    def main_db_path(self) -> Path:
        return self.data_dir / "shinsekai.db"

    @property
    def migration_lock_path(self) -> Path:
        return self.data_dir / ".storage_migration.lock"

    def config_file(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.config_dir, relative_path, field="config path")

    def state_file(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.state_dir, relative_path, field="state path")

    def cache_file(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.cache_dir, relative_path, field="cache path")

    def model_dir(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.models_dir, relative_path, field="model path")

    def runtime_subdir(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.runtime_dir, relative_path, field="runtime path")

    def db_file(self, relative_path: str | os.PathLike[str]) -> Path:
        return _safe_relative_child(self.data_dir, relative_path, field="database path")

    def media_dir(self, category: str, prefix: str = "") -> Path:
        category_dir = _safe_relative_child(self.data_dir, category, field="media category")
        if not str(prefix or "").strip():
            return category_dir
        return _safe_relative_child(category_dir, prefix, field="media prefix")


__all__ = ["StorageLayout"]
