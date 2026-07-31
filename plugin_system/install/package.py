"""Install official registry package archives, typically hosted on R2."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import uuid
import zipfile
from contextlib import contextmanager
from collections.abc import Iterator
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sdk.archive_paths import UnsafeArchiveError, extract_zip_safely
from sdk.file_transactions import (
    copy_directory_without_links,
    create_private_temporary_directory,
    private_sibling_path,
    remove_directory_without_links,
    rename_path_without_overwrite,
    replace_directory_transactionally,
)
from plugin_system.registry.catalog import RegistryPluginRecord
from plugin_system.registry.download import portable_plugin_target, sanitize_plugins_directory_name
from sdk.path_contract import (
    path_is_link_or_reparse_point,
    project_root,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_project_output_path,
)

_PACKAGE_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+plugin-package; https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
_PACKAGE_INSTALL_LOCK = threading.RLock()
_UNSPECIFIED_IDENTITY = object()


@contextmanager
def registry_package_install_transaction() -> Iterator[None]:
    """Serialize publication, dependency validation, and caller rollback."""

    with _PACKAGE_INSTALL_LOCK:
        yield


class PluginPackageError(Exception):
    """Base error for official registry package installs."""

    code = "plugin_package_error"
    fallback_allowed = False
    user_message = "插件包体安装失败。"

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        fallback_allowed: bool | None = None,
        status_code: int | None = None,
        user_message: str | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if fallback_allowed is not None:
            self.fallback_allowed = fallback_allowed
        if user_message is not None:
            self.user_message = user_message
        self.status_code = status_code


class PluginPackageNetworkError(PluginPackageError):
    """A transient package download failure where GitHub fallback is allowed."""

    code = "package_network_error"
    fallback_allowed = True
    user_message = "官方包体暂时无法访问，正在自动尝试 GitHub 源码安装。"


class PluginPackageNonFallbackError(PluginPackageError, ValueError):
    """An official package failure that must not fall back to unverified sources."""

    fallback_allowed = False


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
        raise PluginPackageNonFallbackError(
            "plugin package URL must use http or https",
            code="package_invalid_url",
            user_message="官方包体地址无效，请等待维护者修复索引。",
        )
    if not parsed.netloc:
        raise PluginPackageNonFallbackError(
            "plugin package URL is missing a host",
            code="package_invalid_url",
            user_message="官方包体地址无效，请等待维护者修复索引。",
        )
    allowed = _allowed_hosts()
    if allowed and parsed.hostname and parsed.hostname.lower() not in allowed:
        raise PluginPackageNonFallbackError(
            f"plugin package host is not allowed: {parsed.hostname}",
            code="package_host_not_allowed",
            user_message="官方包体来源不在允许列表内，已阻止安装。",
)


def _cleanup_private_tree(
    path: Path,
    *,
    expected_identity: os.stat_result,
) -> None:
    try:
        remove_directory_without_links(
            path,
            expected_identity=expected_identity,
        )
    except (FileNotFoundError, OSError, ValueError):
        pass


def _is_transient_network_error(exc: BaseException) -> bool:
    """Return True for failures where GitHub source fallback is acceptable."""
    if isinstance(exc, HTTPError):
        return False
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            return _is_transient_network_error(reason)
        text = str(reason).lower()
        return any(
            marker in text
            for marker in (
                "connection refused",
                "connection reset",
                "network is unreachable",
                "temporary failure",
                "timed out",
                "timeout",
                "name or service not known",
                "nodename nor servname provided",
                "getaddrinfo failed",
            )
        )
    return isinstance(
        exc,
        (
            ConnectionError,
            IncompleteRead,
            TimeoutError,
            socket.gaierror,
            socket.timeout,
        ),
    )


def _read_url(
    url: str,
    *,
    timeout_sec: float = 180.0,
    max_bytes: int | None = None,
    download_id: str = "",
) -> bytes:
    limit = max_bytes if max_bytes is not None else _max_bytes()
    request_id = download_id.strip() or str(uuid.uuid4())
    req = Request(
        url,
        headers={
            "User-Agent": _PACKAGE_USER_AGENT,
            "X-Shinsekai-Download-Id": request_id,
        },
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > limit:
                raise PluginPackageNonFallbackError(
                    f"plugin package is too large: {content_length} bytes",
                    code="package_too_large",
                    user_message="官方包体超过大小限制，已阻止安装。",
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                block = resp.read(65536)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise PluginPackageNonFallbackError(
                        f"plugin package is too large: {total} bytes",
                        code="package_too_large",
                        user_message="官方包体超过大小限制，已阻止安装。",
                    )
                chunks.append(block)
    except PluginPackageError:
        raise
    except HTTPError as exc:
        raise PluginPackageNonFallbackError(
            f"plugin package HTTP error: {exc.code}",
            code="package_http_error",
            status_code=exc.code,
            user_message="官方包体不可用，请等待维护者修复索引或包体。",
        ) from exc
    except URLError as exc:
        if _is_transient_network_error(exc):
            raise PluginPackageNetworkError(f"plugin package download failed: {exc}") from exc
        raise PluginPackageNonFallbackError(
            f"plugin package URL error: {exc}",
            code="package_url_error",
            user_message="官方包体地址访问失败，请等待维护者修复索引或包体。",
        ) from exc
    except Exception as exc:
        if _is_transient_network_error(exc):
            raise PluginPackageNetworkError(f"plugin package download failed: {exc}") from exc
        raise PluginPackageNonFallbackError(
            f"plugin package download failed: {exc}",
            code="package_download_error",
            user_message="官方包体下载失败，请等待维护者修复索引或包体。",
        ) from exc
    return b"".join(chunks)


def _verify_package(body: bytes, *, expected_sha256: str, expected_size: int | None) -> None:
    if expected_size is not None and len(body) != expected_size:
        raise PluginPackageNonFallbackError(
            f"plugin package size mismatch: expected {expected_size}, got {len(body)}",
            code="package_size_mismatch",
            user_message="包体校验未通过，已阻止安装。",
        )
    if not expected_sha256:
        raise PluginPackageNonFallbackError(
            "official plugin package is missing sha256",
            code="package_missing_sha256",
            user_message="官方包体缺少校验信息，已阻止安装。",
        )
    actual = hashlib.sha256(body).hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise PluginPackageNonFallbackError(
            "plugin package checksum mismatch",
            code="package_checksum_mismatch",
            user_message="包体校验未通过，已阻止安装。",
        )


def _extract_safe_zip(body: bytes) -> tuple[Path, os.stat_result, Path]:
    tmp_root, tmp_root_identity = create_private_temporary_directory(
        prefix="shinsekai-plugin-package-",
    )
    try:
        # The package was already downloaded and verified as one in-memory
        # byte string.  Decode that exact object instead of publishing a
        # temporary pathname that could be replaced before ZipFile reopens it.
        with zipfile.ZipFile(BytesIO(body)) as zf:
            raw_root = tmp_root / "raw"
            extraction = extract_zip_safely(zf, raw_root)
        extract_root = tmp_root / "extract"
        nested_root = raw_root / extraction.top_level if extraction.top_level else None
        if nested_root is not None and nested_root.is_dir():
            raw_root_identity = raw_root.lstat()
            rename_path_without_overwrite(
                nested_root,
                extract_root,
                expected_identity=nested_root.lstat(),
            )
            _cleanup_private_tree(
                raw_root,
                expected_identity=raw_root_identity,
            )
        else:
            rename_path_without_overwrite(
                raw_root,
                extract_root,
                expected_identity=raw_root.lstat(),
            )
    except UnsafeArchiveError as exc:
        _cleanup_private_tree(
            tmp_root,
            expected_identity=tmp_root_identity,
        )
        raise PluginPackageNonFallbackError(
            f"unsafe plugin package path: {exc}",
            code="package_unsafe_path",
            user_message="包体校验未通过，已阻止安装。",
        ) from exc
    except zipfile.BadZipFile as exc:
        _cleanup_private_tree(
            tmp_root,
            expected_identity=tmp_root_identity,
        )
        raise PluginPackageNonFallbackError(
            "plugin package is not a valid zip",
            code="package_bad_zip",
            user_message="包体校验未通过，已阻止安装。",
        ) from exc
    except Exception:
        _cleanup_private_tree(
            tmp_root,
            expected_identity=tmp_root_identity,
        )
        raise
    return tmp_root, tmp_root_identity, tmp_root / "extract"


def registry_package_target(
    record: RegistryPluginRecord,
    *,
    plugins_parent: Path | None = None,
    root: str | Path | None = None,
) -> Path:
    folder_name = sanitize_plugins_directory_name(record.name or record.id or record.display_name)
    if not folder_name:
        raise PluginPackageNonFallbackError(
            "registry record has no safe plugin folder name",
            code="package_invalid_name",
            user_message="插件包体缺少安全的安装目录名，请等待维护者修复索引。",
        )
    active_root = project_root() if root is None else root
    configured_parent = (
        plugins_parent
        if plugins_parent is not None
        else Path(active_root) / "plugins"
    )
    unresolved_parent = Path(configured_parent)
    if not unresolved_parent.is_absolute():
        raise ValueError("plugins_parent must be absolute")
    lexical_parent = require_symlink_free_absolute_path(
        unresolved_parent,
        field="plugins directory",
    )
    parent = resolve_project_output_path(
        configured_parent,
        root=active_root,
    )
    try:
        return portable_plugin_target(parent, folder_name)
    except FileExistsError as exc:
        raise PluginPackageNonFallbackError(
            str(exc),
            code="package_name_collision",
            user_message="插件目录名与现有目录在其他系统上会发生冲突，已阻止安装。",
        ) from exc


def _replace_directory(
    extracted: Path,
    target: Path,
    *,
    overwrite: bool = True,
    expected_target_identity: os.stat_result | None | object = (
        _UNSPECIFIED_IDENTITY
    ),
    root: str | Path | None = None,
) -> None:
    if path_is_link_or_reparse_point(target):
        raise PluginPackageNonFallbackError(
            "plugin target must not be a symbolic link",
            code="package_unsafe_target",
            user_message="插件安装目录不安全，已阻止覆盖。",
        )
    try:
        target_parent = require_symlink_free_absolute_path(
            target.parent,
            field="plugin target parent",
        )
        target_parent = resolve_project_output_path(
            target_parent,
            root=project_root() if root is None else root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginPackageNonFallbackError(
            f"plugin target parent is unsafe: {exc}",
            code="package_unsafe_target",
            user_message="插件安装目录不安全，已阻止覆盖。",
        ) from exc
    target = target_parent / target.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target_parent = require_directory_without_links(
        target.parent,
        field="plugin target parent",
    )
    target = target_parent / target.name
    if target.exists() and not target.is_dir():
        raise PluginPackageNonFallbackError(
            "plugin target is not a directory",
            code="package_unsafe_target",
            user_message="插件安装目标不是目录，已阻止覆盖。",
        )
    if target.exists() and not overwrite:
        raise FileExistsError(f"plugin target already exists: {target.name}")
    try:
        target_identity = target.lstat()
    except FileNotFoundError:
        target_identity = None
    if expected_target_identity is not _UNSPECIFIED_IDENTITY:
        if expected_target_identity is None:
            if target_identity is not None:
                raise FileExistsError(
                    f"plugin target appeared before publication: {target.name}"
                )
        elif (
            target_identity is None
            or not os.path.samestat(expected_target_identity, target_identity)
        ):
            raise PermissionError(
                f"plugin target identity changed before publication: {target}"
            )
    staging = private_sibling_path(
        target,
        f".install-{uuid.uuid4().hex}",
        field="plugin installation staging directory",
    )
    staging_identity: os.stat_result | None = None
    try:
        # ``tempfile`` and the selected project can live on different Windows
        # volumes.  Build a complete sibling first so publication never
        # degrades into a partial cross-volume ``shutil.move`` copy.
        staging = copy_directory_without_links(extracted, staging)
        staging_identity = staging.lstat()
        replace_directory_transactionally(
            staging,
            target,
            overwrite=overwrite,
            expected_staging_identity=staging_identity,
            expected_destination_identity=target_identity,
        )
    finally:
        if staging_identity is not None:
            try:
                remove_directory_without_links(
                    staging,
                    expected_identity=staging_identity,
                )
            except (OSError, ValueError):
                pass


def install_registry_package_under_plugins(
    record: RegistryPluginRecord,
    *,
    plugins_parent: Path | None = None,
    overwrite: bool = False,
    timeout_sec: float = 180.0,
    expected_target_identity: os.stat_result | None | object = (
        _UNSPECIFIED_IDENTITY
    ),
    root: str | Path | None = None,
) -> Path:
    """Download, verify, and extract an official registry package under ``plugins/``."""
    package_url = (record.package_url or record.download_url or "").strip()
    if not package_url:
        raise PluginPackageNonFallbackError(
            "registry record has no package URL",
            code="package_missing_url",
            user_message="插件索引缺少官方包体地址，请等待维护者修复索引。",
        )
    _validate_package_url(package_url)

    target = registry_package_target(
        record,
        plugins_parent=plugins_parent,
        root=root,
    )
    with _PACKAGE_INSTALL_LOCK:
        _assert_expected_plugin_target_identity(
            target,
            expected_target_identity,
        )
        if target.is_dir() and not overwrite:
            return _verified_plugin_directory(target)

    download_id = str(uuid.uuid4())
    body = _read_url(
        package_url,
        timeout_sec=timeout_sec,
        max_bytes=_max_bytes(),
        download_id=download_id,
    )
    _verify_package(
        body,
        expected_sha256=(record.package_sha256 or record.sha256 or "").strip(),
        expected_size=record.package_size if record.package_size is not None else record.size,
    )
    tmp_root, tmp_root_identity, extracted = _extract_safe_zip(body)
    try:
        with _PACKAGE_INSTALL_LOCK:
            # A peer can finish while this request is downloading.  Recheck
            # the no-overwrite contract at publication time so a stale
            # installer cannot replace the peer's complete tree.
            if path_is_link_or_reparse_point(target):
                raise PluginPackageNonFallbackError(
                    "plugin target must not be a symbolic link",
                    code="package_unsafe_target",
                    user_message="插件安装目录不安全，已阻止覆盖。",
                )
            _assert_expected_plugin_target_identity(
                target,
                expected_target_identity,
            )
            if target.is_dir() and not overwrite:
                return _verified_plugin_directory(target)
            _replace_directory(
                extracted,
                target,
                overwrite=overwrite,
                expected_target_identity=expected_target_identity,
                root=root,
            )
    finally:
        _cleanup_private_tree(
            tmp_root,
            expected_identity=tmp_root_identity,
        )
    return _verified_plugin_directory(target)


def _assert_expected_plugin_target_identity(
    target: Path,
    expected_identity: os.stat_result | None | object,
) -> None:
    if expected_identity is _UNSPECIFIED_IDENTITY:
        return
    try:
        current_identity = target.lstat()
    except FileNotFoundError:
        current_identity = None
    if expected_identity is None:
        if current_identity is not None:
            raise FileExistsError(
                f"plugin target appeared during installation: {target.name}"
            )
        return
    if (
        current_identity is None
        or not os.path.samestat(expected_identity, current_identity)
    ):
        raise PermissionError(
            f"plugin target identity changed during installation: {target}"
        )


def _verified_plugin_directory(target: Path) -> Path:
    exact = require_symlink_free_absolute_path(
        target,
        field="installed plugin directory",
    )
    if not exact.is_dir():
        raise NotADirectoryError(exact)
    return exact
