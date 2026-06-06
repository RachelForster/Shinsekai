"""Install official registry package archives, typically hosted on R2."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core.plugins.registry_catalog import RegistryPluginRecord
from core.plugins.registry_download import sanitize_plugins_directory_name

_PACKAGE_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+plugin-package; https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024


class PluginPackageError(Exception):
    """Base error for official registry package installs."""


class PluginPackageNetworkError(PluginPackageError):
    """A transient package download failure where GitHub fallback is allowed."""


class PluginPackageNonFallbackError(PluginPackageError, ValueError):
    """An official package failure that must not fall back to unverified sources."""


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("SHINSEKAI_PLUGIN_PACKAGE_HOSTS", "").strip()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _max_bytes() -> int:
    raw = os.environ.get("SHINSEKAI_PLUGIN_PACKAGE_MAX_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_BYTES
    return value if value > 0 else _DEFAULT_MAX_BYTES


def _validate_package_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PluginPackageNonFallbackError("plugin package URL must use http or https")
    if not parsed.netloc:
        raise PluginPackageNonFallbackError("plugin package URL is missing a host")
    allowed = _allowed_hosts()
    if allowed and parsed.hostname and parsed.hostname.lower() not in allowed:
        raise PluginPackageNonFallbackError(f"plugin package host is not allowed: {parsed.hostname}")


def _read_url(url: str, *, timeout_sec: float = 180.0, max_bytes: int | None = None) -> bytes:
    limit = max_bytes if max_bytes is not None else _max_bytes()
    req = Request(url, headers={"User-Agent": _PACKAGE_USER_AGENT})
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > limit:
                raise PluginPackageNonFallbackError(f"plugin package is too large: {content_length} bytes")
            chunks: list[bytes] = []
            total = 0
            while True:
                block = resp.read(65536)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise PluginPackageNonFallbackError(f"plugin package is too large: {total} bytes")
                chunks.append(block)
    except PluginPackageError:
        raise
    except Exception as exc:
        raise PluginPackageNetworkError(f"plugin package download failed: {exc}") from exc
    return b"".join(chunks)


def _verify_package(body: bytes, *, expected_sha256: str, expected_size: int | None) -> None:
    if expected_size is not None and len(body) != expected_size:
        raise PluginPackageNonFallbackError(f"plugin package size mismatch: expected {expected_size}, got {len(body)}")
    if not expected_sha256:
        raise PluginPackageNonFallbackError("official plugin package is missing sha256")
    actual = hashlib.sha256(body).hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise PluginPackageNonFallbackError("plugin package checksum mismatch")


def _safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    infos = [info for info in zf.infolist() if info.filename and not info.is_dir()]
    if not infos:
        raise PluginPackageNonFallbackError("plugin package is empty")

    roots: set[str] = set()
    parsed: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for info in infos:
        path = PurePosixPath(info.filename)
        parts = tuple(part for part in path.parts if part not in {"", "."})
        if not parts or path.is_absolute() or any(part == ".." for part in parts):
            raise PluginPackageNonFallbackError(f"unsafe plugin package path: {info.filename}")
        roots.add(parts[0])
        parsed.append((info, parts))

    strip_root = len(roots) == 1
    safe: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for info, parts in parsed:
        rel = parts[1:] if strip_root else parts
        if rel:
            safe.append((info, rel))
    if not safe:
        raise PluginPackageNonFallbackError("plugin package has no files after root normalization")
    return safe


def _extract_safe_zip(body: bytes) -> Path:
    tmp_root = Path(tempfile.mkdtemp(prefix="shinsekai-plugin-package-"))
    zip_path = tmp_root / "package.zip"
    zip_path.write_bytes(body)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = _safe_members(zf)
            extract_root = (tmp_root / "extract").resolve(strict=False)
            for info, rel_parts in members:
                destination = (extract_root / Path(*rel_parts)).resolve(strict=False)
                if extract_root != destination and extract_root not in destination.parents:
                    raise PluginPackageNonFallbackError(f"unsafe plugin package path: {info.filename}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise PluginPackageNonFallbackError("plugin package is not a valid zip") from exc
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    return tmp_root / "extract"


def registry_package_target(record: RegistryPluginRecord, *, plugins_parent: Path | None = None) -> Path:
    folder_name = sanitize_plugins_directory_name(record.name or record.id or record.display_name)
    if not folder_name:
        raise PluginPackageNonFallbackError("registry record has no safe plugin folder name")
    parent = Path(plugins_parent) if plugins_parent is not None else Path("plugins")
    return parent / folder_name


def _replace_directory(extracted: Path, target: Path) -> None:
    target = target.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.exists():
        backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
        target.rename(backup)
    try:
        shutil.move(str(extracted), str(target))
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup is not None and backup.exists():
            backup.rename(target)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def install_registry_package_under_plugins(
    record: RegistryPluginRecord,
    *,
    plugins_parent: Path | None = None,
    overwrite: bool = False,
    timeout_sec: float = 180.0,
) -> Path:
    """Download, verify, and extract an official registry package under ``plugins/``."""
    package_url = (record.package_url or record.download_url or "").strip()
    if not package_url:
        raise PluginPackageNonFallbackError("registry record has no package URL")
    _validate_package_url(package_url)

    target = registry_package_target(record, plugins_parent=plugins_parent)
    if target.is_dir() and not overwrite:
        return target.resolve(strict=False)

    body = _read_url(package_url, timeout_sec=timeout_sec, max_bytes=_max_bytes())
    _verify_package(
        body,
        expected_sha256=(record.package_sha256 or record.sha256 or "").strip(),
        expected_size=record.package_size if record.package_size is not None else record.size,
    )
    extracted = _extract_safe_zip(body)
    tmp_root = extracted.parent
    try:
        _replace_directory(extracted, target)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return target.resolve(strict=False)
