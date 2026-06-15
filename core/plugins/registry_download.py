"""Download registry-listed plugins from GitHub (source archive) + persist 「已下载」 state."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from config.mirror_env import mirror_github_url

logger = logging.getLogger(__name__)
_PLUGINS_DIR = Path("plugins")
_DOWNLOAD_STATE_PATH = Path("data/config/plugin_registry_downloads.json")

_WIN_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


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
        if ord(ch) < 32:
            parts.append("_")
        elif ch in invalid:
            parts.append("_")
        else:
            parts.append(ch)
    s = "".join(parts).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    if sys.platform == "win32":
        stem = s.rstrip(".").upper()
        if stem in _WIN_RESERVED_DEVICE_NAMES:
            s = f"{s}_plugin"
    return s

_DL_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+plugin-download; https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)


def normalize_repo_slug(repo: str) -> str:
    raw = repo.strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("git@github.com:"):
        raw = raw.split(":", 1)[1]
    elif lowered.startswith("https://github.com/") or lowered.startswith("http://github.com/"):
        raw = raw.split("github.com/", 1)[1]
    elif lowered.startswith("github.com/"):
        raw = raw.split("/", 1)[1]
    raw = raw.split("#", 1)[0].split("?", 1)[0].strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) < 2:
        return ""
    return "/".join(parts[:2]).lower()


def normalize_manifest_entry(entry: str) -> str:
    """
    Align with :func:`core.plugins.plugin_host.normalize_manifest_entry`:
    ensure ``plugins.`` prefix for module paths used under ``plugins/``.
    """
    norm = entry.strip()
    if not norm:
        return norm
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


def _load_download_state_payload() -> tuple[list[str], dict[str, str], dict[str, dict[str, object]]]:
    """Load persisted repos, manifest-entry mapping, and install metadata."""
    if not _DOWNLOAD_STATE_PATH.is_file():
        return [], {}, {}
    try:
        raw = json.loads(_DOWNLOAD_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read plugin download state: %s", _DOWNLOAD_STATE_PATH)
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
            ks, vs = k.strip(), v.strip()
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
            nk = normalize_manifest_entry(k.strip())
            metadata = _normalize_install_metadata(v)
            if nk and metadata:
                entry_install[nk] = metadata
    return sorted(repos_set), entry_repo, entry_install


def _load_download_state() -> tuple[list[str], dict[str, str]]:
    """Load persisted repos (sorted) and manifest-entry -> repo slug mapping."""
    repos, entry_repo, _entry_install = _load_download_state_payload()
    return repos, entry_repo


def _write_download_state(
    repos: list[str],
    entry_repo: dict[str, str],
    entry_install: dict[str, dict[str, object]] | None = None,
) -> None:
    if entry_install is None:
        _repos, _entry_repo, entry_install = _load_download_state_payload()
    _DOWNLOAD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repos": repos, "entry_repo": entry_repo, "entry_install": entry_install}
    _DOWNLOAD_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_downloaded_repos() -> set[str]:
    """Normalized ``owner/repo`` keys marked as downloaded by this app."""
    repos, _ = _load_download_state()
    return set(repos)


def load_plugin_install_metadata(entry: str) -> dict[str, object]:
    """Return persisted install metadata for a manifest entry."""
    norm_e = normalize_manifest_entry(entry.strip())
    if not norm_e:
        return {}
    _repos, _entry_repo, entry_install = _load_download_state_payload()
    return dict(entry_install.get(norm_e) or {})


def mark_repo_downloaded(
    repo: str,
    *,
    manifest_entry: str | None = None,
    install_metadata: dict[str, object] | None = None,
) -> None:
    slug = normalize_repo_slug(repo)
    if not slug:
        return
    repos_list, er, entry_install = _load_download_state_payload()
    repos_set = set(repos_list)
    repos_set.add(slug)
    er = dict(er)
    entry_install = dict(entry_install)
    me = (manifest_entry or "").strip()
    if me:
        norm_e = normalize_manifest_entry(me)
        er[norm_e] = slug
        metadata = _normalize_install_metadata(install_metadata or {})
        if metadata:
            entry_install[norm_e] = metadata
        elif install_metadata is not None:
            entry_install.pop(norm_e, None)
    _write_download_state(sorted(repos_set), er, entry_install)


def unmark_repo_downloaded(repo: str) -> None:
    """Remove ``owner/repo`` and any manifest entries pointing at it."""
    slug = normalize_repo_slug(repo)
    if not slug:
        return
    repos_list, er, entry_install = _load_download_state_payload()
    removed_entries = {k for k, v in er.items() if normalize_repo_slug(v) == slug}
    er = {k: v for k, v in er.items() if k not in removed_entries}
    entry_install = {k: v for k, v in entry_install.items() if k not in removed_entries}
    repos_set = set(repos_list)
    repos_set.discard(slug)
    _write_download_state(sorted(repos_set), er, entry_install)


def unmark_repo_for_manifest_entry(entry: str) -> bool:
    """
    Drop the download-registry mapping for this manifest ``entry`` and unlist the repo if unused.

    Returns True if the state file was updated.
    """
    norm_e = normalize_manifest_entry(entry.strip())
    if not norm_e:
        return False
    repos_list, er, entry_install = _load_download_state_payload()
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
    _write_download_state(sorted(repos_set), er, entry_install)
    return True


def _github_archive_zip_url(repo_slug: str, branch: str) -> str:
    base = "/".join(p.strip() for p in repo_slug.strip().strip("/").split("/") if p.strip())
    return mirror_github_url(f"https://github.com/{base}/archive/refs/heads/{branch}.zip")


def _archive_top_prefix(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            raise ValueError("empty archive")
        top = names[0].split("/")[0]
        if not top:
            raise ValueError("invalid archive layout")
        return top


def download_github_repo_sources(
    repo: str,
    *,
    plugins_parent: Path | None = None,
    timeout_sec: float = 180.0,
    progress: Callable[[int, int | None], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    folder_name: str | None = None,
) -> Path:
    """
    Download ``owner/repo`` default branch (``main`` then ``master``) ZIP and extract under ``plugins/``.

    If ``folder_name`` is set (registry display name), the extracted top-level directory is renamed to
    a sanitized form so ``plugins/<name>/`` matches the catalog title.

    If the target folder already exists, returns its path without overwriting (idempotent).

    :returns: Path to the extracted repository root directory inside ``plugins``.
    """
    slug = "/".join(p.strip() for p in repo.strip().strip("/").split("/") if p.strip())
    if slug.count("/") < 1:
        raise ValueError(f"invalid repo slug (need owner/name): {repo!r}")

    parent = Path(plugins_parent) if plugins_parent is not None else _PLUGINS_DIR
    parent.mkdir(parents=True, exist_ok=True)

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

    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    tmp_path = Path(tmp_zip)
    try:
        tmp_path.write_bytes(body)
        top = _archive_top_prefix(tmp_path)
        extracted_path = parent / top
        folder_final = (
            sanitize_plugins_directory_name(folder_name.strip())
            if (folder_name and folder_name.strip())
            else ""
        )
        target_path = parent / folder_final if folder_final else extracted_path

        if folder_final and target_path.is_dir():
            logger.info("Plugin folder already exists (catalog name): %s", target_path)
            return target_path.resolve()

        if extracted_path.is_dir():
            if folder_final and extracted_path.resolve() != target_path.resolve():
                if target_path.exists():
                    raise FileExistsError(
                        f"Cannot rename extracted folder to {target_path.name!r}: target exists"
                    )
                extracted_path.rename(target_path)
                return target_path.resolve()
            return extracted_path.resolve()

        if on_phase is not None:
            on_phase("extract")
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(parent)
        if not extracted_path.is_dir():
            raise RuntimeError(f"extract finished but folder missing: {extracted_path}")

        if folder_final and extracted_path.resolve() != target_path.resolve():
            if target_path.exists():
                raise FileExistsError(
                    f"Cannot rename extracted folder to {target_path.name!r}: target exists"
                )
            extracted_path.rename(target_path)
            return target_path.resolve()
        return extracted_path.resolve()
    finally:
        tmp_path.unlink(missing_ok=True)


def format_download_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        r = exc.reason
        return str(r) if r else "network error"
    return str(exc) or type(exc).__name__
