"""Remote plugin registry (plugins.json) for the 「发现插件」 UI."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_JSON_URL = (
    "https://raw.githubusercontent.com/RachelForster/Shinsekai-Plugin-Registry/main/plugins.json"
)

_REGISTRY_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)


@dataclass(frozen=True)
class RegistryPluginRecord:
    """One row from the central ``plugins.json`` catalog."""

    name: str
    author: str
    repo: str
    description: str
    entry: str
    commit_sha: str = ""
    archive_sha256: str = ""

    def github_url(self) -> str:
        slug = self.repo.strip().strip("/")
        return f"https://github.com/{slug}"


def _relax_json_trailing_commas(text: str) -> str:
    """Strip trailing commas before ``}`` / ``]`` (common in hand-edited JSON)."""
    return re.sub(r",(\s*[}\]])", r"\1", text.strip())


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _normalize_commit_sha(raw: Any, *, index: int) -> str:
    value = _as_str(raw).strip() if raw is not None else ""
    if not value:
        return ""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise ValueError(f"registry[{index}] commit_sha must be a 40-character hex SHA")
    return value.lower()


def _normalize_archive_sha256(raw: Any, *, index: int) -> str:
    value = _as_str(raw).strip() if raw is not None else ""
    if not value:
        return ""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"registry[{index}] archive_sha256 must be a 64-character hex digest")
    return value.lower()


def parse_registry_plugins(raw: Any) -> list[RegistryPluginRecord]:
    """
    Validate and normalize API payload: must be a JSON array of objects with string fields.
    Missing optional fields become empty strings.
    Rows with malformed optional provenance metadata are skipped instead of
    weakening verification for that row or failing the whole catalog.
    """
    if not isinstance(raw, list):
        raise ValueError("registry root must be a JSON array")
    out: list[RegistryPluginRecord] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"registry[{i}] must be an object")
        name = _as_str(item.get("name", ""))
        author = _as_str(item.get("author", ""))
        repo = _as_str(item.get("repo", ""))
        description = _as_str(item.get("description", ""))
        entry = _as_str(item.get("entry", ""))
        name, author, repo, description, entry = (
            name.strip(),
            author.strip(),
            repo.strip(),
            description.strip(),
            entry.strip(),
        )
        try:
            commit_sha = _normalize_commit_sha(item.get("commit_sha", ""), index=i)
            archive_sha256 = _normalize_archive_sha256(
                item.get("archive_sha256", ""),
                index=i,
            )
        except ValueError:
            logger.warning("skipping registry[%s] with invalid provenance metadata", i)
            continue
        if not name and not repo:
            raise ValueError(f"registry[{i}] needs at least name or repo")
        out.append(
            RegistryPluginRecord(
                name=name or repo,
                author=author,
                repo=repo,
                description=description,
                entry=entry,
                commit_sha=commit_sha,
                archive_sha256=archive_sha256,
            )
        )
    return out


def fetch_registry_plugins(
    url: str | None = None,
    *,
    timeout_sec: float = 20.0,
) -> list[RegistryPluginRecord]:
    """
    GET registry JSON and return parsed records.

    :raises ValueError: invalid JSON shape
    :raises urllib.error.HTTPError: HTTP failure
    :raises urllib.error.URLError: network / TLS failure
    """
    target = (url or DEFAULT_REGISTRY_JSON_URL).strip()
    if not target:
        raise ValueError("empty registry URL")

    req = Request(target, headers={"User-Agent": _REGISTRY_USER_AGENT})
    with urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8")

    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        raw = json.loads(_relax_json_trailing_commas(body))

    try:
        return parse_registry_plugins(raw)
    except ValueError:
        logger.exception("invalid registry payload from %s", target)
        raise


def fetch_registry_error_message(exc: BaseException) -> str:
    """Short user-facing summary for UI."""
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        reason = exc.reason
        return str(reason) if reason else "network error"
    return str(exc) or type(exc).__name__
