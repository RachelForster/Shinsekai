from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_LOG_BYTES = 4 * 1024 * 1024


def _log_snapshot(path: Path, *, max_bytes: int = MAX_LOG_BYTES) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path.as_posix())
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as file:
        if truncated:
            file.seek(max(0, size - max_bytes))
        raw = file.read(max_bytes)
    content = raw.decode("utf-8", errors="replace")
    if truncated:
        content = "[Log truncated: showing the latest entries]\n" + content
    return {
        "content": content,
        "modifiedAt": path.stat().st_mtime,
        "name": path.name,
        "path": path.as_posix(),
        "size": size,
        "truncated": truncated,
    }


def _default_log_snapshot(project_root: Path) -> dict[str, Any]:
    log_root = project_root / "logs"
    jsonl_logs = []
    if log_root.is_dir():
        jsonl_logs = sorted(log_root.rglob("*.jsonl*"), key=_mtime, reverse=True)
    candidates = [
        *jsonl_logs,
        log_root / "main.log",
        log_root / "frontend-bridge.log",
        log_root / "chat.log",
        project_root / "realtimesst.log",
    ]
    existing = [path for path in candidates if path.is_file()]
    if not existing and log_root.is_dir():
        existing = sorted(
            [path for pattern in ("*.jsonl*", "*.log") for path in log_root.rglob(pattern) if path.is_file()],
            key=_mtime,
            reverse=True,
        )
    if not existing:
        raise FileNotFoundError("no log file found")
    return _log_snapshot(existing[0])


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
