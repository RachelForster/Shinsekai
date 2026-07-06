from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any

from core.paths import resource_path
from sdk.logging.environment import runtime_environment

from .security import safe_child_path, safe_existing_file_path

MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_LOG_FILES = 200
MAX_DIAGNOSTIC_FILES = 12


def _log_snapshot(path: Path, *, max_bytes: int = MAX_LOG_BYTES) -> dict[str, Any]:
    path = safe_existing_file_path(path, field="log path")
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
        "entries": _parse_jsonl_entries(content),
        "modifiedAt": path.stat().st_mtime,
        "name": path.name,
        "path": path.as_posix(),
        "size": size,
        "truncated": truncated,
    }


def _default_log_snapshot(project_root: Path) -> dict[str, Any]:
    existing = _log_file_candidates(project_root)
    if not existing:
        raise FileNotFoundError("no log file found")
    return _log_snapshot(existing[0])


def _log_file_list(project_root: Path) -> dict[str, Any]:
    files = [_log_file_info(path, project_root) for path in _log_file_candidates(project_root)]
    return {"files": files[:MAX_LOG_FILES]}


def _diagnostic_bundle(project_root: Path) -> dict[str, Any]:
    log_root = project_root / "logs"
    output_dir = log_root / "diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = safe_child_path(output_dir, f"shinsekai-diagnostics-{stamp}.zip")

    files = _log_file_candidates(project_root)[:MAX_DIAGNOSTIC_FILES]
    runtime = runtime_environment(project_root)
    manifest = {
        "createdAt": time.time(),
        "fileCount": len(files),
        "platform": runtime.get("os", "unknown"),
        "python": runtime.get("python_version", "unknown"),
        "runtime": runtime,
        "version": _read_version(project_root),
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in files:
            if output == path:
                continue
            try:
                archive.write(path, _relative_log_path(path, project_root))
            except OSError:
                continue
    return {
        "downloadUrl": f"/api/download?path={output.as_posix()}",
        "path": output.as_posix(),
    }


def _log_file_candidates(project_root: Path) -> list[Path]:
    log_root = project_root / "logs"
    candidates: list[Path] = []
    if log_root.is_dir():
        candidates.extend(log_root.rglob("*.jsonl*"))
        candidates.extend(log_root.rglob("*.log"))
        candidates.extend(log_root.rglob("*.txt"))
    candidates.extend(
        [
            log_root / "main.log",
            log_root / "frontend-bridge.log",
            log_root / "chat.log",
            project_root / "realtimesst.log",
        ]
    )
    seen: set[Path] = set()
    existing: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return sorted(existing, key=_mtime, reverse=True)


def _log_file_info(path: Path, project_root: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "app": path.parent.name if path.parent.name != "logs" else "",
        "modifiedAt": stat.st_mtime,
        "name": path.name,
        "path": path.as_posix(),
        "relativePath": _relative_log_path(path, project_root),
        "size": stat.st_size,
    }


def _relative_log_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.name


def _parse_jsonl_entries(content: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed.setdefault("line", index)
            entries.append(parsed)
    return entries


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _read_version(project_root: Path) -> str:
    for path in (project_root / "VERSION", resource_path("VERSION")):
        text = _read_text(path)
        if text and text != "unknown":
            return text
    return "unknown"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
