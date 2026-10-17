"""Small, persistent dependency records for already validated avatar states.

The host creates these records at mutation/package-validation boundaries. They
are not accepted from external packages as proof of authorization.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from sdk.adapters import ModelAssetAdapter
from sdk.path_utils import is_portable_relative_path, safe_child_path, safe_existing_file_path


MAX_INDEX_BYTES = 128 * 1024
MAX_STATE_BYTES = 1024 * 1024


def index_path(saved: Path) -> Path:
    return saved.with_name(f".{saved.name}.dependencies.json")


def _stamp(path: Path) -> list[int]:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Avatar dependency must be a regular file")
    return [metadata.st_size, metadata.st_mtime_ns]


def _read(path: Path, limit: int) -> bytes:
    _stamp(path)
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Avatar state/dependency index is too large")
    return data


def write_state_index(adapter: ModelAssetAdapter, model: Path, saved: Path, parsed: dict) -> None:
    """Record only adapter-approved files after full state validation."""
    root = model.resolve(strict=True).parent
    saved = safe_existing_file_path(saved, roots=[root])
    files = []
    for dependency in dict.fromkeys(adapter.state_files(model, parsed)):
        checked = safe_existing_file_path(dependency, roots=[root])
        files.append({"path": checked.relative_to(root).as_posix(), "stamp": _stamp(checked)})
    if len(files) > 512:
        raise ValueError("Too many avatar state dependencies")
    record = {
        "version": 1,
        "format": adapter.format_id,
        "model": model.name,
        "model_stamp": _stamp(model),
        "state_sha256": hashlib.sha256(_read(saved, MAX_STATE_BYTES)).hexdigest(),
        "files": files,
    }
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_INDEX_BYTES:
        raise ValueError("Avatar dependency index is too large")
    # States have immutable names and are not referenced by config yet. A
    # failed/partial record must therefore prevent the surrounding commit.
    index_path(saved).write_bytes(encoded)


def indexed_state_files(model: Path, saved: Path, format_id: str) -> tuple[Path, ...]:
    """Authorize through the bounded record, never parse a motion file."""
    record = json.loads(_read(index_path(saved), MAX_INDEX_BYTES))
    if not isinstance(record, dict) or (
        record.get("version") != 1 or record.get("format") != format_id
        or record.get("model") != model.name or record.get("model_stamp") != _stamp(model)
        or record.get("state_sha256") != hashlib.sha256(_read(saved, MAX_STATE_BYTES)).hexdigest()
    ):
        raise ValueError("Avatar dependency index is stale or invalid; save/reimport the state")
    entries = record.get("files")
    if not isinstance(entries, list) or len(entries) > 512:
        raise ValueError("Invalid avatar dependency index")
    files = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Invalid avatar dependency record")
        relative = item["path"]
        if (not is_portable_relative_path(relative)
                or any(char in relative for char in "\\:?#%")
                or any(part in ("", ".", "..") for part in relative.split("/"))):
            raise ValueError("Invalid avatar dependency path")
        checked = safe_child_path(model.parent, relative)
        if item.get("stamp") != _stamp(checked):
            raise ValueError("Avatar dependency changed; save/reimport the state")
        files.append(checked)
    return tuple(dict.fromkeys(files))
