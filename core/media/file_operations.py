"""Host filesystem operations exposed through higher-level adapters."""

from __future__ import annotations

import mimetypes
import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


FILE_SEARCH_LIMIT = 50


def resolve_local_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.home() / candidate).resolve()


def search_files(pattern: str, directory: str = "~") -> dict[str, Any]:
    base = Path.home() if directory == "~" else resolve_local_path(directory)
    if not base.exists():
        return {"error": f"Directory not found: {base}", "matches": []}

    matches: list[dict[str, Any]] = []
    for candidate in base.rglob(pattern):
        if candidate.is_file():
            matches.append(
                {
                    "name": candidate.name,
                    "path": str(candidate),
                    "size": candidate.stat().st_size,
                    "size_human": _human_size(candidate.stat().st_size),
                }
            )
        if len(matches) >= FILE_SEARCH_LIMIT:
            break
    return {
        "pattern": pattern,
        "directory": str(base),
        "count": len(matches),
        "matches": matches,
    }


def list_directory(path: str = ".") -> dict[str, Any]:
    directory = resolve_local_path(path)
    if not directory.exists():
        return {"error": f"Directory not found: {directory}"}

    items: list[dict[str, Any]] = []
    try:
        for entry in sorted(
            directory.iterdir(),
            key=lambda candidate: (
                not candidate.is_dir(),
                candidate.name.lower(),
            ),
        ):
            info: dict[str, Any] = {
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_file():
                info["size"] = entry.stat().st_size
                info["size_human"] = _human_size(entry.stat().st_size)
            items.append(info)
    except PermissionError:
        return {"error": f"Permission denied: {directory}", "items": []}
    return {"path": str(directory), "count": len(items), "items": items}


def read_text_file(
    path: str,
    *,
    max_chars: int = 5000,
    line_start: int = 0,
    line_end: int = 0,
) -> dict[str, Any]:
    file_path = resolve_local_path(path)
    if not file_path.is_file():
        return {"error": f"File not found: {file_path}"}
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as file:
            content = file.read(max_chars)
        if line_start > 0:
            lines = content.split("\n")
            start = max(0, line_start - 1)
            end = min(len(lines), line_end) if line_end > 0 else len(lines)
            content = "\n".join(lines[start:end])
            if len(content) > max_chars:
                content = content[:max_chars]
        return {
            "path": str(file_path),
            "size": file_path.stat().st_size,
            "content": content,
            "truncated": len(content) >= max_chars,
        }
    except Exception as exc:
        return {"error": str(exc), "path": str(file_path)}


def inspect_path(path: str) -> dict[str, Any]:
    candidate = resolve_local_path(path)
    if not candidate.exists():
        return {"error": f"Path not found: {candidate}"}

    stat = candidate.stat()
    mime, _ = (
        mimetypes.guess_type(str(candidate)) if candidate.is_file() else (None, None)
    )
    return {
        "name": candidate.name,
        "path": str(candidate),
        "type": "directory" if candidate.is_dir() else "file",
        "size": stat.st_size if candidate.is_file() else None,
        "size_human": _human_size(stat.st_size) if candidate.is_file() else None,
        "mime": mime or "unknown",
        "modified": _timestamp_text(stat.st_mtime),
        "created": _timestamp_text(stat.st_ctime),
    }


def open_local_path(path: str) -> dict[str, Any]:
    candidate = resolve_local_path(path)
    if not candidate.exists():
        return {"error": f"Path not found: {candidate}"}
    try:
        if platform.system() == "Windows":
            os.startfile(str(candidate))
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(candidate)], check=True)
        else:
            subprocess.run(["xdg-open", str(candidate)], check=True)
        return {"opened": str(candidate)}
    except Exception as exc:
        return {"error": str(exc), "path": str(candidate)}


