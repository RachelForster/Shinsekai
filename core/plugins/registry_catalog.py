"""Remote plugin registry for the plugin discovery UI."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_JSON_URL = (
    "https://raw.githubusercontent.com/RachelForster/Shinsekai-Plugin-Registry/main/plugin_cache_original.json"
)
LEGACY_REGISTRY_JSON_URL = (
    "https://raw.githubusercontent.com/RachelForster/Shinsekai-Plugin-Registry/main/plugins.json"
)
REGISTRY_URL_ENV = "SHINSEKAI_PLUGIN_REGISTRY_URL"

_REGISTRY_USER_AGENT = (
    "EasyAIDesktopAssistant/1.0 (+https://github.com/RachelForster/Shinsekai-Plugin-Registry)"
)


@dataclass(frozen=True)
class RegistryPluginRecord:
    """One normalized row from the central plugin registry."""

    id: str
    name: str
    display_name: str
    author: str
    repo: str
    description: str
    short_description: str
    entry: str
    version: str = ""
    lowest_shinsekai_version: str = ""
    source_url: str = ""
    readme_url: str = ""
    download_url: str = ""
    sha256: str = ""
    commit_sha: str = ""
    size: int | None = None
    updated_at: str = ""
    tags: list[str] | None = None
    logo: str = ""
    stars: int = 0
    forks: int = 0
    social_link: str = ""
    package_source: str = ""
    package_url: str = ""
    package_sha256: str = ""
    package_size: int | None = None
    package_r2_key: str = ""
    security_scan: dict[str, Any] | None = None
    trust_level: str = "community"
    verified: bool = False
    review: dict[str, Any] | None = None

    def github_url(self) -> str:
        from core.plugins.registry_download import normalize_repo_slug

        slug = normalize_repo_slug(self.repo)
        return f"https://github.com/{slug}" if slug else ""

    def display_title(self) -> str:
        return self.display_name or self.name or self.repo

    @property
    def normalized_tags(self) -> list[str]:
        return list(self.tags or [])


def _relax_json_trailing_commas(text: str) -> str:
    """Strip trailing commas before ``}`` / ``]`` (common in hand-edited JSON)."""
    return re.sub(r",(\s*[}\]])", r"\1", text.strip())


def _as_string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _as_count(value: Any) -> int:
    number = _as_int(value)
    return number if number is not None else 0


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、\s]+", value) if item.strip()]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return [_as_string(item) for item in value if _as_string(item)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _registry_items(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw, list):
        return [("", item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        plugins = raw.get("plugins")
        if isinstance(plugins, list):
            return [("", item) for item in plugins if isinstance(item, dict)]
        if isinstance(plugins, dict):
            return [(str(key), value) for key, value in plugins.items() if isinstance(value, dict)]
        return [(str(key), value) for key, value in raw.items() if isinstance(value, dict)]
    raise ValueError("registry root must be a JSON array or object")


def parse_registry_plugins(raw: Any) -> list[RegistryPluginRecord]:
    """
    Validate and normalize registry payloads.

    Supported shapes:
    - legacy array: [{ name, author, repo, description, entry }]
    - object map: { "plugin-id": { ...market fields } }
    - schema object: { "schema": 2, "plugins": [...] }
    """
    out: list[RegistryPluginRecord] = []
    for i, (key, item) in enumerate(_registry_items(raw)):
        package = _as_dict(item.get("package"))
        rec_id = _as_string(item.get("id") or key or item.get("name") or item.get("repo"))
        name = _as_string(item.get("name") or rec_id)
        display_name = _as_string(item.get("display_name") or item.get("displayName") or name)
        author = _as_string(item.get("author"))
        repo = _as_string(item.get("repo"))
        description = _as_string(item.get("description") or item.get("desc"))
        short_description = _as_string(
            item.get("short_description") or item.get("short_desc") or item.get("desc") or description
        )
        entry = _as_string(item.get("entry"))
        raw_size = item.get("size") if item.get("size") is not None else package.get("size")
        download_url = _as_string(item.get("download_url") or item.get("downloadUrl") or package.get("url"))
        sha256 = _as_string(item.get("sha256") or package.get("sha256"))
        size = _as_int(raw_size)
        package_url = _as_string(package.get("url") or download_url)
        package_sha256 = _as_string(package.get("sha256") or sha256)
        package_size = _as_int(package.get("size") if package.get("size") is not None else size)

        if not name and not repo:
            raise ValueError(f"registry[{i}] needs at least name or repo")

        out.append(
            RegistryPluginRecord(
                id=rec_id or name or repo,
                name=name or repo,
                display_name=display_name or name or repo,
                author=author,
                repo=repo,
                description=description,
                short_description=short_description,
                entry=entry,
                version=_as_string(item.get("version")),
                lowest_shinsekai_version=_as_string(
                    item.get("lowest_shinsekai_version")
                    or item.get("lowestShinsekaiVersion")
                    or item.get("shinsekai_version")
                    or item.get("shinsekaiVersion")
                ),
                source_url=_as_string(item.get("source_url") or item.get("sourceUrl")),
                readme_url=_as_string(item.get("readme_url") or item.get("readmeUrl")),
                download_url=download_url,
                sha256=sha256,
                commit_sha=_as_string(item.get("commit_sha") or item.get("commitSha")),
                size=size,
                updated_at=_as_string(item.get("updated_at") or item.get("updatedAt")),
                tags=_as_string_list(item.get("tags")),
                logo=_as_string(item.get("logo")),
                stars=_as_count(item.get("stars") if item.get("stars") is not None else item.get("stargazers_count")),
                forks=_as_count(item.get("forks") if item.get("forks") is not None else item.get("forks_count")),
                social_link=_as_string(item.get("social_link") or item.get("socialLink")),
                package_source=_as_string(package.get("source") or ("r2" if package_url else "")),
                package_url=package_url,
                package_sha256=package_sha256,
                package_size=package_size,
                package_r2_key=_as_string(package.get("r2_key") or package.get("r2Key")),
                security_scan=_as_dict(item.get("sec_scan") or item.get("securityScan")),
                trust_level=_as_string(item.get("trust_level") or item.get("trustLevel"), "community") or "community",
                verified=_as_bool(item.get("verified")),
                review=_as_optional_dict(item.get("review")),
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
    explicit_url = url or os.environ.get(REGISTRY_URL_ENV)
    primary = (explicit_url or DEFAULT_REGISTRY_JSON_URL).strip()
    if not primary:
        raise ValueError("empty registry URL")
    targets = [primary] if explicit_url else [primary, LEGACY_REGISTRY_JSON_URL]
    last_error: BaseException | None = None

    for target in targets:
        try:
            req = Request(target, headers={"User-Agent": _REGISTRY_USER_AGENT})
            with urlopen(req, timeout=timeout_sec) as resp:
                body = resp.read().decode("utf-8")

            try:
                raw = json.loads(body)
            except json.JSONDecodeError:
                raw = json.loads(_relax_json_trailing_commas(body))

            return parse_registry_plugins(raw)
        except (HTTPError, URLError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if target == targets[-1]:
                if isinstance(exc, ValueError):
                    logger.exception("invalid registry payload from %s", target)
                raise
            logger.warning("registry fetch failed from %s, trying fallback: %s", target, fetch_registry_error_message(exc))

    if last_error is not None:
        raise last_error
    raise ValueError("empty registry URL")


def fetch_registry_error_message(exc: BaseException) -> str:
    """Short user-facing summary for UI."""
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        reason = exc.reason
        return str(reason) if reason else "network error"
    return str(exc) or type(exc).__name__
