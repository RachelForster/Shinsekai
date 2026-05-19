"""Local filesystem tools — search, read, open, move, extract.

All paths are resolved relative to user home or absolute.
Destructive operations report what happened and do NOT silently delete.
"""

from __future__ import annotations

import os
import shutil
import zipfile
import tarfile
import mimetypes
import subprocess
import platform
import stat
import fnmatch
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator

from sdk.tool_registry import tool

_FILE_SEARCH_LIMIT = 50
_SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "api.yaml",
    "mcp.yaml",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
_SENSITIVE_PROJECT_RELATIVE_DIRS = {
    Path("data/config"),
}


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (Path.home() / p).resolve()


def _safe(name: str, base: Path) -> Path | None:
    """Resolve and check existence; return None if not found."""
    p = _resolve(str(base / name)) if not Path(name).is_absolute() else _resolve(name)
    if not p.exists():
        return None
    return p


def _project_root() -> Path:
    root = os.environ.get("EASYAI_PROJECT_ROOT")
    if root:
        return Path(root).expanduser().resolve()
    return Path.cwd().resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_sensitive_path(path: Path) -> bool:
    p = path.expanduser().resolve()
    parts = p.parts
    lowered_parts = [part.casefold() for part in parts]
    lower_name = p.name.casefold()
    if lower_name in _SENSITIVE_FILE_NAMES:
        return True
    for idx, part in enumerate(lowered_parts):
        if part in {".ssh", ".aws", ".azure", ".gnupg", ".kube"}:
            return True
        if part == ".config" and idx + 1 < len(lowered_parts) and lowered_parts[idx + 1] == "gcloud":
            return True
    root = _project_root()
    for rel_dir in _SENSITIVE_PROJECT_RELATIVE_DIRS:
        sensitive_root = (root / rel_dir).resolve()
        if p == sensitive_root or _is_relative_to(p, sensitive_root):
            return True
    return False


def _sensitive_error(path: Path) -> dict[str, Any]:
    return {
        "error": "Refusing to access sensitive local credentials or configuration path.",
        "path": str(path),
    }


def _iter_files_safe(base: Path, pattern: str) -> Iterator[Path]:
    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if not _is_sensitive_path(root_path / name)
        ]
        for name in files:
            p = root_path / name
            if _is_sensitive_path(p):
                continue
            rel = p.relative_to(base).as_posix()
            if fnmatch.fnmatch(name, pattern) or PurePosixPath(rel).match(pattern):
                yield p


def _safe_archive_relative_path(value: str) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    posix_path = PurePosixPath(raw)
    windows_path = PureWindowsPath(value)
    if (
        not raw
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in posix_path.parts)
    ):
        raise ValueError(f"Unsafe archive member path: {value!r}")
    return Path(*posix_path.parts)


def _safe_archive_destination(dest: Path, relative_path: Path) -> Path:
    root = dest.resolve()
    target = (dest / relative_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Archive member escapes destination: {relative_path}")
    return target


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    for member in zf.infolist():
        relative_path = _safe_archive_relative_path(member.filename)
        _safe_archive_destination(dest, relative_path)
        mode = (member.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ValueError(f"Archive links are not supported: {member.filename!r}")
    zf.extractall(dest)


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    for member in tf.getmembers():
        relative_path = _safe_archive_relative_path(member.name)
        _safe_archive_destination(dest, relative_path)
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not supported: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"Unsupported archive member type: {member.name!r}")
    tf.extractall(dest)


# ── Read-only tools ──────────────────────────────────────────────────


@tool(name="file_search", group="file", risk="medium",
      description="Search for files by name pattern or extension in a directory. "
                  "pattern: glob like '*.py' or 'report*'. dir_path: directory to search (default home). "
                  "Returns up to 50 matches with size and path.")
def file_search(pattern: str, dir_path: str = "~") -> dict[str, Any]:
    base = Path.home() if dir_path == "~" else _resolve(dir_path)
    if not base.exists():
        return {"error": f"Directory not found: {base}", "matches": []}
    if _is_sensitive_path(base):
        return {**_sensitive_error(base), "matches": []}
    matches = []
    for p in _iter_files_safe(base, pattern):
        matches.append({
            "name": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "size_human": _human_size(p.stat().st_size),
        })
        if len(matches) >= _FILE_SEARCH_LIMIT:
            break
    return {"pattern": pattern, "directory": str(base), "count": len(matches), "matches": matches}


@tool(name="file_list_dir", group="file", risk="medium",
      description="List contents of a directory. path: directory path (default current working dir). "
                  "Returns files and subdirectories with sizes.")
def file_list_dir(path: str = ".") -> dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"error": f"Directory not found: {p}"}
    if _is_sensitive_path(p):
        return _sensitive_error(p)
    items = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            info = {"name": entry.name, "type": "dir" if entry.is_dir() else "file"}
            if entry.is_file():
                info["size"] = entry.stat().st_size
                info["size_human"] = _human_size(entry.stat().st_size)
            items.append(info)
    except PermissionError:
        return {"error": f"Permission denied: {p}", "items": []}
    return {"path": str(p), "count": len(items), "items": items}


