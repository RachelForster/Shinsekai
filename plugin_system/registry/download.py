"""Download registry-listed plugins from GitHub (source archive) + persist 「已下载」 state."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from config.mirror_env import mirror_github_url
from core.archive_paths import extract_zip_safely
from core.file_transactions import (
    atomic_write_text,
    copy_directory_without_links,
    create_private_temporary_directory,
    ensure_portable_name_available,
    private_sibling_path,
    read_text_without_links,
    remove_directory_without_links,
    replace_directory_transactionally,
)
from core.paths import (
    managed_child_path,
    path_is_link_or_reparse_point,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_project_output_path,
    truncate_utf8_bytes,
)

logger = logging.getLogger(__name__)
_PLUGINS_DIR = Path("plugins")
_DOWNLOAD_STATE_PATH = Path("data/config/plugin_registry_downloads.json")
_DOWNLOAD_STATE_LOCK = threading.RLock()


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


_WIN_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    | {
        f"{prefix}{suffix}"
        for prefix in ("COM", "LPT")
        for suffix in (*map(str, range(1, 10)), "¹", "²", "³")
    }
)
_REPO_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _project_scoped_path(
    path: Path,
    *,
    root: str | Path | None = None,
) -> Path:
    if root is None:
        return resolve_project_output_path(path)
    return resolve_project_output_path(path, root=root)


def sanitize_plugins_directory_name(raw: str, *, max_len: int = 120) -> str:
    """
    Make registry ``name`` safe as a single path segment under ``plugins/``.

    Strips control chars and replaces Windows-forbidden filename characters.
    """
    s = raw.strip()
    if not s:
        return ""
    invalid = '<>:"/\\|?*'
    parts: list[str] = []
    for ch in s:
        if (
            ord(ch) < 32
            or ord(ch) == 127
            or 0xD800 <= ord(ch) <= 0xDFFF
        ):
            parts.append("_")
        elif ch in invalid:
            parts.append("_")
        else:
            parts.append(ch)
    s = "".join(parts).strip(" .")
    s = truncate_utf8_bytes(s[:max_len].rstrip(" ."), 255).rstrip(" .")
    # Package directories can be created on one platform and later migrated
    # to Windows, so enforce Windows device-name portability everywhere.
    stem, separator, extension = s.partition(".")
    if stem.upper() in _WIN_RESERVED_DEVICE_NAMES:
        s = f"{stem}_plugin{separator}{extension}"[:max_len].rstrip(" .")
    return truncate_utf8_bytes(s, 255).rstrip(" .")


def portable_plugin_target(parent: Path, folder_name: str) -> Path:
    """Resolve a plugin directory without creating cross-platform aliases.

    Linux permits names such as ``Demo`` and ``demo`` (and distinct Unicode
    normalization forms) side by side, while Windows and common macOS volumes
    do not.  Reject that ambiguity at installation time so a later project
    move cannot merge or overwrite two plugin trees.
    """

    target = managed_child_path(parent, folder_name, field="plugin directory name")
    if not parent.is_dir():
        return target
    try:
        ensure_portable_name_available(parent, folder_name)
    except FileExistsError as exc:
        raise FileExistsError(
            f"plugin directory name collides on a portable filesystem: {exc}"
        ) from exc
    return target

_DL_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+plugin-download; https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)


def normalize_repo_slug(repo: str) -> str:
    raw = str(repo or "")
    if (
        not raw
        or raw != raw.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        return ""
    lowered = raw.lower()
    if lowered.startswith("git@github.com:"):
        raw = raw.split(":", 1)[1]
    elif lowered.startswith(("https://", "http://")):
        parsed = urlsplit(raw)
        try:
            parsed_port = parsed.port
        except ValueError:
            return ""
        if (
            parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed_port is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
        ):
            return ""
        raw = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
    elif lowered.startswith("github.com/"):
        raw = raw.split("/", 1)[1]
    else:
        if "#" in raw or "?" in raw:
            return ""
    if raw.endswith("/"):
        raw = raw[:-1]
    if raw.endswith(".git"):
        raw = raw[:-4]
    parts = raw.split("/")
    if (
        len(parts) != 2
        or any(part in {"", ".", ".."} or part != part.strip() for part in parts)
        or any(not _REPO_COMPONENT_RE.fullmatch(part) for part in parts)
    ):
        return ""
    return "/".join(parts).lower()


def normalize_manifest_entry(entry: str) -> str:
    """
    Align with :func:`plugin_system.host.normalize_manifest_entry`:
    ensure ``plugins.`` prefix for module paths used under ``plugins/``.
    """
    norm = str(entry or "")
    if not norm:
        return norm
    if norm != norm.strip() or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in norm
    ):
        return ""
    if norm.startswith("plugins."):
        return norm
    return f"plugins.{norm}"


def _normalize_install_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "dependencyDetail",
        "dependencyStatus",
        "entry",
        "packageSha256",
        "packageSize",
        "packageSource",
        "packageStatus",
        "packageUrl",
        "refKind",
        "repo",
        "sourceLabel",
        "sourceType",
        "tagName",
    }
    return {key: item for key, item in value.items() if key in allowed and item not in (None, "")}


def _load_download_state_payload(
    *,
    root: str | Path | None = None,
) -> tuple[list[str], dict[str, str], dict[str, dict[str, object]]]:
    with _DOWNLOAD_STATE_LOCK:
        return _load_download_state_payload_unlocked(root=root)


def _load_download_state_payload_unlocked(
    *,
    root: str | Path | None = None,
) -> tuple[list[str], dict[str, str], dict[str, dict[str, object]]]:
    """Load persisted repos, manifest-entry mapping, and install metadata."""
    state_path = _project_scoped_path(_DOWNLOAD_STATE_PATH, root=root)
    if not state_path.is_file():
        return [], {}, {}
    try:
        raw = json.loads(read_text_without_links(state_path))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read plugin download state: %s", state_path)
        return [], {}, {}
    if isinstance(raw, list):
        repos_set = {normalize_repo_slug(str(x)) for x in raw if str(x).strip()}
        return sorted(repos_set), {}, {}
    if not isinstance(raw, dict):
        return [], {}, {}
    repos_raw = raw.get("repos", [])
    er_raw = raw.get("entry_repo", {})
    install_raw = raw.get("entry_install", {})
    repos_set: set[str] = set()
    if isinstance(repos_raw, list):
        for x in repos_raw:
            s = normalize_repo_slug(str(x))
            if s:
                repos_set.add(s)
    entry_repo: dict[str, str] = {}
    if isinstance(er_raw, dict):
        for k, v in er_raw.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            ks, vs = k, v
            if not ks or not vs:
                continue
            nk = normalize_manifest_entry(ks)
            nv = normalize_repo_slug(vs)
            if nk and nv:
                entry_repo[nk] = nv
    entry_install: dict[str, dict[str, object]] = {}
    if isinstance(install_raw, dict):
        for k, v in install_raw.items():
            if not isinstance(k, str):
                continue
            nk = normalize_manifest_entry(k)
            metadata = _normalize_install_metadata(v)
            if nk and metadata:
                entry_install[nk] = metadata
    return sorted(repos_set), entry_repo, entry_install


def _load_download_state(
    *,
    root: str | Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Load persisted repos (sorted) and manifest-entry -> repo slug mapping."""
    repos, entry_repo, _entry_install = _load_download_state_payload(root=root)
    return repos, entry_repo


