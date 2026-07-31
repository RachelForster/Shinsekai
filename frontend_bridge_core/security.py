from __future__ import annotations

import ipaddress
import os
import re
import stat
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from sdk.path_contract import (
    path_is_link_or_reparse_point,
    project_root,
    require_symlink_free_absolute_path,
    resolve_project_read_path,
    safe_path_component,
    safe_path_component_with_suffix,
)

from .path_utils import (
    is_absolute_path_text,
    is_windows_drive_relative_path_text,
    resolved_path_is_within,
    strip_windows_verbatim_prefix,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\ud800-\udfff]")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_SAFE_COMMAND_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_SAFE_SEARCH_RE = re.compile(r"^[\w\s.,:;!?()\[\]'\"+&/@#-]{1,200}$", re.UNICODE)


def portable_path_text(value: str | os.PathLike[str], *, field: str) -> str:
    """Validate path text without silently changing the caller's filename."""

    raw = os.fspath(value)
    if not raw or raw != raw.strip() or _CONTROL_CHARS_RE.search(raw):
        raise ValueError(
            f"{field} is required and must not contain surrounding whitespace "
            "or control characters"
        )
    return raw


def reject_control_chars(value: str, *, field: str = "value") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if _CONTROL_CHARS_RE.search(text):
        raise ValueError(f"{field} contains control characters")
    return text


def safe_header_value(value: str) -> str:
    return reject_control_chars(value, field="header")


def safe_content_disposition(filename: str) -> str:
    safe_name = Path(reject_control_chars(filename, field="filename")).name
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name).strip("._") or "download"
    encoded = quote(safe_name, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def download_url(path: str | os.PathLike[str]) -> str:
    """Build one bridge download URL without changing the path identity."""

    raw = portable_path_text(path, field="download path")
    return f"/api/download?path={quote(raw, safe='')}"


def _safe_host(host: str) -> str:
    raw = portable_path_text(host, field="host").lower()
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        pass
    host = raw.rstrip(".")
    if not host or not _HOST_RE.fullmatch(host):
        raise ValueError("URL host is invalid")
    return host


def host_matches(host: str, allowed_hosts: set[str]) -> bool:
    safe_host = _safe_host(host)
    normalized_allowed = {_safe_host(item) for item in allowed_hosts}
    return any(safe_host == allowed or safe_host.endswith(f".{allowed}") for allowed in normalized_allowed)


def validated_http_url(
    raw_url: str,
    *,
    allowed_hosts: set[str] | None = None,
    allow_localhost: bool = False,
    allow_private_hosts: bool = False,
    field: str = "url",
) -> str:
    url = str(raw_url or "")
    if (
        not url
        or url != url.strip()
        or _CONTROL_CHARS_RE.search(url)
        or "\\" in url
    ):
        raise ValueError(
            f"{field} is required and must not contain surrounding whitespace, "
            "control characters, or backslashes"
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field} must use http or https")
    if not parsed.hostname:
        raise ValueError(f"{field} must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} must not include credentials")
    if parsed.fragment:
        raise ValueError(f"{field} must not include a fragment")

    host = _safe_host(parsed.hostname)
    if allowed_hosts is not None and not host_matches(host, allowed_hosts):
        raise ValueError(f"{field} host is not allowed")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            if not allow_localhost:
                raise ValueError(f"{field} loopback IP is not allowed")
        elif ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"{field} special-use IP is not allowed")
        elif ip.is_private and not allow_private_hosts:
            raise ValueError(f"{field} private IP is not allowed")
    elif host in {"localhost", "localhost.localdomain"} and not allow_localhost:
        raise ValueError(f"{field} localhost is not allowed")

    netloc = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "", parsed.query or "", ""))


def validated_origin(raw_origin: str, *, allowed_ports: set[int]) -> str:
    origin = validated_http_url(
        raw_origin,
        allow_localhost=True,
        allow_private_hosts=True,
        field="origin",
    )
    parsed = urlsplit(origin)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("origin must not include path, query, or fragment")
    if parsed.port not in allowed_ports:
        raise ValueError("origin port is not allowed")
    return safe_header_value(origin)