@tool(name="file_read", group="file", risk="high",
      description="Read a text file and return its content. "
                  "path: file path. max_chars: max characters to read (default 5000, for preview). "
                  "line_start/line_end: optional line range (1-indexed).")
def file_read(path: str, max_chars: int = 5000, line_start: int = 0, line_end: int = 0) -> dict[str, Any]:
    p = _resolve(path)
    if not p.is_file():
        return {"error": f"File not found: {p}"}
    if _is_sensitive_path(p):
        return _sensitive_error(p)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if line_start > 0:
            lines = content.split("\n")
            s = max(0, line_start - 1)
            e = min(len(lines), line_end) if line_end > 0 else len(lines)
            content = "\n".join(lines[s:e])
            if len(content) > max_chars:
                content = content[:max_chars]
        truncated = len(content) >= max_chars
        return {
            "path": str(p),
            "size": p.stat().st_size,
            "content": content,
            "truncated": truncated,
        }
    except Exception as e:
        return {"error": str(e), "path": str(p)}


@tool(name="file_info", group="file", risk="medium",
      description="Get detailed info about a file or directory: size, modified time, type.")
def file_info(path: str) -> dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"error": f"Path not found: {p}"}
    if _is_sensitive_path(p):
        return _sensitive_error(p)
    st = p.stat()
    mime, _ = mimetypes.guess_type(str(p)) if p.is_file() else (None, None)
    return {
        "name": p.name,
        "path": str(p),
        "type": "directory" if p.is_dir() else "file",
        "size": st.st_size if p.is_file() else None,
        "size_human": _human_size(st.st_size) if p.is_file() else None,
        "mime": mime or "unknown",
        "modified": _ts_to_str(st.st_mtime),
        "created": _ts_to_str(st.st_ctime),
    }


@tool(name="file_open", group="file", risk="medium",
      description="Open a file or folder with the default system application.")
def file_open(path: str) -> dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"error": f"Path not found: {p}"}
    if _is_sensitive_path(p):
        return _sensitive_error(p)
    try:
        if platform.system() == "Windows":
            os.startfile(str(p))
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(p)], check=True)
        else:
            subprocess.run(["xdg-open", str(p)], check=True)
        return {"opened": str(p)}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


@tool(name="file_search_content", group="file", risk="high",
      description="Search for text inside files. keyword: text to search. dir_path: directory. "
                  "file_pattern: optional glob filter like '*.py'. Returns matching lines with file paths.")
def file_search_content(keyword: str, dir_path: str = "~", file_pattern: str = "*") -> dict[str, Any]:
    base = Path.home() if dir_path == "~" else _resolve(dir_path)
    if not base.exists():
        return {"error": f"Directory not found: {base}"}
    if _is_sensitive_path(base):
        return _sensitive_error(base)
    results = []
    count = 0
    for p in _iter_files_safe(base, file_pattern):
        if p.stat().st_size > 2 * 1024 * 1024:  # skip >2MB
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if keyword.lower() in line.lower():
                        results.append({
                            "file": str(p),
                            "line": i,
                            "content": line.strip()[:200],
                        })
                        count += 1
                        if count >= 30:
                            break
                if count >= 30:
                    break
        except Exception:
            continue
    return {"keyword": keyword, "directory": str(base), "count": len(results), "matches": results}