def _write_download_state(
    repos: list[str],
    entry_repo: dict[str, str],
    entry_install: dict[str, dict[str, object]] | None = None,
    *,
    root: str | Path | None = None,
) -> None:
    if entry_install is None:
        _repos, _entry_repo, entry_install = _load_download_state_payload(
            root=root,
        )
    state_path = _project_scoped_path(_DOWNLOAD_STATE_PATH, root=root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repos": repos, "entry_repo": entry_repo, "entry_install": entry_install}
    atomic_write_text(
        state_path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def load_downloaded_repos(
    *,
    root: str | Path | None = None,
) -> set[str]:
    """Normalized ``owner/repo`` keys marked as downloaded by this app."""
    repos, _ = _load_download_state(root=root)
    return set(repos)


def load_plugin_install_metadata(
    entry: str,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Return persisted install metadata for a manifest entry."""
    norm_e = normalize_manifest_entry(entry)
    if not norm_e:
        return {}
    _repos, _entry_repo, entry_install = _load_download_state_payload(root=root)
    return dict(entry_install.get(norm_e) or {})


def mark_repo_downloaded(
    repo: str,
    *,
    manifest_entry: str | None = None,
    install_metadata: dict[str, object] | None = None,
    root: str | Path | None = None,
) -> None:
    with _DOWNLOAD_STATE_LOCK:
        _mark_repo_downloaded_unlocked(
            repo,
            manifest_entry=manifest_entry,
            install_metadata=install_metadata,
            root=root,
        )


def _mark_repo_downloaded_unlocked(
    repo: str,
    *,
    manifest_entry: str | None = None,
    install_metadata: dict[str, object] | None = None,
    root: str | Path | None = None,
) -> None:
    slug = normalize_repo_slug(repo)
    if not slug:
        return
    repos_list, er, entry_install = _load_download_state_payload(root=root)
    repos_set = set(repos_list)
    repos_set.add(slug)
    er = dict(er)
    entry_install = dict(entry_install)
    me = manifest_entry or ""
    if me:
        norm_e = normalize_manifest_entry(me)
        if not norm_e:
            raise ValueError("manifest entry is not an exact portable value")
        er[norm_e] = slug
        metadata = _normalize_install_metadata(install_metadata or {})
        if metadata:
            entry_install[norm_e] = metadata
        elif install_metadata is not None:
            entry_install.pop(norm_e, None)
    _write_download_state(
        sorted(repos_set),
        er,
        entry_install,
        root=root,
    )


def unmark_repo_downloaded(
    repo: str,
    *,
    root: str | Path | None = None,
) -> None:
    """Remove ``owner/repo`` and any manifest entries pointing at it."""
    with _DOWNLOAD_STATE_LOCK:
        _unmark_repo_downloaded_unlocked(repo, root=root)


def _unmark_repo_downloaded_unlocked(
    repo: str,
    *,
    root: str | Path | None = None,
) -> None:
    slug = normalize_repo_slug(repo)
    if not slug:
        return
    repos_list, er, entry_install = _load_download_state_payload(root=root)
    removed_entries = {k for k, v in er.items() if normalize_repo_slug(v) == slug}
    er = {k: v for k, v in er.items() if k not in removed_entries}
    entry_install = {k: v for k, v in entry_install.items() if k not in removed_entries}
    repos_set = set(repos_list)
    repos_set.discard(slug)
    _write_download_state(
        sorted(repos_set),
        er,
        entry_install,
        root=root,
    )


def unmark_repo_for_manifest_entry(
    entry: str,
    *,
    root: str | Path | None = None,
) -> bool:
    """
    Drop the download-registry mapping for this manifest ``entry`` and unlist the repo if unused.

    Returns True if the state file was updated.
    """
    with _DOWNLOAD_STATE_LOCK:
        return _unmark_repo_for_manifest_entry_unlocked(entry, root=root)


def _unmark_repo_for_manifest_entry_unlocked(
    entry: str,
    *,
    root: str | Path | None = None,
) -> bool:
    norm_e = normalize_manifest_entry(entry)
    if not norm_e:
        return False
    repos_list, er, entry_install = _load_download_state_payload(root=root)
    if norm_e not in er:
        return False
    er = dict(er)
    entry_install = dict(entry_install)
    slug = normalize_repo_slug(er.pop(norm_e))
    entry_install.pop(norm_e, None)
    others = {normalize_repo_slug(v) for v in er.values()}
    repos_set = set(repos_list)
    if slug not in others:
        repos_set.discard(slug)
    _write_download_state(
        sorted(repos_set),
        er,
        entry_install,
        root=root,
    )
    return True


def _github_archive_zip_url(repo_slug: str, branch: str) -> str:
    base = normalize_repo_slug(repo_slug)
    if not base:
        raise ValueError("repository must be an exact GitHub owner/name reference")
    return mirror_github_url(f"https://github.com/{base}/archive/refs/heads/{branch}.zip")


def download_github_repo_sources(
    repo: str,
    *,
    plugins_parent: Path | None = None,
    timeout_sec: float = 180.0,
    progress: Callable[[int, int | None], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    folder_name: str | None = None,
    root: str | Path | None = None,
) -> Path:
    """
    Download ``owner/repo`` default branch (``main`` then ``master``) ZIP and extract under ``plugins/``.

    If ``folder_name`` is set (registry display name), the extracted top-level directory is renamed to
    a sanitized form so ``plugins/<name>/`` matches the catalog title.

    If the target folder already exists, returns its path without overwriting (idempotent).

    :returns: Path to the extracted repository root directory inside ``plugins``.
    """
    slug = normalize_repo_slug(repo)
    if not slug:
        raise ValueError(f"invalid repo slug (need owner/name): {repo!r}")

    configured_parent = (
        os.fspath(plugins_parent)
        if plugins_parent is not None
        else os.fspath(_project_scoped_path(_PLUGINS_DIR, root=root))
    )
    unresolved_parent = Path(configured_parent)
    if not unresolved_parent.is_absolute():
        raise ValueError("plugins_parent must be absolute")
    parent = require_symlink_free_absolute_path(
        unresolved_parent,
        field="plugins directory",
    )
    parent = resolve_project_output_path(configured_parent, root=root)
    parent.mkdir(parents=True, exist_ok=True)
    parent = require_directory_without_links(
        parent,
        field="plugins directory",
    )

    last_err: BaseException | None = None
    body: bytes | None = None
    for branch in ("main", "master"):
        url = _github_archive_zip_url(slug, branch)
        req = Request(url, headers={"User-Agent": _DL_USER_AGENT})
        try:
            with urlopen(req, timeout=timeout_sec) as resp:
                total: int | None = None
                cl = resp.headers.get("Content-Length")
                if cl is not None and str(cl).isdigit():
                    total = int(cl)
                chunks: list[bytes] = []
                read = 0
                while True:
                    block = resp.read(65536)
                    if not block:
                        break
                    chunks.append(block)
                    read += len(block)
                    if progress is not None:
                        progress(read, total)
                body = b"".join(chunks)
            break
        except HTTPError as e:
            last_err = e
            if e.code != 404:
                raise
        except URLError as e:
            last_err = e
            break
    if body is None:
        raise last_err if last_err else URLError("download failed")

    temp_root, temp_root_identity = create_private_temporary_directory(
        prefix="shinsekai-github-plugin-",
    )
    try:
        extract_root = temp_root / "extract"
        if on_phase is not None:
            on_phase("extract")
        with zipfile.ZipFile(BytesIO(body)) as zf:
            extraction = extract_zip_safely(
                zf,
                extract_root,
                require_single_root=True,
            )
        top = extraction.top_level
        if not top:
            raise ValueError("archive has no top-level directory")
        extracted_path = extract_root / top
        folder_final = (
            sanitize_plugins_directory_name(folder_name.strip())
            if (folder_name and folder_name.strip())
            else ""
        )
        # Recheck the caller-owned publication boundary after the network and
        # extraction delay; a linked managed parent must never redirect the
        # existence checks or final rename outside the project.
        parent = require_symlink_free_absolute_path(
            parent,
            field="plugins directory",
        )
        parent = resolve_project_output_path(parent, root=root)
        target_path = portable_plugin_target(parent, folder_final or top)

        if target_path.is_dir():
            target_path = require_symlink_free_absolute_path(
                target_path,
                field="installed plugin directory",
            )
            if not target_path.is_dir():
                raise NotADirectoryError(target_path)
            logger.info("Plugin folder already exists: %s", target_path)
            return target_path
        if target_path.exists():
            raise FileExistsError(f"Plugin target is not a directory: {target_path.name!r}")

        if not extracted_path.is_dir():
            raise RuntimeError(f"extract finished but folder missing: {extracted_path}")
        staging = private_sibling_path(
            target_path,
            f".install-{uuid.uuid4().hex}",
            field="plugin installation staging directory",
        )
        staging_identity: os.stat_result | None = None
        try:
            staging = copy_directory_without_links(extracted_path, staging)
            staging_identity = staging.lstat()
            replace_directory_transactionally(
                staging,
                target_path,
                overwrite=False,
                expected_staging_identity=staging_identity,
                expected_destination_identity=None,
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
        target_path = require_symlink_free_absolute_path(
            target_path,
            field="installed plugin directory",
        )
        if not target_path.is_dir():
            raise NotADirectoryError(target_path)
        return target_path
    finally:
        _cleanup_private_tree(
            temp_root,
            expected_identity=temp_root_identity,
        )


def format_download_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        r = exc.reason
        return str(r) if r else "network error"
    return str(exc) or type(exc).__name__