def _comparison_path(path: Path) -> str:
    value = str(path)
    if os.name == "nt":
        value = strip_windows_verbatim_prefix(value)
        return os.path.normcase(os.path.normpath(value))
    return os.path.normpath(value)


def _ensure_path_within_base(base: Path, resolved: Path, *, message: str) -> Path:
    base_value = _comparison_path(base)
    resolved_value = _comparison_path(resolved)
    try:
        common = os.path.commonpath([base_value, resolved_value])
    except ValueError as exc:
        raise PermissionError(f"{message} or uses a different drive") from exc
    if common != base_value:
        raise PermissionError(message)
    # Comparison keys must never replace the native I/O path. In particular,
    # keep a verbatim prefix when the caller supplied or inherited one.
    return resolved


def safe_project_path(raw_path: str | os.PathLike[str], root: Path | None = None) -> Path:
    from sdk.path_contract import resolve_managed_project_path

    base = project_root() if root is None else root
    return resolve_managed_project_path(
        portable_path_text(raw_path, field="path"),
        root=base,
    )


def safe_child_path(base: Path, raw_path: str | os.PathLike[str]) -> Path:
    root = require_symlink_free_absolute_path(base, field="base path")
    raw = portable_path_text(raw_path, field="path")
    if (
        is_absolute_path_text(raw)
        or is_windows_drive_relative_path_text(raw)
        or "\\" in raw
    ):
        raise ValueError("child path must be a portable relative path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("child path must use exact relative components")
    for part in parts:
        safe_path_component(part, field="child path component")
    candidate = root.joinpath(*parts)
    if not resolved_path_is_within(candidate, root):
        raise PermissionError("path is outside base path")
    return require_symlink_free_absolute_path(candidate, field="child path")


def safe_existing_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
    root: Path | None = None,
) -> Path:
    raw = portable_path_text(raw_path, field=field)
    path = resolve_project_read_path(
        raw,
        root=project_root() if root is None else root,
    )
    try:
        path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(path) from None
    return require_symlink_free_absolute_path(path, field=field)


def safe_existing_file_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
    root: Path | None = None,
) -> Path:
    path = safe_existing_path(raw_path, field=field, root=root)
    metadata = path.lstat()
    if path_is_link_or_reparse_point(path) or not stat.S_ISREG(metadata.st_mode):
        raise FileNotFoundError(path)
    return path


def safe_existing_dir_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
    root: Path | None = None,
) -> Path:
    path = safe_existing_path(raw_path, field=field, root=root)
    metadata = path.lstat()
    if path_is_link_or_reparse_point(path) or not stat.S_ISDIR(metadata.st_mode):
        raise NotADirectoryError(path)
    return path


def safe_filename(raw_name: str, *, default_suffix: str = "") -> str:
    raw = portable_path_text(raw_name, field="filename")
    if "/" in raw or "\\" in raw:
        raise ValueError("filename must not contain path separators")
    name = Path(raw).name
    if not name or name in {".", ".."}:
        raise ValueError("filename is invalid")
    if name != raw:
        raise ValueError("filename must not contain path separators")
    if default_suffix:
        if name.casefold().endswith(default_suffix.casefold()):
            name = f"{name[:-len(default_suffix)]}{default_suffix}"
        else:
            return safe_path_component_with_suffix(
                name,
                default_suffix,
                field="filename",
            )
    return safe_path_component(name, field="filename")


def safe_executable(raw_executable: str, *, default: str) -> str:
    raw = str(raw_executable or "")
    if not raw:
        raw = default
    if raw != raw.strip() or _CONTROL_CHARS_RE.search(raw):
        raise ValueError(
            "executable must not contain surrounding whitespace or control characters"
        )
    if "/" not in raw and "\\" not in raw:
        if not _SAFE_COMMAND_RE.fullmatch(raw):
            raise ValueError("executable name is invalid")
        return raw
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("executable path must be absolute")
    path = resolve_project_read_path(raw, root=project_root())
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def safe_search_query(query: str) -> str:
    text = reject_control_chars(query, field="search query")
    if not _SAFE_SEARCH_RE.fullmatch(text):
        raise ValueError("search query contains unsupported characters")
    return text