# ── Write / destructive tools ────────────────────────────────────────


@tool(name="file_move", group="file", risk="high",
      description="Move or rename a file/directory. source: original path. dest: destination path.")
def file_move(source: str, dest: str) -> dict[str, Any]:
    src = _resolve(source)
    dst = _resolve(dest)
    if not src.exists():
        return {"error": f"Source not found: {src}"}
    try:
        shutil.move(str(src), str(dst))
        return {"moved": str(src), "to": str(dst)}
    except Exception as e:
        return {"error": str(e), "source": str(src), "dest": str(dst)}


@tool(name="file_copy", group="file", risk="medium",
      description="Copy a file. source: original path. dest: destination path.")
def file_copy(source: str, dest: str) -> dict[str, Any]:
    src = _resolve(source)
    dst = _resolve(dest)
    if not src.is_file():
        return {"error": f"Source file not found: {src}"}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return {"copied": str(src), "to": str(dst)}
    except Exception as e:
        return {"error": str(e)}


@tool(name="file_delete", group="file", risk="high",
      description="Delete a file or empty directory. WARNING: this is permanent. Returns what was deleted.")
def file_delete(path: str) -> dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"error": f"Path not found: {p}"}
    try:
        if p.is_dir():
            p.rmdir()
            return {"deleted": str(p), "type": "directory"}
        else:
            p.unlink()
            return {"deleted": str(p), "type": "file", "size_human": _human_size(p.stat().st_size)}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


@tool(name="file_extract", group="file", risk="high",
      description="Extract a zip or tar.gz archive to a directory. "
                  "archive_path: the compressed file. extract_to: target directory (defaults to same folder).")
def file_extract(archive_path: str, extract_to: str = "") -> dict[str, Any]:
    p = _resolve(archive_path)
    if not p.is_file():
        return {"error": f"Archive not found: {p}"}
    dest = _resolve(extract_to) if extract_to else p.parent / p.stem
    dest.mkdir(parents=True, exist_ok=True)
    try:
        name_low = p.name.lower()
        if name_low.endswith(".zip"):
            with zipfile.ZipFile(p, "r") as zf:
                _safe_extract_zip(zf, dest)
        elif name_low.endswith((".tar.gz", ".tgz")):
            with tarfile.open(p, "r:gz") as tf:
                _safe_extract_tar(tf, dest)
        elif name_low.endswith(".tar"):
            with tarfile.open(p, "r:") as tf:
                _safe_extract_tar(tf, dest)
        else:
            return {"error": f"Unsupported archive format: {p.name}"}
        # Count extracted files
        extracted = sum(1 for _ in dest.rglob("*"))
        return {"extracted": str(p), "to": str(dest), "files_count": extracted}
    except Exception as e:
        return {"error": str(e), "archive": str(p)}


@tool(name="file_write", group="file", risk="high",
      description="Create a new file or overwrite an existing file with text content. "
                  "path: file path. content: text content to write.")
def file_write(path: str, content: str) -> dict[str, Any]:
    p = _resolve(path)
    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return {"written": str(p), "size": p.stat().st_size, "existed": existed}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


@tool(name="file_append", group="file", risk="medium",
      description="Append text to an existing file. Creates the file if it doesn't exist. "
                  "path: file path. content: text to append.")
def file_append(path: str, content: str) -> dict[str, Any]:
    p = _resolve(path)
    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return {"appended": str(p), "size": p.stat().st_size, "existed": existed}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


@tool(name="file_mkdir", group="file", risk="medium",
      description="Create a new directory (and any missing parent directories). "
                  "path: directory path to create.")
def file_mkdir(path: str) -> dict[str, Any]:
    p = _resolve(path)
    if p.exists():
        return {"error": f"Path already exists: {p}"}
    try:
        p.mkdir(parents=True, exist_ok=False)
        return {"created": str(p)}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


# ── Helpers ───────────────────────────────────────────────────────────


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _ts_to_str(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