def search_file_content(
    keyword: str,
    *,
    directory: str = "~",
    file_pattern: str = "*",
) -> dict[str, Any]:
    base = Path.home() if directory == "~" else resolve_local_path(directory)
    if not base.exists():
        return {"error": f"Directory not found: {base}"}

    matches: list[dict[str, Any]] = []
    for candidate in base.rglob(file_pattern):
        if not candidate.is_file() or candidate.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            with candidate.open("r", encoding="utf-8", errors="replace") as file:
                for line_number, line in enumerate(file, 1):
                    if keyword.lower() in line.lower():
                        matches.append(
                            {
                                "file": str(candidate),
                                "line": line_number,
                                "content": line.strip()[:200],
                            }
                        )
                        if len(matches) >= 30:
                            break
                if len(matches) >= 30:
                    break
        except Exception:
            continue
    return {
        "keyword": keyword,
        "directory": str(base),
        "count": len(matches),
        "matches": matches,
    }


def move_path(source: str, destination: str) -> dict[str, Any]:
    source_path = resolve_local_path(source)
    destination_path = resolve_local_path(destination)
    if not source_path.exists():
        return {"error": f"Source not found: {source_path}"}
    try:
        shutil.move(str(source_path), str(destination_path))
        return {"moved": str(source_path), "to": str(destination_path)}
    except Exception as exc:
        return {
            "error": str(exc),
            "source": str(source_path),
            "dest": str(destination_path),
        }


def copy_file(source: str, destination: str) -> dict[str, Any]:
    source_path = resolve_local_path(source)
    destination_path = resolve_local_path(destination)
    if not source_path.is_file():
        return {"error": f"Source file not found: {source_path}"}
    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(destination_path))
        return {"copied": str(source_path), "to": str(destination_path)}
    except Exception as exc:
        return {"error": str(exc)}


def delete_path(path: str) -> dict[str, Any]:
    candidate = resolve_local_path(path)
    if not candidate.exists():
        return {"error": f"Path not found: {candidate}"}
    try:
        if candidate.is_dir():
            candidate.rmdir()
            return {"deleted": str(candidate), "type": "directory"}
        size = candidate.stat().st_size
        candidate.unlink()
        return {
            "deleted": str(candidate),
            "type": "file",
            "size_human": _human_size(size),
        }
    except Exception as exc:
        return {"error": str(exc), "path": str(candidate)}


def extract_archive(
    archive_path: str,
    *,
    destination: str = "",
) -> dict[str, Any]:
    archive = resolve_local_path(archive_path)
    if not archive.is_file():
        return {"error": f"Archive not found: {archive}"}

    target = (
        resolve_local_path(destination)
        if destination
        else archive.parent / archive.stem
    )
    target.mkdir(parents=True, exist_ok=True)
    try:
        lower_name = archive.name.lower()
        if lower_name.endswith(".zip"):
            with zipfile.ZipFile(archive, "r") as zip_file:
                zip_file.extractall(target)
        elif lower_name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tar_file:
                tar_file.extractall(target)
        elif lower_name.endswith(".tar"):
            with tarfile.open(archive, "r:") as tar_file:
                tar_file.extractall(target)
        else:
            return {"error": f"Unsupported archive format: {archive.name}"}
        extracted = sum(1 for _ in target.rglob("*"))
        return {
            "extracted": str(archive),
            "to": str(target),
            "files_count": extracted,
        }
    except Exception as exc:
        return {"error": str(exc), "archive": str(archive)}


def write_text_file(path: str, content: str) -> dict[str, Any]:
    file_path = resolve_local_path(path)
    existed = file_path.exists()
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {
            "written": str(file_path),
            "size": file_path.stat().st_size,
            "existed": existed,
        }
    except Exception as exc:
        return {"error": str(exc), "path": str(file_path)}


def append_text_file(path: str, content: str) -> dict[str, Any]:
    file_path = resolve_local_path(path)
    existed = file_path.exists()
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as file:
            file.write(content)
        return {
            "appended": str(file_path),
            "size": file_path.stat().st_size,
            "existed": existed,
        }
    except Exception as exc:
        return {"error": str(exc), "path": str(file_path)}


def create_directory(path: str) -> dict[str, Any]:
    directory = resolve_local_path(path)
    if directory.exists():
        return {"error": f"Path already exists: {directory}"}
    try:
        directory.mkdir(parents=True, exist_ok=False)
        return {"created": str(directory)}
    except Exception as exc:
        return {"error": str(exc), "path": str(directory)}


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def _timestamp_text(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
