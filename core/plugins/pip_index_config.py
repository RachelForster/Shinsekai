"""Shared pip index selection for runtime and plugin dependency installs."""

from __future__ import annotations

import json
import os
from pathlib import Path

_PIP_INDEX_FLAGS = frozenset({"-i", "--index-url", "--no-index"})
_DEFAULT_OFFICIAL_INDEXES = ["https://pypi.org/simple/"]
_DEFAULT_CHINA_INDEXES = [
    "https://pypi.tuna.tsinghua.edu.cn/simple/",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://mirrors.ustc.edu.cn/pypi/simple/",
    "https://mirrors.hit.edu.cn/pypi/web/simple/",
]


def has_explicit_pip_index(args: list[str]) -> bool:
    for arg in args:
        if arg in _PIP_INDEX_FLAGS:
            return True
        if arg.startswith("--index-url="):
            return True
        if arg.startswith("-i") and arg != "-i":
            return True
    return False


def pip_index_args(*, primary_flag: str = "--index-url") -> list[str]:
    urls = pip_index_urls()
    if not urls:
        return []
    args = [primary_flag, urls[0]]
    for url in urls[1:]:
        args.extend(["--extra-index-url", url])
    return args


def pip_index_urls(source_root: Path | None = None) -> list[str]:
    """Return pip indexes for this install, preferring China mirrors by default."""
    if os.environ.get("PIP_INDEX_URL") or os.environ.get("PIP_CONFIG_FILE"):
        return []

    custom_urls = _configured_urls_from_env()
    if custom_urls:
        return custom_urls

    official, china = _manifest_pip_indexes(source_root)
    source = os.environ.get("SHINSEKAI_RUNTIME_SOURCE", "").strip().lower()
    if source == "official":
        return official
    if source == "china":
        return _ordered_urls(china, official)
    return _ordered_urls(china, official)


def _configured_urls_from_env() -> list[str]:
    urls: list[str] = []
    _push_url(urls, os.environ.get("SHINSEKAI_PIP_INDEX_URL"))
    for raw in _split_env_urls(os.environ.get("SHINSEKAI_PIP_INDEX_URLS")):
        _push_url(urls, raw)
    return urls


def _manifest_pip_indexes(source_root: Path | None) -> tuple[list[str], list[str]]:
    manifest = _load_runtime_manifest(source_root)
    if not isinstance(manifest, dict):
        return _DEFAULT_OFFICIAL_INDEXES, _DEFAULT_CHINA_INDEXES
    pip_indexes = manifest.get("pip_indexes")
    if not isinstance(pip_indexes, dict):
        return _DEFAULT_OFFICIAL_INDEXES, _DEFAULT_CHINA_INDEXES

    official = _source_urls(
        pip_indexes.get("official"),
        pip_indexes.get("official_urls"),
        _DEFAULT_OFFICIAL_INDEXES,
    )
    china = _source_urls(
        pip_indexes.get("china"),
        pip_indexes.get("china_urls"),
        _DEFAULT_CHINA_INDEXES,
    )
    return official, china


def _load_runtime_manifest(source_root: Path | None) -> dict[str, object] | None:
    candidates: list[Path] = []
    env_path = os.environ.get("SHINSEKAI_RUNTIME_MANIFEST")
    if env_path:
        candidates.append(Path(env_path))
    for root in _source_root_candidates(source_root):
        candidates.append(root / "frontend" / "src-tauri" / "runtime_manifest.json")
    for candidate in candidates:
        try:
            with candidate.expanduser().resolve().open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _source_root_candidates(source_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if source_root is not None:
        candidates.append(source_root)
    for env_name in ("SHINSEKAI_SOURCE_ROOT", "SHINSEKAI_PROJECT_ROOT", "EASYAI_PROJECT_ROOT"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value))
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parents[2])
    return _unique_paths(candidates)


def _source_urls(single_index: object, index_urls: object, fallback: list[str]) -> list[str]:
    urls: list[str] = []
    if isinstance(single_index, str):
        _push_url(urls, single_index)
    if isinstance(index_urls, list):
        for url in index_urls:
            if isinstance(url, str):
                _push_url(urls, url)
    return urls or list(fallback)


def _split_env_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    urls: list[str] = []
    for line in raw.splitlines():
        for part in line.split(","):
            _push_url(urls, part)
    return urls


def _ordered_urls(primary: list[str], fallback: list[str]) -> list[str]:
    urls: list[str] = []
    for url in [*primary, *fallback]:
        _push_url(urls, url)
    return urls


def _push_url(urls: list[str], raw: str | None) -> None:
    url = (raw or "").strip()
    if url and url not in urls:
        urls.append(url)


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.expanduser().resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique
