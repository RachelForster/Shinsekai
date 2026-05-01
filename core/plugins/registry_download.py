"""Download registry-listed plugins from GitHub (source archive) + persist 「已下载」 state."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_DOWNLOAD_STATE_PATH = Path("data/config/plugin_registry_downloads.json")
_PLUGINS_DIR = Path("plugins")

_DL_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+plugin-download; https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)


def normalize_repo_slug(repo: str) -> str:
    parts = [p.strip() for p in repo.strip().strip("/").split("/") if p.strip()]
    return "/".join(parts).lower()


def load_downloaded_repos() -> set[str]:
    """Normalized ``owner/repo`` keys marked as downloaded by this app."""
    if not _DOWNLOAD_STATE_PATH.is_file():
        return set()
    try:
        raw = json.loads(_DOWNLOAD_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read plugin download state: %s", _DOWNLOAD_STATE_PATH)
        return set()
    if isinstance(raw, dict) and isinstance(raw.get("repos"), list):
        return {normalize_repo_slug(str(x)) for x in raw["repos"]}
    if isinstance(raw, list):
        return {normalize_repo_slug(str(x)) for x in raw}
    return set()


def mark_repo_downloaded(repo: str) -> None:
    slug = normalize_repo_slug(repo)
    if not slug:
        return
    repos = load_downloaded_repos()
    repos.add(slug)
    _DOWNLOAD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repos": sorted(repos)}
    _DOWNLOAD_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _github_archive_zip_url(repo_slug: str, branch: str) -> str:
    base = "/".join(p.strip() for p in repo_slug.strip().strip("/").split("/") if p.strip())
    return f"https://github.com/{base}/archive/refs/heads/{branch}.zip"


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
) -> Path:
    """
    Download ``owner/repo`` default branch (``main`` then ``master``) ZIP and extract under ``plugins/``.

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
        dest = parent / top
        if dest.is_dir():
            logger.info("Plugin folder already exists, skipping extract: %s", dest)
            return dest.resolve()

        if on_phase is not None:
            on_phase("extract")
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(parent)
        if not dest.is_dir():
            raise RuntimeError(f"extract finished but folder missing: {dest}")
        return dest.resolve()
    finally:
        tmp_path.unlink(missing_ok=True)


def format_download_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        r = exc.reason
        return str(r) if r else "network error"
    return str(exc) or type(exc).__name__
