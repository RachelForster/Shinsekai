from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


MAX_DESC_CHARS = 200
REQUIRED_FIELDS = ("display_name", "desc", "author", "repo")
SLUG_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TAG_SPLIT_RE = re.compile(r"[,\s\uFF0C\u3001]+")


class PluginSubmissionError(ValueError):
    """Raised when plugin submission metadata does not match the registry contract."""


def as_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def require_string(payload: dict[str, Any], field: str) -> str:
    value = as_string(payload.get(field))
    if not value:
        raise PluginSubmissionError(f"{field} is required and must be a non-empty string.")
    return value


def optional_string(payload: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = as_string(payload.get(field))
        if value:
            return value
    return ""


def normalize_github_repo_url(value: Any) -> str:
    repo_url = as_string(value)
    if not repo_url:
        raise PluginSubmissionError("repo must be a GitHub URL string.")
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise PluginSubmissionError("repo must use https://github.com/{owner}/{repo}.")
    if parsed.query or parsed.fragment:
        raise PluginSubmissionError("repo URL must not include query strings or fragments.")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or not all(SLUG_PART_RE.fullmatch(part) for part in parts):
        raise PluginSubmissionError("repo must use https://github.com/{owner}/{repo}.")
    repo_name = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    if not repo_name or not SLUG_PART_RE.fullmatch(repo_name):
        raise PluginSubmissionError("repo must use https://github.com/{owner}/{repo}.")
    return f"https://github.com/{parts[0]}/{repo_name}"


def normalize_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        tags = [part.strip() for part in TAG_SPLIT_RE.split(value) if part.strip()]
    elif isinstance(value, list):
        tags = []
        for item in value:
            tag = as_string(item)
            if not tag:
                raise PluginSubmissionError("tags must contain non-empty strings only.")
            tags.append(tag)
    else:
        raise PluginSubmissionError("tags must be an array of strings or a comma-separated string.")
    if len(tags) > 5:
        raise PluginSubmissionError("tags must contain at most 5 items.")
    return tags


def normalize_submission(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PluginSubmissionError("submission must be a JSON object.")

    for field in REQUIRED_FIELDS:
        require_string(payload, field)

    desc = require_string(payload, "desc")
    if len(desc) > MAX_DESC_CHARS:
        raise PluginSubmissionError(f"desc must be {MAX_DESC_CHARS} characters or fewer.")

    normalized = {
        "display_name": require_string(payload, "display_name"),
        "desc": desc,
        "author": require_string(payload, "author"),
        "social_link": as_string(payload.get("social_link")),
        "repo": normalize_github_repo_url(payload.get("repo")),
        "tags": normalize_tags(payload.get("tags")),
    }
    lowest_shinsekai_version = optional_string(
        payload,
        "lowest_shinsekai_version",
        "lowestShinsekaiVersion",
        "shinsekai_version",
        "shinsekaiVersion",
    )
    if lowest_shinsekai_version:
        normalized["lowest_shinsekai_version"] = lowest_shinsekai_version
    return normalized


def validation_errors(payload: dict[str, Any]) -> list[str]:
    try:
        normalize_submission(payload)
    except PluginSubmissionError as exc:
        return [str(exc)]
    return []
